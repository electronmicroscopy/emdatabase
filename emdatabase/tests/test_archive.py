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
import tempfile
import zipfile
from pathlib import Path

import py7zr
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


# --- the same, out of a 7z -------------------------------------------------
#
# A zip compresses each member on its own; a 7z compresses them together in
# solid blocks and can only be extracted to a directory. Both end up at the same
# place, so the behaviour asserted here is deliberately the zip's.

MEMBER_7Z = "Fig_01/Panel_g-h_Themis/scan.raw"


def _sevenzip_bytes() -> bytes:
    """A small .7z holding the member and a decoy sharing its file name."""
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        (work / "good").write_bytes(CONTENT)
        (work / "decoy").write_bytes(DECOY_CONTENT)
        built = work / "built.7z"
        with py7zr.SevenZipFile(built, "w") as archive:
            archive.write(work / "decoy", DECOY)
            archive.write(work / "good", MEMBER_7Z)
        return built.read_bytes()


@pytest.fixture
def archived_7z(http_server):
    """Build a dataset whose file is one member of a 7z served from localhost."""
    base, directory = http_server
    (directory / "Fig_01.7z").write_bytes(_sevenzip_bytes())

    def make(**overrides):
        archive = {"url": f"{base}/Fig_01.7z", "member": MEMBER_7Z, **overrides.pop("archive", {})}
        spec = {
            "description": "One headerless raw file inside a 7z.",
            "source": base,
            "file": "scan.raw",
            "checksum": f"md5:{hashlib.md5(CONTENT).hexdigest()}",
            "size_bytes": len(CONTENT),
            "archive": archive,
            **overrides,
        }
        return DownloadableDataset(**spec)

    return make


def test_a_7z_member_comes_out_byte_for_byte(archived_7z, dest):
    path = archived_7z().download(destination=dest, progressbar=False, background=False)
    assert Path(path).read_bytes() == CONTENT


def test_a_7z_member_the_archive_does_not_hold_names_it(archived_7z, dest):
    """py7zr extracts nothing and raises nothing for a name it lacks, so we check."""
    ds = archived_7z(archive={"member": "Fig_01/Panel_g-h_Themis/missing.raw"})
    with pytest.raises(KeyError, match="missing.raw"):
        ds.download(destination=dest, progressbar=False, background=False)
    assert list(dest.iterdir()) == []


def test_a_wrong_checksum_on_a_7z_leaves_no_file(archived_7z, dest):
    ds = archived_7z(checksum="md5:" + "0" * 32)
    with pytest.raises(ValueError):
        ds.download(destination=dest, progressbar=False, background=False)
    assert list(dest.iterdir()) == []


def test_the_7z_progress_object_reaches_the_total(archived_7z, dest):
    """py7zr reports once at the end, so only the final state is meaningful."""
    bar = _Recorder()
    archived_7z().download(destination=dest, progressbar=bar, background=False)
    assert bar.total == len(CONTENT)
    assert bar.done == len(CONTENT)
    assert bar.closed


def test_a_7z_host_that_ignores_range_fails_loudly(archived_7z, dest, http_server):
    base, _ = http_server
    ds = archived_7z(archive={"url": f"{base}/attached/Fig_01.7z"})
    with pytest.raises(ArchiveError, match="Range"):
        ds.download(destination=dest, progressbar=False, background=False)
    assert list(dest.iterdir()) == []


def test_a_host_that_stops_serving_mid_read_says_so(archived, dest, http_server):
    """The archive is found, then the host goes down while its bytes are being read.

    ``zipfile`` turns any ``OSError`` raised while it reads the directory into
    ``BadZipFile("File is not a zip file")``, so an outage reported as it
    happens is the difference between a message about the host and one blaming
    the archive.
    """
    base, _ = http_server
    ds = archived(archive={"url": f"{base}/flaky/Fig_01.zip"})
    with pytest.raises(ArchiveError, match="503"):
        ds.download(destination=dest, progressbar=False, background=False)
    assert list(dest.iterdir()) == []


# --- more than one member --------------------------------------------------
#
# Some data is not one file. An EMPAD acquisition is a header naming a raw it
# expects to find beside it, so both have to arrive, under the names the archive
# gave them, in a directory of their own.

