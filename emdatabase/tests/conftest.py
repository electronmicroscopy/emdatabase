"""Shared test fixtures.

Every test runs against an isolated, empty config directory (in a tmp dir), with
every ``EMDATABASE_*`` environment variable cleared and the first-run notice
already marked shown, so the developer's real configuration never affects a test
and a test never writes to the real one.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    from emdatabase import config

    for name in list(os.environ):
        if name.startswith(config.ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EMDATABASE_CONFIG", str(tmp_path / "config"))
    monkeypatch.setattr(config, "_NOTICE_SHOWN", True)
    config.refresh()
    yield
    config.refresh()
