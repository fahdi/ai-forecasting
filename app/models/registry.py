"""
Model registry with promotion gate (issue #6, PRD §4.1 R5).

File-based: a JSON index plus one artifact directory per version. A candidate
is promoted only if it beats the incumbent on the primary validation metric;
rollback to the previous active version is a single operation.
"""

import json
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
            return json.loads(self._index_path.read_text())
        return {"versions": {}, "active": None, "history": []}

    def _save(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2))

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

    def promote(self, version_id: str) -> None:
        """Promotion gate (R5): candidate must beat the incumbent."""
        candidate = self._index["versions"][version_id]
        incumbent_id = self._index["active"]
        if incumbent_id is not None:
            incumbent = self._index["versions"][incumbent_id]
            candidate_score = candidate["metrics"][PRIMARY_METRIC]
            incumbent_score = incumbent["metrics"][PRIMARY_METRIC]
            if candidate_score <= incumbent_score:
                raise PromotionRejected(
                    f"candidate '{version_id}' ({candidate_score}) does not beat "
                    f"incumbent '{incumbent_id}' ({incumbent_score})"
                )
            self._index["history"].append(incumbent_id)
        self._index["active"] = version_id
        self._save()

    def rollback(self) -> str:
        if not self._index["history"]:
            raise RuntimeError("no previous active version to roll back to")
        previous = self._index["history"].pop()
        self._index["active"] = previous
        self._save()
        return previous
