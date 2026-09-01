"""Tests for the dask-style config loader.

The autouse fixture in conftest.py points ``EMDATABASE_CONFIG`` at an empty tmp
directory and clears the ``EMDATABASE_*`` environment, so these exercise the
layering in isolation and never touch the real config.
"""

from pathlib import Path

import pooch
import pytest
import yaml

import emdatabase
from emdatabase import config


def _write_yaml(tmp_path: Path, **values) -> Path:
    directory = tmp_path / "config"
    directory.mkdir(exist_ok=True)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return path


def test_shipped_defaults():
    assert config.get("data_dir") is None
    assert config.get("stores") == {}


def test_yaml_file_is_read(tmp_path):
    _write_yaml(tmp_path, data_dir=str(tmp_path / "from-yaml"))
    config.refresh()
    assert emdatabase.get_data_dir() == tmp_path / "from-yaml"


def test_env_var_overrides_the_yaml_file(tmp_path, monkeypatch):
    _write_yaml(tmp_path, data_dir=str(tmp_path / "from-yaml"))
    monkeypatch.setenv("EMDATABASE_DATA_DIR", str(tmp_path / "from-env"))
    config.refresh()
    assert emdatabase.get_data_dir() == tmp_path / "from-env"


def test_env_var_nests_on_a_double_underscore():
    collected = config.collect_env(
        env={
            "EMDATABASE_DATA_DIR": "/scratch/data",
            "EMDATABASE_STORES__GROUP": "/group/example_data",
            "EMDATABASE_CONFIG": "/etc/nowhere",  # the config dir, not a key
            "PATH": "/usr/bin",
        }
    )
    assert collected == {"data_dir": "/scratch/data", "stores": {"group": "/group/example_data"}}


def test_set_wins_over_the_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("EMDATABASE_DATA_DIR", str(tmp_path / "from-env"))
    config.refresh()
    config.set({"data_dir": str(tmp_path / "from-set")})
    assert emdatabase.get_data_dir() == tmp_path / "from-set"


def test_set_as_a_context_manager_restores(tmp_path):
    before = config.get("data_dir")
    with config.set({"data_dir": str(tmp_path / "temporary")}):
        assert emdatabase.get_data_dir() == tmp_path / "temporary"
    assert config.get("data_dir") == before


def test_set_data_dir_is_a_thin_wrapper(tmp_path):
    emdatabase.set_data_dir(tmp_path / "chosen")
    assert config.get("data_dir") == str(tmp_path / "chosen")
    assert emdatabase.get_data_dir() == tmp_path / "chosen"


def test_an_unknown_key_warns_and_is_still_set():
    with pytest.warns(UserWarning, match='Unknown configuration key "quality"'):
        config.set({"quality": "high"})
    assert config.get("quality") == "high"


def test_a_nested_key_under_a_known_one_does_not_warn(recwarn):
    config.set({"stores": {"group": "/group/example_data"}})
    config.set({"stores.other": "/other"})
    assert not [w for w in recwarn if "Unknown configuration" in str(w.message)]
    assert config.stores()["other"] == Path("/other")


def test_write_round_trips(tmp_path):
    config.set({"data_dir": str(tmp_path / "written"), "stores": {"group": "/group"}})
    path = tmp_path / "config" / "config.yaml"
    config.write()
    assert path.exists()
    config.refresh()  # the file is in the isolated config dir, so it is read back
    assert config.get("data_dir") == str(tmp_path / "written")
    assert config.get("stores") == {"group": "/group"}


def test_data_dir_defaults_to_the_pooch_cache():
    assert config.data_dir() == Path(pooch.os_cache("emdatabase"))


def test_paths_expand_a_tilde():
    config.set({"data_dir": "~/emdatabase-elsewhere", "stores": {"home": "~/shared"}})
    assert config.data_dir() == Path.home() / "emdatabase-elsewhere"
    assert config.stores() == {"home": Path.home() / "shared"}


def test_first_run_notice_is_logged_once(caplog, monkeypatch, tmp_path):
    import logging

    monkeypatch.setattr(config, "_NOTICE_SHOWN", False)
    with caplog.at_level(logging.INFO, logger="emdatabase"):
        config.first_run_notice(tmp_path / "cache")
        config.first_run_notice(tmp_path / "cache")
    assert len(caplog.records) == 1
    assert str(tmp_path / "cache") in caplog.records[0].getMessage()
    assert "EMDATABASE_DATA_DIR" in caplog.records[0].getMessage()
