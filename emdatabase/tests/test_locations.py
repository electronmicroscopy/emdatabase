"""Tests for named locations: read-only directories searched before the personal one.

The conftest fixture isolates the config, so these exercise the resolution logic
on its own (no network - the "downloads" here find a pre-placed file, and the
one test that seeds a shared location fetches from ``conftest``'s local HTTP
server).
"""

import hashlib
from pathlib import Path

import pytest

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


def _configure(tmp_path, **shared):
    """A personal directory plus any number of shared ones, all under tmp_path."""
    user = tmp_path / "user"
    user.mkdir(exist_ok=True)
    made = {}
    for name, subdir in shared.items():
        path = tmp_path / subdir
        path.mkdir(exist_ok=True)
        made[name] = str(path)
    made["personal"] = str(user)
    config.set({"locations": made})
    return user


def test_a_shared_location_is_searched_before_the_personal_one(tmp_path):
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    ds = _dataset()
    assert ds.filepath() is None  # nowhere yet
    (user / ds.file).write_bytes(b"user")
    assert ds.filepath() == user / ds.file  # found in the personal dir
    (group / ds.file).write_bytes(b"group")
    assert ds.filepath() == group / ds.file  # the shared location wins


def test_download_uses_a_shared_copy_without_refetching(tmp_path):
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    ds = _dataset()
    (group / ds.file).write_bytes(b"payload")  # pre-installed for the group
    path = ds.download(background=False)
    assert path == group / ds.file  # used the shared copy
    assert not (user / ds.file).exists()  # nothing downloaded to the personal dir


def test_search_order_is_the_shared_ones_in_order_then_personal(tmp_path):
    user = _configure(tmp_path, first="a", second="b")
    assert config.data_search_dirs() == [tmp_path / "a", tmp_path / "b", user]


def test_env_var_publishes_a_shared_location(tmp_path, monkeypatch):
    monkeypatch.setenv("EMDATABASE_LOCATIONS__GROUP", str(tmp_path / "group"))
    config.refresh()
    assert config.locations()[0] == config.Location("group", tmp_path / "group", "shared")


def test_filepaths_reports_every_copy(tmp_path):
    """A shared copy and your own download of the same file coexist."""
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    ds = _dataset()
    assert ds.filepaths() == []
    (group / ds.file).write_bytes(b"group")
    assert ds.filepaths() == [group / ds.file]
    (user / ds.file).write_bytes(b"user")
    assert ds.filepaths() == [group / ds.file, user / ds.file]
    assert ds.filepath() == group / ds.file  # the winner is still the shared one


def test_entry_reports_the_location_name(tmp_path):
    """Provenance is by name: which location a copy came from, not just "shared"."""
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    ds = _dataset()
    (group / ds.file).write_bytes(b"group")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "group"
    assert row["user_path"] == ""  # nothing of yours to delete

    (user / ds.file).write_bytes(b"user")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "group"  # the shared copy is still the one in use
    assert row["user_path"] == str(user / ds.file)

    assert ds.delete() is True  # deletes yours
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["user_path"] == ""
    assert (group / ds.file).exists()  # the shared copy is untouched
    assert row["downloaded"] is True  # and still resolves


def test_entry_location_is_personal_when_nothing_is_shared(tmp_path):
    user = _configure(tmp_path)

    ds = _dataset()
    (user / ds.file).write_bytes(b"user")
    row = catalogue.entry(TINY_DATASET, ds)
    assert row["location"] == "personal"
    assert row["user_path"] == str(user / ds.file)


def test_downloads_go_to_the_personal_directory(tmp_path):
    user = _configure(tmp_path, group="group")

    ds = _dataset()
    path = ds.download(progressbar=False, background=False)
    assert path == user / ds.file
    assert not (tmp_path / "group" / ds.file).exists()


def test_the_catalogue_payload_carries_the_locations(tmp_path):
    user = _configure(tmp_path, group="group")
    payload = catalogue.catalogue()
    assert payload["locations"] == {"group": str(tmp_path / "group"), "personal": str(user)}
    assert payload["data_dir"] == str(config.data_dir())


# ---------------------------------------------------------------------------
# A location's name as a destination
# ---------------------------------------------------------------------------


def test_download_to_a_shared_location_by_name(tmp_path, served):
    """Naming a shared location as the destination is how one is seeded."""
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    path = served.download(destination="group", progressbar=False, background=False)
    assert path == group / served.file
    assert path.read_bytes() == CONTENT
    assert not (user / served.file).exists()


def test_download_to_personal_by_name(tmp_path, served):
    user = _configure(tmp_path, group="group")

    path = served.download(destination="personal", progressbar=False, background=False)
    assert path == user / served.file
    assert not (tmp_path / "group" / served.file).exists()


def test_a_background_download_targets_the_location_before_it_finishes(tmp_path, served):
    """The handle points at the configured directory, not at a ``group``
    directory relative to the working directory."""
    _configure(tmp_path, group="group")
    group = tmp_path / "group"

    handle = served.download(destination="group", progressbar=False)
    assert handle == group / served.file  # comparing paths never blocks
    assert handle.result() == group / served.file


def test_a_destination_that_is_not_a_location_name_is_a_path(tmp_path, served):
    _configure(tmp_path, group="group")
    elsewhere = tmp_path / "elsewhere"

    path = served.download(destination=str(elsewhere), progressbar=False, background=False)
    assert path == elsewhere / served.file
    assert not (tmp_path / "group" / served.file).exists()


def test_a_path_is_never_a_location_name(tmp_path):
    """Only a string is looked up; ``Path("group")`` is a relative directory."""
    _configure(tmp_path, group="group")

    assert config.resolve_destination("group") == tmp_path / "group"
    assert config.resolve_destination(Path("group")) == Path("group")
    assert DownloadableDataset._resolve_destination(Path("group")) == Path("group")


def test_resolve_destination_passes_none_through(tmp_path):
    _configure(tmp_path, group="group")
    assert config.resolve_destination(None) is None


def test_delete_by_location_name_removes_the_shared_copy(tmp_path):
    """``delete()`` never touches a shared location; ``delete("group")`` does."""
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    ds = _dataset()
    (group / ds.file).write_bytes(b"group")
    (user / ds.file).write_bytes(b"user")

    assert ds.delete() is True  # yours only
    assert (group / ds.file).exists()
    assert ds.filepath() == group / ds.file  # which is what you now resolve to

    assert ds.delete(destination="group") is True
    assert not (group / ds.file).exists()
    assert ds.filepath() is None  # nothing left anywhere


def test_delete_personal_by_name_is_the_bare_delete(tmp_path):
    user = _configure(tmp_path, group="group")
    group = tmp_path / "group"

    ds = _dataset()
    (group / ds.file).write_bytes(b"group")
    (user / ds.file).write_bytes(b"user")

    assert ds.delete(destination="personal") is True
    assert not (user / ds.file).exists()
    assert (group / ds.file).exists()
