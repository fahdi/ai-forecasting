"""
Shared test configuration.

The suite must be hermetic: it may not depend on the docker-compose postgres
(or anything else on the host) being up. DATABASE_URL is pointed at a
throwaway sqlite file BEFORE any app module is imported, because
app.core.database builds its engine at import time.
"""

import asyncio
import os
import tempfile

_TEST_DB_DIR = tempfile.mkdtemp(prefix="aif-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/test.db"

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Create the ORM tables once for the whole session (lifespan does this
    in production, but plain TestClient(app) never runs the lifespan).

    In the .venv-freqtrade environment the app's dependencies are absent —
    the strategy tests there don't touch the database, so skip quietly.
    """
    try:
        from app.core.database import init_db
    except ModuleNotFoundError:
        yield
        return

    asyncio.run(init_db())
    yield
