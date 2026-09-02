"""Tests for the dask-style config loader.

The autouse fixture in conftest.py points ``EMDATABASE_CONFIG`` at an empty tmp
directory and clears the ``EMDATABASE_*`` environment, so these exercise the
layering in isolation and never touch the real config.
"""

import warnings
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


# ---------------------------------------------------------------------------
# Adding and removing locations
# ---------------------------------------------------------------------------


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_add_location_names_a_store_after_its_directory(tmp_path):
    shared = _dir(tmp_path, "example_data")
    assert config.add_location(shared) == shared
    assert config.stores() == {"example_data": shared}


def test_add_location_takes_an_explicit_name(tmp_path):
    shared = _dir(tmp_path, "example_data")
    config.add_location(shared, name="group")
    assert config.stores() == {"group": shared}


def test_add_location_appends_in_search_order(tmp_path):
    first = _dir(tmp_path, "first")
    second = _dir(tmp_path, "second")
    config.add_location(first)
    config.add_location(second)
    assert list(config.stores()) == ["first", "second"]


def test_add_location_with_a_duplicate_default_name_raises(tmp_path):
    config.add_location(_dir(tmp_path / "a", "example_data"))
    with pytest.raises(ValueError, match="Pass name="):
        config.add_location(_dir(tmp_path / "b", "example_data"))


def test_add_location_repoints_an_explicitly_named_store(tmp_path):
    config.add_location(_dir(tmp_path, "one"), name="group")
    config.add_location(_dir(tmp_path, "two"), name="group")
    assert config.stores() == {"group": tmp_path / "two"}


def test_adding_the_same_store_twice_is_a_no_op(tmp_path):
    shared = _dir(tmp_path, "example_data")
    config.add_location(shared)
    config.add_location(shared)
    assert config.stores() == {"example_data": shared}


def test_add_location_personal_sets_the_data_dir(tmp_path):
    personal = _dir(tmp_path, "downloads")
    assert config.add_location(personal, "personal") == personal
    assert config.data_dir() == personal
    assert config.stores() == {}


def test_add_location_expands_a_tilde():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the path almost certainly does not exist
        returned = config.add_location("~/shared-elsewhere", persist=False)
    assert returned == Path.home() / "shared-elsewhere"
    assert config.get("stores") == {"shared-elsewhere": str(Path.home() / "shared-elsewhere")}


def test_add_location_warns_about_a_path_that_does_not_exist(tmp_path):
    missing = tmp_path / "not-mounted-yet"
    with pytest.warns(UserWarning, match="does not exist"):
        config.add_location(missing)
    assert config.stores() == {"not-mounted-yet": missing}


def test_add_location_rejects_an_unknown_kind(tmp_path):
    with pytest.raises(ValueError, match='kind must be "shared" or "personal"'):
        config.add_location(_dir(tmp_path, "example_data"), "elsewhere")  # type: ignore[arg-type]


def test_add_location_persists_and_is_read_back(tmp_path):
    shared = _dir(tmp_path, "example_data")
    config.add_location(shared)
    assert (tmp_path / "config" / "config.yaml").exists()
    config.refresh()  # as a fresh import would
    assert config.stores() == {"example_data": shared}


def test_add_location_without_persist_does_not_write(tmp_path):
    shared = _dir(tmp_path, "example_data")
    config.add_location(shared, persist=False)
    assert config.stores() == {"example_data": shared}
    assert not (tmp_path / "config" / "config.yaml").exists()
    config.refresh()
    assert config.stores() == {}


def test_remove_location_by_name(tmp_path):
    config.add_location(_dir(tmp_path, "first"), persist=False)
    config.add_location(_dir(tmp_path, "second"), persist=False)
    config.remove_location("first", persist=False)
    assert config.stores() == {"second": tmp_path / "second"}


def test_remove_location_by_path(tmp_path):
    shared = _dir(tmp_path, "example_data")
    config.add_location(shared, name="group", persist=False)
    config.remove_location(shared, persist=False)
    assert config.stores() == {}


def test_remove_location_resets_the_personal_dir(tmp_path):
    personal = _dir(tmp_path, "downloads")
    config.add_location(personal, "personal", persist=False)
    config.remove_location("personal", persist=False)
    assert config.get("data_dir") is None
    assert config.data_dir() == Path(pooch.os_cache("emdatabase"))


def test_remove_location_matches_the_personal_dir_by_path(tmp_path):
    personal = _dir(tmp_path, "downloads")
    config.add_location(personal, "personal", persist=False)
    config.remove_location(personal, persist=False)
    assert config.get("data_dir") is None


def test_remove_location_prefers_a_store_name(tmp_path):
    """A store named "personal" is still a store."""
    shared = _dir(tmp_path, "example_data")
    personal = _dir(tmp_path, "downloads")
    config.add_location(shared, name="personal", persist=False)
    config.add_location(personal, "personal", persist=False)
    config.remove_location("personal", persist=False)
    assert config.stores() == {}
    assert config.data_dir() == personal


def test_remove_location_raises_on_something_unconfigured(tmp_path):
    config.add_location(_dir(tmp_path, "example_data"), persist=False)
    with pytest.raises(KeyError, match="No location named or located at"):
        config.remove_location("nowhere")


def test_remove_location_persists(tmp_path):
    config.add_location(_dir(tmp_path, "example_data"))
    config.remove_location("example_data")
    config.refresh()
    assert config.stores() == {}


def test_locations_are_the_stores_then_the_personal_dir(tmp_path):
    first = _dir(tmp_path, "first")
    second = _dir(tmp_path, "second")
    personal = _dir(tmp_path, "downloads")
    config.add_location(first, persist=False)
    config.add_location(second, persist=False)
    config.add_location(personal, "personal", persist=False)

    assert config.locations() == [
        config.Location("first", first, "shared"),
        config.Location("second", second, "shared"),
        config.Location("personal", personal, "personal"),
    ]
    assert config.data_search_dirs() == [first, second, personal]


def test_the_top_level_re_exports_are_the_config_functions():
    assert emdatabase.add_location is config.add_location
    assert emdatabase.remove_location is config.remove_location
    assert emdatabase.locations is config.locations
