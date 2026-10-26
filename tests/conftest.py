from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import AppSettings
from app.data.loader import load_dataset
from app.main import create_app
from app.services.decision_log import DecisionLog
from app.services.lighty import Lighty


@pytest.fixture(scope="session")
def settings(tmp_path_factory) -> AppSettings:
    rt = tmp_path_factory.mktemp("runtime")
    return AppSettings(RUNTIME_DIR=rt, AI_API_KEY=None, AI_BASE_URL=None, AI_MODEL=None, ADMIN_TOKEN=None)


@pytest.fixture(scope="session")
def dataset(settings):
    return load_dataset(settings.workbook_path, settings.event_stream_path, settings.snapshot_at)


@pytest.fixture(scope="session")
def lighty(settings, dataset) -> Lighty:
    return Lighty(settings, dataset=dataset)


@pytest.fixture(scope="session")
def portfolio(lighty):
    return lighty.portfolio()


@pytest.fixture()
def fresh_lighty(settings, dataset, tmp_path) -> Lighty:
    """Lighty with its own SQLite file, for tests that change settings or approvals."""
    return Lighty(settings, dataset=dataset, decision_log=DecisionLog(tmp_path / "g.sqlite3"))


@pytest.fixture()
def client(settings, fresh_lighty):
    with TestClient(create_app(settings, fresh_lighty)) as c:
        yield c


@pytest.fixture(scope="session")
def copilot_settings(settings) -> AppSettings:
    """Dev auth (X-Employee-Id / X-Employee-Role headers) and no startup warm-up, for fast copilot API tests."""
    return settings.model_copy(update={"allow_dev_auth": True, "warm_portfolio_on_startup": False})


@pytest.fixture()
def copilot_client(copilot_settings, dataset, tmp_path):
    lt = Lighty(copilot_settings, dataset=dataset, decision_log=DecisionLog(tmp_path / "c.sqlite3"))
    with TestClient(create_app(copilot_settings, lt)) as c:
        yield c
