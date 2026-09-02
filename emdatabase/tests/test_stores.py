"""Tests for named stores: read-only directories searched before the data dir.

The conftest fixture isolates the config, so these exercise the resolution logic
on its own (no network - the "downloads" here find a pre-placed file, and the
one test that seeds a store fetches from ``conftest``'s local HTTP server).
"""

import hashlib
from pathlib import Path

import pytest

import emdatabase
from emdatabase import catalogue, config
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.tests.test_load_data import TINY_DATASET

CONTENT = b"a tiny dataset, allegedly" * 10


def _dataset() -> DownloadableDataset:
    ds = catalogue.resolve(TINY_DATASET)
    assert ds is not None
    return ds


@pytest.fixture
def served(http_server):
    """A dataset served from localhost, for the tests that really download."""
    base, directory = http_server
    (directory / "Tiny.zspy").write_bytes(CONTENT)
    return DownloadableDataset(
        description="A tiny dataset, served locally.",
        source=base,
        file="Tiny.zspy",
        checksum=f"md5:{hashlib.md5(CONTENT).hexdigest()}",
    )


def _configure(tmp_path, **stores):
    """A user data dir plus any number of named stores, all under tmp_path."""
    user = tmp_path / "user"
    user.mkdir(exist_ok=True)
    made = {}
    for name, subdir in stores.items():
        path = tmp_path / subdir
        path.mkdir(exist_ok=True)
        made[name] = str(path)
    config.set({"data_dir": str(user), "stores": made})
    return user


def test_a_store_is_searched_before_the_user_dir(tmp_path):
    user = _configure(tmp_path, group="group")
    store = tmp_path / "group"

    ds = _dataset()
    assert ds.filepath() is None  # nowhere yet
    (user / ds.file).write_bytes(b"user")
    assert ds.filepath() == user / ds.file  # found in the user dir
    (store / ds.file).write_bytes(b"group")
    assert ds.filepath() == store / ds.file  # the store wins


def test_download_uses_a_store_copy_without_refetching(tmp_path):
    user = _configure(tmp_path, group="group")
    store = tmp_path / "group"

    ds = _dataset()
    (store / ds.file).write_bytes(b"payload")  # pre-installed for the group
    path = ds.download(background=False)
    assert path == store / ds.file  # used the store's copy
    assert not (user / ds.file).exists()  # nothing downloaded to the user dir


def test_search_order_is_stores_in_order_then_the_user_dir(tmp_path):
    user = _configure(tmp_path, first="a", second="b")
    assert config.data_search_dirs() == [tmp_path / "a", tmp_path / "b", user]


def test_env_var_publishes_a_store(tmp_path, monkeypatch):
    monkeypatch.setenv("EMDATABASE_STORES__GROUP", str(tmp_path / "group"))
    config.refresh()
    assert config.stores() == {"group": tmp_path / "group"}


def test_filepaths_reports_every_copy(tmp_path):
    """A store's copy and your own download of the same file coexist."""
    user = _configure(tmp_path, group="group")
    store = tmp_path / "group"

    ds = _dataset()
    assert ds.filepaths() == []
    (store / ds.file).write_bytes(b"group")
    assert ds.filepaths() == [store / ds.file]
    (user / ds.file).write_bytes(b"user")
    assert ds.filepaths() == [store / ds.file, user / ds.file]
    assert ds.filepath() == store / ds.file  # the winner is still the store's


def test_entry_reports_the_store_name_as_the_location(tmp_path):
    """Provenance is by name: which store a copy came from, not just "shared"."""
    user = _configure(tmp_path, group="group")
    store = tmp_path / "group"

    ds = _dataset()
    (store / ds.file).write_bytes(b"group")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "group"
    assert row["user_path"] == ""  # nothing of yours to delete

    (user / ds.file).write_bytes(b"user")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "group"  # the store's copy is still the one in use
    assert row["user_path"] == str(user / ds.file)

    assert ds.delete() is True  # deletes yours
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["user_path"] == ""
    assert (store / ds.file).exists()  # the store's copy is untouched
    assert row["downloaded"] is True  # and still resolves


def test_entry_location_is_user_when_there_is_no_store(tmp_path):
    user = _configure(tmp_path)

    ds = _dataset()
    (user / ds.file).write_bytes(b"user")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "user"
    assert row["user_path"] == str(user / ds.file)


def test_downloads_go_to_the_data_dir(tmp_path):
    user = _configure(tmp_path, group="group")

    ds = _dataset()
    path = ds.download(progressbar=False, background=False)
    assert path == user / ds.file
    assert not (tmp_path / "group" / ds.file).exists()


def test_the_catalogue_payload_carries_the_stores(tmp_path):
    _configure(tmp_path, group="group")
    payload = catalogue.catalogue()
    assert payload["stores"] == {"group": str(tmp_path / "group")}
    assert payload["data_dir"] == str(emdatabase.get_data_dir())


# ---------------------------------------------------------------------------
# A store's name as a destination
# ---------------------------------------------------------------------------


def test_download_to_a_store_by_name(tmp_path, served):
    """Naming a store as the destination is how one is seeded."""
    user = _configure(tmp_path, group="group")
    store = tmp_path / "group"

    path = served.download(destination="group", progressbar=False, background=False)
    assert path == store / served.file
    assert path.read_bytes() == CONTENT
    assert not (user / served.file).exists()


def test_a_background_download_targets_the_store_before_it_finishes(tmp_path, served):
    """The handle points at the store's directory, not at a ``group`` directory
    relative to the working directory."""
    _configure(tmp_path, group="group")
    store = tmp_path / "group"

    handle = served.download(destination="group", progressbar=False)
    assert handle == store / served.file  # comparing paths never blocks
    assert handle.result() == store / served.file


def test_a_destination_that_is_not_a_store_name_is_a_path(tmp_path, served):
    _configure(tmp_path, group="group")
    elsewhere = tmp_path / "elsewhere"

    path = served.download(destination=str(elsewhere), progressbar=False, background=False)
    assert path == elsewhere / served.file
    assert not (tmp_path / "group" / served.file).exists()


def test_a_path_is_never_a_store_name(tmp_path):
    """Only a string is looked up; ``Path("group")`` is a relative directory."""
    _configure(tmp_path, group="group")

    assert config.resolve_destination("group") == tmp_path / "group"
    assert config.resolve_destination(Path("group")) == Path("group")
    assert DownloadableDataset._resolve_destination(Path("group")) == Path("group")


def test_resolve_destination_passes_none_through(tmp_path):
    _configure(tmp_path, group="group")
    assert config.resolve_destination(None) is None


def test_delete_by_store_name_removes_the_store_copy(tmp_path):
    """``delete()`` never touches a store; ``delete("group")`` is how you ask."""
    user = _configure(tmp_path, group="group")
    store = tmp_path / "group"

    ds = _dataset()
    (store / ds.file).write_bytes(b"group")
    (user / ds.file).write_bytes(b"user")

    assert ds.delete() is True  # yours only
    assert (store / ds.file).exists()
    assert ds.filepath() == store / ds.file  # which is what you now resolve to

    assert ds.delete(destination="group") is True
    assert not (store / ds.file).exists()
    assert ds.filepath() is None  # nothing left anywhere
