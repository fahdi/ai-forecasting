"""
Coverage tests for app/api/v1/endpoints/models.py

Covers /train, /performance, /list, delete, info and the background training
task. The /health route and get_health_engine are intentionally NOT covered
here — tests/test_model_health.py owns them.

NOTE on known bugs (tested as current behavior, not fixed here):
- delete/info wrap intentional HTTPException(404)s in a blanket
  `except Exception` and re-raise them as 500.
- process_model_training calls save_model_performance(metadata=...) but the
  real function's parameter is named model_metadata, so the un-mocked call
  would always TypeError; the test patches save_model_performance and only
  asserts the call happens.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
import app.api.v1.endpoints.models as models_module
from app.api.v1.endpoints.models import get_health_engine, process_model_training

client = TestClient(app)

NS = "app.api.v1.endpoints.models"


@pytest.fixture
def db_override():
    def _install(session):
        async def _get_db():
            yield session

        app.dependency_overrides[get_db] = _get_db
        return session

    yield _install
    app.dependency_overrides.pop(get_db, None)


def make_session_factory() -> MagicMock:
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session_cm)


class TestGetHealthEngine:
    """Covers the real get_health_engine factory and the engine-None branch
    of GET /models/health. tests/test_model_health.py always overrides this
    dependency, so the factory body itself is only exercised here; the
    with-engine endpoint contract stays owned by test_model_health.py."""

    def test_builds_and_caches_engine_from_database_url(self, monkeypatch):
        # conftest points DATABASE_URL at a throwaway sqlite file.
        monkeypatch.setattr(models_module, "_HEALTH_ENGINE", "unset")
        engine = get_health_engine()
        try:
            assert engine is not None
            # Second call returns the cached engine, not a new one.
            assert get_health_engine() is engine
            # The engine is usable by the endpoint end-to-end: with no
            # predictions recorded the summary is empty.
            app.dependency_overrides[get_health_engine] = lambda: engine
            try:
                response = client.get("/api/v1/models/health")
            finally:
                app.dependency_overrides.pop(get_health_engine, None)
            assert response.status_code == 200
            assert response.json() == {"pairs": []}
        finally:
            engine.dispose()

    def test_no_database_url_yields_none(self, monkeypatch):
        monkeypatch.setattr(models_module, "_HEALTH_ENGINE", "unset")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert get_health_engine() is None
        assert get_health_engine() is None  # cached None, no re-probe

    def test_health_endpoint_without_engine_returns_empty(self):
        app.dependency_overrides[get_health_engine] = lambda: None
        try:
            response = client.get("/api/v1/models/health")
        finally:
            app.dependency_overrides.pop(get_health_engine, None)
        assert response.status_code == 200
        assert response.json() == {"pairs": []}


class TestTrain:
    def test_train_success(self, db_override):
        db_override(MagicMock())
        with patch(f"{NS}.process_model_training", new=AsyncMock()) as bg_task:
            response = client.post(
                "/api/v1/models/train",
                json={"symbol": "aapl", "model_type": "xgboost",
                      "test_size": 0.3, "retrain_existing": True},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert "aapl" in body["message"]
        assert body["model_type"] == "xgboost"
        assert "job_id" in body and "estimated_completion" in body
        # TestClient executes background tasks before returning the response.
        assert bg_task.await_count == 1
        kwargs = bg_task.await_args.kwargs
        assert kwargs["symbol"] == "AAPL"
        assert kwargs["test_size"] == 0.3
        assert kwargs["retrain_existing"] is True

    def test_train_test_size_validation(self, db_override):
        db_override(MagicMock())
        response = client.post(
            "/api/v1/models/train", json={"symbol": "AAPL", "test_size": 0.9}
        )
        assert response.status_code == 422

    def test_train_internal_error_returns_500(self, db_override):
        db_override(MagicMock())
        with patch(f"{NS}.uuid") as uuid_mock:
            uuid_mock.uuid4.side_effect = RuntimeError("no entropy")
            response = client.post(
                "/api/v1/models/train", json={"symbol": "AAPL"}
            )
        assert response.status_code == 500
        assert "no entropy" in response.json()["detail"]


class TestPerformance:
    @staticmethod
    def _session_returning(rows):
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        return session

    def test_performance_with_filters(self, db_override):
        row = SimpleNamespace(
            model_type="xgboost", symbol="AAPL", version="v1",
            mape=1.5, mae=0.7, rmse=1.1, directional_accuracy=0.61,
            training_date=datetime(2026, 1, 1),
            test_start_date=datetime(2025, 6, 1),
            test_end_date=datetime(2025, 12, 31),
        )
        session = self._session_returning([row])
        db_override(session)
        response = client.get(
            "/api/v1/models/performance?symbol=aapl&model_type=xgboost&limit=5"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 1
        perf = body["performances"][0]
        assert perf["symbol"] == "AAPL"
        assert perf["model_type"] == "xgboost"
        assert perf["mape"] == 1.5
        assert perf["directional_accuracy"] == 0.61
        session.execute.assert_awaited_once()

    def test_performance_empty(self, db_override):
        db_override(self._session_returning([]))
        response = client.get("/api/v1/models/performance")
        assert response.status_code == 200
        body = response.json()
        assert body == {"performances": [], "total_count": 0}

    def test_performance_db_error_returns_500(self, db_override):
        session = MagicMock()
        session.execute = AsyncMock(side_effect=RuntimeError("db down"))
        db_override(session)
        response = client.get("/api/v1/models/performance")
        assert response.status_code == 500
        assert "db down" in response.json()["detail"]


class TestListModels:
    def test_list_success(self):
        models = [{
            "model_type": "xgboost", "symbol": "AAPL", "version": "v2",
            "last_trained": datetime(2026, 1, 1),
            "performance": {"mape": 1.2}, "file_size": 2048,
        }]
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.list_models = AsyncMock(return_value=models)
            response = client.get("/api/v1/models/list?symbol=AAPL")
        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 1
        entry = body["models"][0]
        assert entry["version"] == "v2"
        assert entry["performance"] == {"mape": 1.2}
        assert entry["file_size"] == 2048
        ms.return_value.list_models.assert_awaited_once_with(
            symbol="AAPL", model_type=None
        )

    def test_list_service_error_returns_500(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.list_models = AsyncMock(
                side_effect=RuntimeError("scan failed")
            )
            response = client.get("/api/v1/models/list")
        assert response.status_code == 500
        assert "scan failed" in response.json()["detail"]


class TestDeleteModel:
    def test_delete_success(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.delete_model = AsyncMock(return_value=True)
            response = client.delete("/api/v1/models/xgboost/aapl?version=v1")
        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"]
        ms.return_value.delete_model.assert_awaited_once_with(
            model_type="xgboost", symbol="AAPL", version="v1"
        )

    def test_delete_not_found(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.delete_model = AsyncMock(return_value=False)
            response = client.delete("/api/v1/models/xgboost/none")
        # BUG(flagged): intended 404 surfaces as 500.
        assert response.status_code == 500
        assert "Model not found" in response.json()["detail"]

    def test_delete_service_error_returns_500(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.delete_model = AsyncMock(
                side_effect=RuntimeError("fs error")
            )
            response = client.delete("/api/v1/models/xgboost/aapl")
        assert response.status_code == 500


class TestModelInfo:
    def test_info_success(self):
        info = {"model_type": "xgboost", "symbol": "AAPL", "version": "v1",
                "features": ["close_lag_1"]}
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.get_model_info = AsyncMock(return_value=info)
            response = client.get("/api/v1/models/xgboost/aapl/info")
        assert response.status_code == 200
        assert response.json() == info
        ms.return_value.get_model_info.assert_awaited_once_with(
            model_type="xgboost", symbol="AAPL", version=None
        )

    def test_info_not_found(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.get_model_info = AsyncMock(return_value=None)
            response = client.get("/api/v1/models/xgboost/none/info")
        # BUG(flagged): intended 404 surfaces as 500.
        assert response.status_code == 500
        assert "Model not found" in response.json()["detail"]

    def test_info_service_error_returns_500(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.get_model_info = AsyncMock(
                side_effect=RuntimeError("read error")
            )
            response = client.get("/api/v1/models/xgboost/aapl/info")
        assert response.status_code == 500


class TestProcessModelTraining:
    @pytest.mark.asyncio
    async def test_success_saves_performance(self):
        training_result = {
            "version": "v3", "mape": 1.0, "mae": 0.5, "rmse": 0.9,
            "directional_accuracy": 0.6, "metadata": {"features": 12},
            "performance": {"mape": 1.0},
        }
        with patch(f"{NS}.ModelService") as ms, \
             patch("app.core.database.AsyncSessionLocal", make_session_factory()), \
             patch(f"{NS}.save_model_performance", new=AsyncMock()) as save_perf:
            ms.return_value.train_model = AsyncMock(return_value=training_result)
            await process_model_training(
                job_id="t-1", symbol="AAPL", model_type="xgboost",
                test_size=0.2, retrain_existing=False,
            )
        ms.return_value.train_model.assert_awaited_once_with(
            symbol="AAPL", model_type="xgboost", test_size=0.2,
            retrain_existing=False,
        )
        assert save_perf.await_count == 1
        kwargs = save_perf.await_args.kwargs
        assert kwargs["version"] == "v3"
        assert kwargs["mape"] == 1.0
        assert kwargs["directional_accuracy"] == 0.6

    @pytest.mark.asyncio
    async def test_training_failure_reraises(self):
        with patch(f"{NS}.ModelService") as ms:
            ms.return_value.train_model = AsyncMock(
                side_effect=RuntimeError("diverged")
            )
            with pytest.raises(RuntimeError, match="diverged"):
                await process_model_training(
                    job_id="t-2", symbol="AAPL", model_type="xgboost",
                    test_size=0.2, retrain_existing=False,
                )
