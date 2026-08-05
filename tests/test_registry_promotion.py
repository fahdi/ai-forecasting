"""
Registry durability and decision-backed promotion (issue #21, PRD R5).

Two live problems.

(1) ModelRegistry._save() was a bare write_text: truncate, then write. The API
reads that same registry.json through ensemble_predictor.load_active(), and
signal_service.get_predictor() swallows any failure into None, silently
downgrading the whole system to the baseline EMA momentum rule. A crash or a
concurrent read mid-write could therefore cost you the actual model with no
signal that it happened. Saves now go through a temp file and os.replace, the
same discipline scripts/prod_backup.py already uses.

(2) promote() decided on two stored metrics from unrelated runs. It now
accepts an authoritative PromotionDecision (app/models/promotion.py) and
records the evidence, so registry.json alone answers "why is this version
active". Losing candidates are kept under `rejected` instead of vanishing.

tests/test_model_registry.py is deliberately untouched: passing no decision
preserves today's behaviour exactly, and those 10 tests prove it.
"""

import json

import pytest

from app.models.promotion import PromotionDecision
from app.models.registry import ModelRegistry, PromotionRejected

PRIMARY_METRIC = "directional_accuracy"
SCHEMA = ["log_return_1", "rsi_14"]


@pytest.fixture
def registry(tmp_path):
    return ModelRegistry(tmp_path / "registry")


def register(reg, version, accuracy=0.55, schema=None):
    return reg.register(
        version_id=version,
        metrics={PRIMARY_METRIC: accuracy, "n_test": 500},
        feature_schema=schema or SCHEMA,
        training_window={"start": "2024-01-01", "end": "2026-01-01"},
    )


def approving(**overrides):
    base = dict(
        promote=True,
        status="promoted",
        reason="candidate 0.6000 beats incumbent 0.5000 by 0.1000",
        evidence={"candidate_accuracy": 0.6, "incumbent_accuracy": 0.5, "n": 2000},
    )
    base.update(overrides)
    return PromotionDecision(**base)


def rejecting(**overrides):
    base = dict(
        promote=False,
        status="rejected_no_margin",
        reason="difference of 0.0003 does not clear the threshold of 0.0052",
        evidence={"candidate_accuracy": 0.5241, "incumbent_accuracy": 0.5238, "n": 9328},
    )
    base.update(overrides)
    return PromotionDecision(**base)


