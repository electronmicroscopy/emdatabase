"""Shared test fixtures.

Every test runs against an isolated, empty settings file (in a tmp dir) and with
the legacy ``EM_DATABASE_DATA_DIR`` env var cleared, so the developer's real
settings never affect a test and a test never writes to the real config.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    from emdatabase import config

    monkeypatch.setenv("EM_DATABASE_CONFIG", str(tmp_path / "emdatabase_settings.yaml"))
    # Point the system config at a nonexistent file and clear the shared/data env
    # vars, so the developer's real machine config never leaks into a test.
    monkeypatch.setenv("EM_DATABASE_SYSTEM_CONFIG", str(tmp_path / "system.yaml"))
    monkeypatch.delenv("EM_DATABASE_DATA_DIR", raising=False)
    monkeypatch.delenv("EM_DATABASE_SHARED_DIR", raising=False)
    config.settings.reload()  # re-seed from the isolated (empty) config
    yield
