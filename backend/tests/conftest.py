"""Shared fixtures for integration tests.

Settings/engine are constructed at import time (module-level singletons), so
each test that needs an isolated SQLite database re-imports the whole ``app``
package after setting environment variables — mirroring how the app is
actually configured (env vars read once at process start).
"""
import sys

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as test_client:
        yield test_client
