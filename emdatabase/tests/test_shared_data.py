"""Tests for the ~/.emdatabase settings folder and system-wide data resolution.

The conftest fixture isolates the user + system config and clears the shared/data
env vars, so these exercise the resolution logic in isolation (no network - the
"downloads" here find a pre-placed file).
"""

import os

import emdatabase
from emdatabase import catalogue, config
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.tests.test_load_data import TINY_DATASET


def _dataset() -> DownloadableDataset:
    ds = catalogue.resolve(TINY_DATASET)
    assert ds is not None
    return ds


def test_settings_live_in_dot_emdatabase(monkeypatch):
    monkeypatch.delenv("EM_DATABASE_CONFIG", raising=False)  # use the real default
    path = config.config_path()
    assert path.parent.name == ".emdatabase"
    assert path.name == "settings.yaml"


def test_shared_dir_is_searched_before_the_user_dir(tmp_path, monkeypatch):
    shared, user = tmp_path / "shared", tmp_path / "user"
    shared.mkdir()
    user.mkdir()
    monkeypatch.setenv("EM_DATABASE_SHARED_DIR", str(shared))
    emdatabase.set_data_dir(str(user), persist=False)

    ds = _dataset()
    assert ds.filepath() is None  # nowhere yet
    (user / ds.file).write_bytes(b"user")
    assert ds.filepath() == user / ds.file  # found in the user dir
    (shared / ds.file).write_bytes(b"shared")
    assert ds.filepath() == shared / ds.file  # shared/system wins


def test_download_uses_a_shared_copy_without_refetching(tmp_path, monkeypatch):
    shared, user = tmp_path / "shared", tmp_path / "user"
    shared.mkdir()
    user.mkdir()
    monkeypatch.setenv("EM_DATABASE_SHARED_DIR", str(shared))
    emdatabase.set_data_dir(str(user), persist=False)

    ds = _dataset()
    (shared / ds.file).write_bytes(b"payload")  # pre-installed system-wide
    path = ds.download(background=False)
    assert path == shared / ds.file  # used the shared copy
    assert not (user / ds.file).exists()  # nothing downloaded to the user dir


def test_search_order_is_shared_then_user(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("EM_DATABASE_SHARED_DIR", os.pathsep.join([str(a), str(b)]))
    emdatabase.set_data_dir(str(tmp_path / "user"), persist=False)
    assert config.data_search_dirs() == [a, b, tmp_path / "user"]


def test_system_config_file_contributes_shared_dirs(tmp_path, monkeypatch):
    system_file = tmp_path / "system.yaml"
    system_file.write_text(f"data_dir: {tmp_path / 'sitewide'}\n", encoding="utf-8")
    monkeypatch.setenv("EM_DATABASE_SYSTEM_CONFIG", str(system_file))
    assert tmp_path / "sitewide" in config.shared_data_dirs()


def test_filepaths_reports_every_copy(tmp_path, monkeypatch):
    """A shared install and your own download of the same file coexist."""
    shared, user = tmp_path / "shared", tmp_path / "user"
    shared.mkdir()
    user.mkdir()
    monkeypatch.setenv("EM_DATABASE_SHARED_DIR", str(shared))
    emdatabase.set_data_dir(str(user), persist=False)

    ds = _dataset()
    assert ds.filepaths() == []
    (shared / ds.file).write_bytes(b"shared")
    assert ds.filepaths() == [shared / ds.file]
    (user / ds.file).write_bytes(b"user")
    assert ds.filepaths() == [shared / ds.file, user / ds.file]
    assert ds.filepath() == shared / ds.file  # the winner is still the shared one


def test_entry_exposes_a_user_copy_hiding_behind_a_shared_one(tmp_path, monkeypatch):
    """The widget needs to see the copy delete() would remove, not just the winner."""
    shared, user = tmp_path / "shared", tmp_path / "user"
    shared.mkdir()
    user.mkdir()
    monkeypatch.setenv("EM_DATABASE_SHARED_DIR", str(shared))
    emdatabase.set_data_dir(str(user), persist=False)

    ds = _dataset()
    (shared / ds.file).write_bytes(b"shared")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "shared"
    assert row["user_path"] == ""  # nothing of yours to delete

    (user / ds.file).write_bytes(b"user")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "shared"  # the shared copy is still the one in use
    assert row["user_path"] == str(user / ds.file)

    assert ds.delete() is True  # deletes yours
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["user_path"] == ""
    assert (shared / ds.file).exists()  # the shared copy is untouched
    assert row["downloaded"] is True  # and still resolves


def test_entry_user_path_when_there_is_no_share(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.delenv("EM_DATABASE_SHARED_DIR", raising=False)
    emdatabase.set_data_dir(str(user), persist=False)

    ds = _dataset()
    (user / ds.file).write_bytes(b"user")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "user"
    assert row["user_path"] == str(user / ds.file)
