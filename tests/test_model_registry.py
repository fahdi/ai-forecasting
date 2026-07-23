"""
Tests for the model registry and promotion gate (issue #6, PRD §4.1 R5).

File-based registry: every version recorded with metrics and feature schema;
promotion only when the candidate beats the incumbent on the validation
metric; rollback is one step.
"""

import pytest

from app.models.registry import ModelRegistry, PromotionRejected

PRIMARY_METRIC = "directional_accuracy"


@pytest.fixture
def registry(tmp_path):
    return ModelRegistry(tmp_path / "registry")


def register(reg, version, accuracy):
    return reg.register(
        version_id=version,
        metrics={PRIMARY_METRIC: accuracy, "n_test": 500},
        feature_schema=["log_return_1", "rsi_14"],
        training_window={"start": "2024-07-01", "end": "2026-07-01"},
    )


class TestRegistration:
    def test_register_and_fetch(self, registry):
        register(registry, "v1", 0.55)
        record = registry.get("v1")
        assert record["metrics"][PRIMARY_METRIC] == 0.55
        assert record["feature_schema"] == ["log_return_1", "rsi_14"]
        assert record["created_at"]

    def test_registry_persists_across_instances(self, registry, tmp_path):
        register(registry, "v1", 0.55)
        reopened = ModelRegistry(tmp_path / "registry")
        assert reopened.get("v1")["metrics"][PRIMARY_METRIC] == 0.55

    def test_duplicate_version_rejected(self, registry):
        register(registry, "v1", 0.55)
        with pytest.raises(ValueError, match="exists"):
            register(registry, "v1", 0.60)


class TestPromotion:
    def test_first_model_promotes_unconditionally(self, registry):
        register(registry, "v1", 0.52)
        registry.promote("v1")
        assert registry.active_version() == "v1"

    def test_better_candidate_promotes(self, registry):
        register(registry, "v1", 0.52)
        registry.promote("v1")
        register(registry, "v2", 0.56)
        registry.promote("v2")
        assert registry.active_version() == "v2"

    def test_worse_candidate_rejected(self, registry):
        register(registry, "v1", 0.56)
        registry.promote("v1")
        register(registry, "v2", 0.53)
        with pytest.raises(PromotionRejected, match="0.53"):
            registry.promote("v2")
        assert registry.active_version() == "v1"

    def test_equal_candidate_rejected(self, registry):
        register(registry, "v1", 0.55)
        registry.promote("v1")
        register(registry, "v2", 0.55)
        with pytest.raises(PromotionRejected):
            registry.promote("v2")

    def test_unknown_version_promotion_fails(self, registry):
        with pytest.raises(KeyError):
            registry.promote("ghost")


class TestRollback:
    def test_rollback_restores_previous_active(self, registry):
        register(registry, "v1", 0.52)
        registry.promote("v1")
        register(registry, "v2", 0.56)
        registry.promote("v2")
        registry.rollback()
        assert registry.active_version() == "v1"

    def test_rollback_without_history_fails(self, registry):
        register(registry, "v1", 0.52)
        registry.promote("v1")
        with pytest.raises(RuntimeError, match="[Nn]o previous"):
            registry.rollback()
