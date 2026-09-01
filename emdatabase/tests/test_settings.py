"""Tests for the matplotlib-style settings object and the YAML config file.

The autouse fixture in conftest.py isolates each test to an empty settings file
and clears the legacy env var, so these exercise the mechanism in isolation.
"""

from pathlib import Path

import emdatabase
from emdatabase import config


def test_defaults_when_nothing_configured():
    assert emdatabase.get_data_dir() == config._default_data_dir()
    assert emdatabase.settings["data_dir"] == str(config._default_data_dir())


def test_live_object_is_immediate_like_rcparams(tmp_path):
    emdatabase.settings["data_dir"] = str(tmp_path / "live")
    assert emdatabase.get_data_dir() == tmp_path / "live"  # no save needed
    assert not config.config_path().exists()  # not persisted


def test_set_data_dir_persists_across_sessions(tmp_path):
    target = str(tmp_path / "data")
    emdatabase.set_data_dir(target)  # persist=True by default
    assert emdatabase.get_data_dir() == Path(target)
    assert config._read_file()["data_dir"] == target
    config.settings.reload()  # a fresh "session"
    assert emdatabase.get_data_dir() == Path(target)


def test_set_data_dir_session_only_is_not_persisted(tmp_path):
    target = str(tmp_path / "x")
    emdatabase.set_data_dir(target, persist=False)
    assert emdatabase.get_data_dir() == Path(target)
    assert not config.config_path().exists()
    config.settings.reload()
    assert emdatabase.get_data_dir() == config._default_data_dir()  # forgotten


def test_reset_clears_the_saved_choice(tmp_path):
    emdatabase.set_data_dir(str(tmp_path))
    emdatabase.reset_data_dir()
    assert emdatabase.get_data_dir() == config._default_data_dir()
    config.settings.reload()
    assert emdatabase.get_data_dir() == config._default_data_dir()  # stays reset


def test_generic_setting_roundtrips():
    emdatabase.set_setting("quality", "high")
    assert emdatabase.get_setting("quality") == "high"
    config.settings.reload()
    assert emdatabase.get_setting("quality") == "high"  # persisted


def test_saving_other_settings_keeps_the_default_dynamic():
    """Persisting an unrelated setting must NOT freeze the default data_dir into
    the file - otherwise the default would stop being obeyed."""
    emdatabase.set_setting("quality", "high")  # triggers a save()
    stored = config._read_file()
    assert stored == {"quality": "high"}  # data_dir default not written
    assert emdatabase.get_data_dir() == config._default_data_dir()


def test_legacy_env_var_still_seeds(tmp_path, monkeypatch):
    monkeypatch.setenv("EM_DATABASE_DATA_DIR", str(tmp_path / "fromenv"))
    config.settings.reload()  # a fresh "import" with the env var set
    assert emdatabase.get_data_dir() == tmp_path / "fromenv"