class TestAtomicSave:
    def test_save_is_atomic_under_a_failed_replace(self, registry, monkeypatch, tmp_path):
        """An interrupted save must leave the previous index fully parseable."""
        register(registry, "v1")
        registry.promote("v1")
        before = json.loads((registry.root / "registry.json").read_text())

        import os as os_module

        monkeypatch.setattr(os_module, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        with pytest.raises(OSError):
            register(registry, "v2")

        after = json.loads((registry.root / "registry.json").read_text())
        assert after == before

    def test_no_temp_files_are_left_behind_on_success(self, registry):
        register(registry, "v1")
        registry.promote("v1")
        leftovers = [p.name for p in registry.root.iterdir() if p.name != "registry.json" and p.is_file()]
        assert leftovers == []

    def test_every_read_during_a_rewrite_parses(self, registry):
        """The reader is the API; a partial parse downgrades it to the baseline."""
        register(registry, "v1")
        registry.promote("v1")
        index_path = registry.root / "registry.json"
        for i in range(2, 12):
            register(registry, f"v{i}")
            json.loads(index_path.read_text())


class TestDecisionBackedPromotion:
    def test_promote_with_decision_persists_evidence(self, registry):
        """registry.json alone must answer 'why is this version active'."""
        register(registry, "v1")
        registry.promote("v1")
        register(registry, "v2", accuracy=0.60)

        decision = approving()
        registry.promote("v2", decision=decision)

        record = registry.get("v2")
        assert registry.active_version() == "v2"
        assert record["promotion_evidence"]["evidence"]["n"] == 2000
        assert record["promotion_evidence"]["reason"] == decision.reason
        assert record["promotion_evidence"]["status"] == "promoted"

    def test_promote_with_rejecting_decision_raises_and_leaves_active_unchanged(self, registry):
        register(registry, "v1")
        registry.promote("v1")
        register(registry, "v2", accuracy=0.99)

        with pytest.raises(PromotionRejected) as exc:
            registry.promote("v2", decision=rejecting())

        assert registry.active_version() == "v1"
        assert "does not clear the threshold" in str(exc.value)

    def test_decision_overrides_the_stored_metric_in_both_directions(self, registry):
        """The stored metrics are from unrelated runs; the decision wins."""
        register(registry, "v1", accuracy=0.90)
        registry.promote("v1")

        # Worse stored metric, winning decision -> promotes.
        register(registry, "v2", accuracy=0.10)
        registry.promote("v2", decision=approving())
        assert registry.active_version() == "v2"

        # Better stored metric, losing decision -> does not.
        register(registry, "v3", accuracy=0.99)
        with pytest.raises(PromotionRejected):
            registry.promote("v3", decision=rejecting())
        assert registry.active_version() == "v2"

    def test_promotion_still_records_rollback_history(self, registry):
        register(registry, "v1")
        registry.promote("v1")
        register(registry, "v2")
        registry.promote("v2", decision=approving())
        assert registry.rollback() == "v1"


class TestRejectionRecord:
    def test_record_rejection_keeps_the_loser_on_the_record(self, registry):
        register(registry, "v1")
        registry.promote("v1")
        register(registry, "v2", accuracy=0.5241)

        decision = rejecting()
        registry.record_rejection("v2", decision)

        index = json.loads((registry.root / "registry.json").read_text())
        entries = index["rejected"]
        assert len(entries) == 1
        assert entries[0]["version_id"] == "v2"
        assert entries[0]["status"] == "rejected_no_margin"
        assert entries[0]["evidence"]["n"] == 9328
        assert registry.active_version() == "v1"

    def test_rejections_accumulate_rather_than_overwrite(self, registry):
        register(registry, "v1")
        registry.promote("v1")
        for i in (2, 3, 4):
            register(registry, f"v{i}")
            registry.record_rejection(f"v{i}", rejecting())
        index = json.loads((registry.root / "registry.json").read_text())
        assert [e["version_id"] for e in index["rejected"]] == ["v2", "v3", "v4"]

    def test_rejection_entries_are_timestamped(self, registry):
        register(registry, "v1")
        registry.record_rejection("v1", rejecting())
        index = json.loads((registry.root / "registry.json").read_text())
        assert index["rejected"][0]["rejected_at"]


class TestPrune:
    def test_prune_keeps_active_and_history(self, registry):
        for i in range(1, 6):
            register(registry, f"v{i}")
        registry.promote("v1")
        registry.promote("v3", decision=approving())
        registry.promote("v5", decision=approving())
        # active=v5, history=[v1, v3]

        removed = registry.prune(keep=0)

        assert set(removed) == {"v2", "v4"}
        remaining = set(json.loads((registry.root / "registry.json").read_text())["versions"])
        assert remaining == {"v1", "v3", "v5"}

    def test_prune_never_removes_the_active_version(self, registry):
        for i in range(1, 4):
            register(registry, f"v{i}")
        registry.promote("v2")

        registry.prune(keep=0)

        assert registry.active_version() == "v2"
        assert "v2" in json.loads((registry.root / "registry.json").read_text())["versions"]

    def test_prune_keeps_the_n_most_recent_beyond_the_protected_set(self, registry):
        for i in range(1, 6):
            register(registry, f"v{i}")
        registry.promote("v1")

        registry.prune(keep=2)

        remaining = set(json.loads((registry.root / "registry.json").read_text())["versions"])
        assert "v1" in remaining
        assert {"v4", "v5"} <= remaining

    def test_prune_leaves_the_registry_loadable(self, registry):
        for i in range(1, 5):
            register(registry, f"v{i}")
        registry.promote("v2")
        registry.prune(keep=0)

        reloaded = ModelRegistry(registry.root)
        assert reloaded.active_version() == "v2"
        assert reloaded.get("v2")["version_id"] == "v2"

    def test_prune_on_an_empty_registry_is_a_no_op(self, registry):
        assert registry.prune(keep=3) == []
