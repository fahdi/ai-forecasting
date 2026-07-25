"""
Coverage tests for app/api/v1/endpoints/data.py

DataService is patched at the endpoint module; the async get_db dependency is
overridden with a mock session (the data endpoints declare it but never touch
it), so the suite is hermetic. TestClient is used without a context manager so
the DB lifespan never runs.

NOTE on known bugs (tested as current behavior, not fixed here):
- Every handler wraps its body in `except Exception` and re-raises as 500,
  so intentional HTTPException(400/404)s surface as 500 with the original
  status baked into the detail string (e.g. "404: No data found for symbol").
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.core.config import settings

client = TestClient(app)

DS_PATCH = "app.api.v1.endpoints.data.DataService"


@pytest.fixture(autouse=True)
def mock_db():
    """The data endpoints take a db session but never use it; still override
    the dependency so nothing ever reaches a real engine."""

    async def _get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"close": [100.0, 101.5], "volume": [1000, 1200]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )


class TestUpload:
    def _post(self, filename="prices.csv", symbol="aapl"):
        return client.post(
            "/api/v1/data/upload",
            files={"file": (filename, b"date,close\n2026-01-01,100\n", "text/csv")},
            data={"symbol": symbol},
        )

    def test_upload_success(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.process_uploaded_file = AsyncMock(
                return_value={"file_id": "f-1", "rows_processed": 42}
            )
            response = self._post()
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["rows_processed"] == 42
        assert body["status"] == "success"
        assert body["file_id"] == "f-1"
        ds.return_value.process_uploaded_file.assert_awaited_once()

    def test_upload_rejects_unknown_extension(self):
        # BUG(flagged): intended 400 is swallowed by the blanket except and
        # re-raised as 500 with the original status in the detail text.
        response = self._post(filename="prices.txt")
        assert response.status_code == 500
        assert "File type not supported" in response.json()["detail"]

    def test_upload_rejects_oversized_file(self, monkeypatch):
        monkeypatch.setattr(settings, "MAX_FILE_SIZE", 1)
        response = self._post()
        assert response.status_code == 500  # BUG(flagged): intended 400
        assert "File too large" in response.json()["detail"]

    def test_upload_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.process_uploaded_file = AsyncMock(
                side_effect=RuntimeError("parse blew up")
            )
            response = self._post()
        assert response.status_code == 500
        assert "parse blew up" in response.json()["detail"]


class TestSymbols:
    def test_symbols_success(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.get_available_symbols = AsyncMock(
                return_value=["AAPL", "MSFT"]
            )
            response = client.get("/api/v1/data/symbols?source=yahoo")
        assert response.status_code == 200
        body = response.json()
        assert body["symbols"] == ["AAPL", "MSFT"]
        assert body["total_count"] == 2
        ds.return_value.get_available_symbols.assert_awaited_once_with(source="yahoo")

    def test_symbols_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.get_available_symbols = AsyncMock(
                side_effect=RuntimeError("listing failed")
            )
            response = client.get("/api/v1/data/symbols")
        assert response.status_code == 500
        assert "listing failed" in response.json()["detail"]


class TestDataInfo:
    def test_info_success(self):
        info = {
            "symbol": "AAPL",
            "source": "yahoo",
            "last_updated": datetime(2026, 1, 2, 12, 0, 0),
            "data_points": 500,
            "date_range": {"start": "2024-01-01", "end": "2026-01-02"},
            "columns": ["open", "high", "low", "close", "volume"],
        }
        with patch(DS_PATCH) as ds:
            ds.return_value.get_data_info = AsyncMock(return_value=info)
            response = client.get("/api/v1/data/info/aapl")
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["data_points"] == 500
        assert body["date_range"]["start"] == "2024-01-01"
        ds.return_value.get_data_info.assert_awaited_once_with("AAPL")

    def test_info_not_found(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.get_data_info = AsyncMock(return_value=None)
            response = client.get("/api/v1/data/info/none")
        # BUG(flagged): intended 404 surfaces as 500.
        assert response.status_code == 500
        assert "No data found for symbol" in response.json()["detail"]

    def test_info_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.get_data_info = AsyncMock(side_effect=RuntimeError("boom"))
            response = client.get("/api/v1/data/info/aapl")
        assert response.status_code == 500


class TestDownload:
    @pytest.fixture(autouse=True)
    def temp_cwd(self, tmp_path, monkeypatch):
        # The endpoint writes to the relative path "temp/<file>"; run in an
        # isolated cwd so nothing lands in the repo.
        monkeypatch.chdir(tmp_path)
        (tmp_path / "temp").mkdir()
        yield

    def _get(self, fmt=None, df=None):
        url = "/api/v1/data/download/aapl"
        if fmt is not None:
            url += f"?format={fmt}"
        with patch(DS_PATCH) as ds:
            ds.return_value.get_historical_data = AsyncMock(
                return_value=sample_df() if df is None else df
            )
            return client.get(url)

    def test_download_csv_default(self):
        response = self._get()  # format defaults to csv
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "close" in response.text

    def test_download_json(self):
        response = self._get(fmt="json")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()[0]["close"] == 100.0

    def test_download_parquet(self):
        # No parquet engine (pyarrow/fastparquet) is installed in this env, so
        # use a DataFrame stand-in whose to_parquet writes a placeholder file;
        # this exercises the endpoint's parquet branch and FileResponse.
        fake = MagicMock()
        fake.empty = False
        fake.to_parquet.side_effect = (
            lambda path, index=True: Path(path).write_bytes(b"PAR1fake")
        )
        response = self._get(fmt="parquet", df=fake)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.content == b"PAR1fake"

    def test_download_no_data(self):
        response = self._get(df=pd.DataFrame())
        # BUG(flagged): intended 404 surfaces as 500.
        assert response.status_code == 500
        assert "No data found for symbol" in response.json()["detail"]

    def test_download_unsupported_format(self):
        response = self._get(fmt="xml")
        # BUG(flagged): intended 400 surfaces as 500.
        assert response.status_code == 500
        assert "Unsupported format" in response.json()["detail"]

    def test_download_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.get_historical_data = AsyncMock(
                side_effect=RuntimeError("fetch failed")
            )
            response = client.get("/api/v1/data/download/aapl")
        assert response.status_code == 500
        assert "fetch failed" in response.json()["detail"]


class TestRefresh:
    def test_refresh_success(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.refresh_data = AsyncMock(
                return_value={"new_points": 5, "last_updated": "2026-01-02T00:00:00"}
            )
            response = client.post("/api/v1/data/refresh/aapl?source=alpha_vantage")
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["source"] == "alpha_vantage"
        assert body["new_data_points"] == 5
        assert body["status"] == "success"
        ds.return_value.refresh_data.assert_awaited_once_with(
            symbol="AAPL", source="alpha_vantage"
        )

    def test_refresh_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.refresh_data = AsyncMock(
                side_effect=RuntimeError("upstream down")
            )
            response = client.post("/api/v1/data/refresh/aapl")
        assert response.status_code == 500
        assert "upstream down" in response.json()["detail"]


class TestDelete:
    def test_delete_success(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.delete_data = AsyncMock(return_value=True)
            response = client.delete("/api/v1/data/aapl")
        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"]

    def test_delete_not_found(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.delete_data = AsyncMock(return_value=False)
            response = client.delete("/api/v1/data/none")
        # BUG(flagged): intended 404 surfaces as 500.
        assert response.status_code == 500
        assert "No data found for symbol" in response.json()["detail"]

    def test_delete_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.delete_data = AsyncMock(side_effect=RuntimeError("io"))
            response = client.delete("/api/v1/data/aapl")
        assert response.status_code == 500


class TestSourcesAndStats:
    def test_sources_lists_all_providers(self):
        response = client.get("/api/v1/data/sources")
        assert response.status_code == 200
        sources = {s["name"]: s for s in response.json()["sources"]}
        assert set(sources) == {"yahoo", "alpha_vantage", "custom"}
        assert sources["yahoo"]["enabled"] == settings.YAHOO_FINANCE_ENABLED
        assert sources["alpha_vantage"]["enabled"] == settings.ALPHA_VANTAGE_ENABLED
        assert sources["custom"]["enabled"] is True

    def test_stats_success(self):
        stats = {
            "total_symbols": 3,
            "total_data_points": 1500,
            "data_sources": {"yahoo": 2, "custom": 1},
            "last_updated": "2026-01-02T00:00:00",
            "storage_size": 12345,
        }
        with patch(DS_PATCH) as ds:
            ds.return_value.get_data_stats = AsyncMock(return_value=stats)
            response = client.get("/api/v1/data/stats")
        assert response.status_code == 200
        body = response.json()
        assert body["total_symbols"] == 3
        assert body["total_data_points"] == 1500
        assert body["storage_size"] == 12345

    def test_stats_service_error_returns_500(self):
        with patch(DS_PATCH) as ds:
            ds.return_value.get_data_stats = AsyncMock(
                side_effect=RuntimeError("stats broke")
            )
            response = client.get("/api/v1/data/stats")
        assert response.status_code == 500
        assert "stats broke" in response.json()["detail"]