COMPANION = "Fig_01/Panel_g-h_Themis/scan_x256_y256.raw"
COMPANION_CONTENT = b"raw detector frames " * 500


@pytest.fixture
def paired(http_server):
    """A dataset whose file is a header naming a second member beside it."""
    base, directory = http_server
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MEMBER, CONTENT)
        archive.writestr(COMPANION, COMPANION_CONTENT)
    (directory / "Paired.zip").write_bytes(buffer.getvalue())

    def make(**overrides):
        spec = {
            "description": "A header and the file it names.",
            "source": base,
            "file": "Paired/scan.raw",
            "checksum": f"md5:{hashlib.md5(CONTENT).hexdigest()}",
            "size_bytes": len(CONTENT),
            "archive": {
                "url": f"{base}/Paired.zip",
                "member": MEMBER,
                "companions": [
                    {
                        "member": COMPANION,
                        "file": "Paired/scan_x256_y256.raw",
                        "checksum": f"md5:{hashlib.md5(COMPANION_CONTENT).hexdigest()}",
                        "size_bytes": len(COMPANION_CONTENT),
                    }
                ],
            },
            **overrides,
        }
        return DownloadableDataset(**spec)

    return make


def test_a_companion_lands_beside_the_entrys_own_file(paired, dest):
    """Both members, one directory, the names the archive gave them."""
    path = paired().download(destination=dest, progressbar=False, background=False)

    assert Path(path).name == "scan.raw"  # the entry's own file is what comes back
    folder = dest / "Paired"
    assert sorted(p.name for p in folder.iterdir()) == ["scan.raw", "scan_x256_y256.raw"]
    assert (folder / "scan_x256_y256.raw").read_bytes() == COMPANION_CONTENT


def test_a_companion_with_a_wrong_checksum_fails(paired, dest):
    """Each member is verified on its own, not just the one handed back."""
    ds = paired(
        archive={
            "url": paired().metadata.archive.url,
            "member": MEMBER,
            "companions": [
                {
                    "member": COMPANION,
                    "file": "Paired/scan_x256_y256.raw",
                    "checksum": "md5:" + "0" * 32,
                }
            ],
        }
    )
    with pytest.raises(ValueError):
        ds.download(destination=dest, progressbar=False, background=False)


def test_delete_removes_the_companion_too(paired, dest):
    """The companion is usually the large one, so leaving it would free nothing."""
    config.set({"locations": {"personal": str(dest)}})
    ds = paired()
    ds.download(progressbar=False, background=False)
    folder = dest / "Paired"

    assert len(list(folder.iterdir())) == 2
    assert ds.delete() is True
    assert list(folder.iterdir()) == []


def test_a_shared_copy_missing_its_companion_is_not_used(paired, tmp_path, dest):
    """A header without its raw is not the dataset, so the whole set is fetched."""
    group = tmp_path / "group"
    (group / "Paired").mkdir(parents=True)
    (group / "Paired/scan.raw").write_bytes(CONTENT)  # the header arrived; the raw did not
    config.set({"locations": {"group": str(group), "personal": str(dest)}})
    ds = paired()

    assert ds.filepath() is None  # a partial copy is not a copy
    path = ds.download(progressbar=False, background=False)

    assert Path(path) == dest / "Paired/scan.raw"  # not the shared header
    assert (dest / "Paired/scan_x256_y256.raw").read_bytes() == COMPANION_CONTENT


def test_a_complete_shared_copy_is_still_used_as_is(paired, tmp_path, dest):
    """The shortcut stays a shortcut: both members there means nothing is fetched."""
    group = tmp_path / "group"
    (group / "Paired").mkdir(parents=True)
    (group / "Paired/scan.raw").write_bytes(CONTENT)
    (group / "Paired/scan_x256_y256.raw").write_bytes(COMPANION_CONTENT)
    config.set({"locations": {"group": str(group), "personal": str(dest)}})

    path = paired().download(progressbar=False, background=False)

    assert Path(path) == group / "Paired/scan.raw"
    assert list(dest.iterdir()) == []  # nothing downloaded to the personal dir


def test_the_size_shown_counts_the_companion(paired):
    """`size_bytes` is the entry's own file; `size` is what the dataset occupies."""
    md = paired().metadata
    assert md.size_bytes == len(CONTENT)
    assert md.total_bytes == len(CONTENT) + len(COMPANION_CONTENT)
