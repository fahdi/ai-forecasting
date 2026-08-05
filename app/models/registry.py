"""
Model registry with promotion gate (issue #6, PRD §4.1 R5).

File-based: a JSON index plus one artifact directory per version. A candidate
is promoted only if it beats the incumbent on the primary validation metric;
rollback to the previous active version is a single operation.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PRIMARY_METRIC = "directional_accuracy"


class PromotionRejected(Exception):
    pass


class ModelRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "registry.json"
        self._index = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._index_path.exists():
            index = json.loads(self._index_path.read_text())
            index.setdefault("rejected", [])
            return index
        return {"versions": {}, "active": None, "history": [], "rejected": []}

    def _save(self) -> None:
        """Write via a temp file in the same directory, then os.replace.

        A bare write_text truncates first, and the API reads this file through
        ensemble_predictor.load_active(); signal_service.get_predictor()
        swallows a read failure into None and silently serves the baseline EMA
        rule instead. A half-written index therefore costs the real model with
        no signal that it happened. Same discipline as scripts/prod_backup.py.
        """
        payload = json.dumps(self._index, indent=2)
        handle, temp_name = tempfile.mkstemp(
            dir=str(self.root), prefix=".registry-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w") as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_name, self._index_path)
        except BaseException:
            # Leave the previous index untouched rather than half-replaced.
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def artifact_dir(self, version_id: str) -> Path:
        path = self.root / version_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def register(
        self,
        version_id: str,
        metrics: Dict[str, float],
        feature_schema: List[str],
        training_window: Dict[str, str],
    ) -> Dict[str, Any]:
        if version_id in self._index["versions"]:
            raise ValueError(f"model version '{version_id}' already exists")
        if PRIMARY_METRIC not in metrics:
            raise ValueError(f"metrics must include '{PRIMARY_METRIC}'")
        record = {
            "version_id": version_id,
            "metrics": metrics,
            "feature_schema": feature_schema,
            "training_window": training_window,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._index["versions"][version_id] = record
        self._save()
        return record

    def get(self, version_id: str) -> Dict[str, Any]:
        return self._index["versions"][version_id]

    def active_version(self) -> Optional[str]:
        return self._index["active"]

    def promote(self, version_id: str, decision: Optional[Any] = None) -> None:
        """Promotion gate (R5): the candidate must beat the incumbent.

        With a `decision` from app.models.promotion.decide() that verdict is
        authoritative and its evidence is stored, so registry.json alone
        answers "why is this version active". Without one, the legacy
        stored-metric comparison is preserved unchanged for hand-run training.
        """
        candidate = self._index["versions"][version_id]
        incumbent_id = self._index["active"]

        if decision is not None:
            if not decision.promote:
                raise PromotionRejected(decision.reason)
            candidate["promotion_evidence"] = {
                "status": decision.status,
                "reason": decision.reason,
                "evidence": decision.evidence,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
        elif incumbent_id is not None:
            incumbent = self._index["versions"][incumbent_id]
            candidate_score = candidate["metrics"][PRIMARY_METRIC]
            incumbent_score = incumbent["metrics"][PRIMARY_METRIC]
            if candidate_score <= incumbent_score:
                raise PromotionRejected(
                    f"candidate '{version_id}' ({candidate_score}) does not beat "
                    f"incumbent '{incumbent_id}' ({incumbent_score})"
                )

        if incumbent_id is not None:
            self._index["history"].append(incumbent_id)
        self._index["active"] = version_id
        self._save()

    def record_rejection(self, version_id: str, decision: Any) -> None:
        """Keep a losing candidate on the record instead of letting it vanish.

        Without this the only trace of a rejected retrain is a log line on a
        host nobody reads, so there is no way to tell a gate that is working
        from a trainer that silently stopped producing candidates.
        """
        self._index.setdefault("rejected", []).append(
            {
                "version_id": version_id,
                "status": decision.status,
                "reason": decision.reason,
                "evidence": decision.evidence,
                "rejected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save()

    def prune(self, keep: int = 5) -> List[str]:
        """Drop old version records, keeping `keep` recent ones.

        The active version and everything reachable through the rollback
        history are never removed: pruning must not be able to break a
        rollback or leave load_active() pointing at nothing.
        """
        protected = set(self._index["history"])
        if self._index["active"] is not None:
            protected.add(self._index["active"])

        candidates = [v for v in self._index["versions"] if v not in protected]
        # Newest last by insertion order, which matches registration order.
        removable = candidates[: max(0, len(candidates) - keep)]
        for version_id in removable:
            del self._index["versions"][version_id]
        if removable:
            self._save()
        return removable

    def rollback(self) -> str:
        if not self._index["history"]:
            raise RuntimeError("no previous active version to roll back to")
        previous = self._index["history"].pop()
        self._index["active"] = previous
        self._save()
        return previous
