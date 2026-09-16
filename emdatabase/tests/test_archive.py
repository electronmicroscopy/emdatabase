"""Tests for fetching one member out of a remote zip.

``conftest``'s server answers ``Range`` with ``206``, so all of this runs
offline against a zip built here rather than the multi-gigabyte archives the
feature exists for. Its ``/attached/`` path still ignores ``Range`` and answers
``200``, which is the host that does not do ranges at all.

pooch owns the temporary file, the checksum check and the rename, so the tests
that assert nothing is left behind are asserting that this downloader lets pooch
do that job rather than writing the destination itself.
"""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from emdatabase import config
from emdatabase._archive import ArchiveError
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.widget import DownloadCancelled

MEMBER = "Fig_01/Panel_g-h_Themis/scan.raw"
CONTENT = b"detector frames, allegedly" * 4000
# The same file name in another directory of the same archive: naming the member
# by its basename alone would be ambiguous, which is why entries give the path.
DECOY = "Fig_01/Panel_c-d_Talos/scan.raw"
DECOY_CONTENT = b"the wrong panel entirely" * 4000


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(DECOY, DECOY_CONTENT)
        archive.writestr(MEMBER, CONTENT)
    return buffer.getvalue()


@pytest.fixture
def archived(http_server):
    """Build a dataset whose file is one member of a zip served from localhost."""
    base, directory = http_server
    (directory / "Fig_01.zip").write_bytes(_zip_bytes())

    def make(**overrides):
        archive = {"url": f"{base}/Fig_01.zip", "member": MEMBER, **overrides.pop("archive", {})}
        spec = {
            "description": "One headerless raw file inside a zip.",
            "source": base,
            "file": "scan.raw",
            "checksum": f"md5:{hashlib.md5(CONTENT).hexdigest()}",
            "size_bytes": len(CONTENT),
            "archive": archive,
            **overrides,
        }
        return DownloadableDataset(**spec)

    return make


@pytest.fixture
def dest(tmp_path):
    """A download directory of its own.

    ``tmp_path`` itself is not empty - the config fixture and ``http_server``
    both keep directories there - so "nothing was left behind" has to be asked
    of a directory only the download writes to.
    """
    path = tmp_path / "downloads"
    path.mkdir()
    return path


class _Recorder:
    """The progress protocol, remembering what it was driven with."""

    def __init__(self):
        self.total = 0
        self.done = 0
        self.closed = False

    def update(self, n):
        self.done += n

    def reset(self):
        self.done = 0

    def close(self):
        self.closed = True


def test_the_member_comes_out_byte_for_byte(archived, dest):
    """Including that it is the named member, not the one with the same basename."""
    path = archived().download(destination=dest, progressbar=False, background=False)
    assert Path(path).read_bytes() == CONTENT


def test_download_url_is_the_archive(archived):
    """The member has no link of its own; the archive is the only one there is."""
    assert archived().download_url.endswith("/Fig_01.zip")


def test_a_wrong_checksum_fails_and_leaves_no_file(archived, dest):
    ds = archived(checksum="md5:" + "0" * 32)
    with pytest.raises(ValueError):
        ds.download(destination=dest, progressbar=False, background=False)
    assert list(dest.iterdir()) == []  # not the file, and not a temporary either


def test_the_progress_object_is_driven_the_way_pooch_drives_it(archived, dest):
    bar = _Recorder()
    archived().download(destination=dest, progressbar=bar, background=False)
    assert bar.total == len(CONTENT)
    assert bar.done == len(CONTENT)  # reset() then one final update, so it reaches 100%
    assert bar.closed


def test_a_cancel_raised_from_update_aborts_and_leaves_no_file(archived, dest):
    """How the widgets cancel a download: the exception comes back out of update."""

    class Cancelling(_Recorder):
        def update(self, n):
            raise DownloadCancelled("stop")

    with pytest.raises(DownloadCancelled):
        archived().download(destination=dest, progressbar=Cancelling(), background=False)
    assert list(dest.iterdir()) == []


def test_a_member_the_archive_does_not_hold_names_it(archived, dest):
    ds = archived(archive={"member": "Fig_01/Panel_g-h_Themis/missing.raw"})
    with pytest.raises(KeyError, match="missing.raw"):
        ds.download(destination=dest, progressbar=False, background=False)


def test_a_host_that_ignores_range_fails_loudly(archived, dest, http_server):
    """Answering 200 to a range request means the whole archive; refuse it."""
    base, _ = http_server
    ds = archived(archive={"url": f"{base}/attached/Fig_01.zip"})
    with pytest.raises(ArchiveError, match="Range"):
        ds.download(destination=dest, progressbar=False, background=False)
    assert list(dest.iterdir()) == []


def test_filepath_and_delete_behave_as_for_any_other_dataset(archived, dest):
    config.set({"locations": {"personal": str(dest)}})

    ds = archived()
    assert ds.filepath() is None
    ds.download(progressbar=False, background=False)
    assert ds.filepath() == dest / "scan.raw"
    assert ds.delete() is True
    assert ds.filepath() is None
