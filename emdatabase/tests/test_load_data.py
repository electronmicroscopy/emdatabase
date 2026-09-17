"""Tests for downloading datasets.

The expensive part of testing a download index is not the download - it is
knowing that every ``source`` still resolves. Checking that costs a HEAD request
per dataset, so it is done for all of them, under ``-m network``. Actually
pulling bytes only proves that pooch and the checksum verification are wired up
correctly, which is identical for every entry: the default run does that against
``conftest``'s local server (``test_locations``, ``test_weights``), and
``-m slow`` against the real hosts, with the smallest file in the index among
them.
"""

import io
import os
import threading
import time
import urllib.error
import urllib.request
import warnings
import zipfile
from pathlib import Path

import pytest

import emdatabase.data as data
from emdatabase._archive import _HTTPRangeFile
from emdatabase.data import MgONanoCrystals, NiEBSDLarge
from emdatabase.downloadable_dataset import (
    _PENDING,
    DatasetPath,
    DownloadableDataset,
    DownloadFailedWarning,
    _get_executor,
    _pending_key,
    _shutdown_executor,
    _TqdmProgress,
)

try:
    from quantem.core.io.file_readers import (  # pyright: ignore[reportMissingImports]
        read_4dstem,
    )

    QUANTEM_AVAILABLE = True
except ImportError:
    read_4dstem = None
    QUANTEM_AVAILABLE = False

# The smallest file in the index (34 kB). Used wherever a test needs a real
# download to exercise pooch rather than to exercise a particular dataset.
TINY_DATASET = "CuZnHAADF"

ALL_DATASETS = sorted(data.__all__)


def _url_cases():
    """``(name, version)`` for every entry, and for every dated weights version."""
    for name in ALL_DATASETS:
        yield name, None
        for version in getattr(data, name)().versions:
            yield name, version


URL_CASES = list(_url_cases())


def _head(url, timeout=60):
    """Return the response for a HEAD request, following redirects."""
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": "emdatabase tests"}
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _archive_member(url, member):
    """The directory entry for one member of a remote zip.

    A few small range requests rather than the whole archive, which is the
    reason an entry names a member in the first place.
    """
    with io.BufferedReader(_HTTPRangeFile(url), buffer_size=1 << 20) as stream:
        with zipfile.ZipFile(stream) as archive:
            return archive.getinfo(member)


@pytest.mark.network
@pytest.mark.parametrize(
    ("name", "version"),
    URL_CASES,
    ids=[name if version is None else f"{name}@{version}" for name, version in URL_CASES],
)
def test_source_url_resolves(name, version):
    """Every link in the index must still exist.

    This is what actually breaks over time - a Zenodo record superseded, a
    GitHub ref rewritten - and it is invisible until someone tries to download.
    Deselected by default: it is 20 HEAD requests, and running it on every leg
    of the push matrix meant 120 of them per push. The weekly check_sources
    workflow runs it instead.
    """
    dataset = getattr(data, name)()
    resolved = dataset._resolve(version)
    url = resolved.url
    try:
        response = _head(url)
    except urllib.error.HTTPError as error:
        pytest.fail(f"{name}: {url} returned HTTP {error.code}")
    except urllib.error.URLError as error:  # pragma: no cover - transient
        pytest.skip(f"{name}: network unavailable ({error.reason})")
    assert response.status == 200, f"{name}: {url} returned {response.status}"
    # The header the declared size came from. Checking it also catches the
    # source file being replaced, which is otherwise invisible until someone's
    # checksum fails. A weights family's `latest` link is meant to serve new
    # bytes, so only a pinned link is held to its declared size.
    # An archive entry's link is the zip, so the length to compare is the
    # archive's; the entry's own size_bytes describes the member inside it.
    archive = dataset.metadata.archive
    declared = archive.size_bytes if archive else resolved.size_bytes
    length = response.headers.get("Content-Length")
    if resolved.pinned and length is not None and declared is not None:
        assert int(length) == declared, (
            f"{name}: {url} is {int(length)} bytes, but the YAML declares {declared}"
        )
    if archive is not None:
        # What rots for an archive entry is the member being renamed or moved
        # inside a zip whose own size never changes.
        info = _archive_member(url, archive.member)
        assert info.file_size == resolved.size_bytes, (
            f"{name}: {archive.member} is {info.file_size} bytes inside {url}, "
            f"but the YAML declares {resolved.size_bytes}"
        )


@pytest.mark.parametrize("name", ALL_DATASETS)
def test_metadata_is_complete(name):
    """Entries need enough metadata for pooch to fetch and verify them."""
    dataset = getattr(data, name)()
    assert dataset.checksum and dataset.checksum.startswith("md5:"), (
        f"{name} has no md5 checksum, so a corrupt or truncated download would go unnoticed"
    )
    assert dataset.size_bytes, f"{name} has no size_bytes"


def test_an_explicit_url_is_what_gets_downloaded():
    """A link that does not end in the file name is given whole, as ``url``."""
    dataset = DownloadableDataset(
        description="A dataset behind an opaque link.",
        source="https://drive.google.com",
        url="https://drive.google.com/uc?export=download&id=abc",
        file="MyData.zspy",
    )
    assert dataset.download_url == "https://drive.google.com/uc?export=download&id=abc"


@pytest.mark.slow
def test_download_verifies_checksum(tmp_path):
    """A real download, to prove pooch and checksum verification are wired up."""
    dataset = getattr(data, TINY_DATASET)()
    path = dataset.download(destination=tmp_path, progressbar=False, background=False)
    assert (tmp_path / dataset.file).exists()
    assert isinstance(path, DatasetPath)
    assert isinstance(path, Path)
    assert path.done is True  # nothing pending, so the handle needs no waiting
    assert path == tmp_path / dataset.file


def _slow_retrieve(dataset, tmp_path, started=None):
    """A stand-in for ``_retrieve``: it takes a moment, then writes ``payload``."""

    def retrieve(destination=None, progressbar=True, chunk_size=4096, version=None, refresh=False):
        if started is not None:
            started.set()
        time.sleep(0.4)
        target = tmp_path / dataset.file
        target.write_bytes(b"payload")
        return str(target)

    return retrieve


def test_download_handle_is_nonblocking_then_blocks_on_use(tmp_path, monkeypatch):
    """download() returns before the file exists; touching the path waits for it."""
    dataset = getattr(data, TINY_DATASET)()
    started = threading.Event()
    monkeypatch.setattr(dataset, "_retrieve", _slow_retrieve(dataset, tmp_path, started))
    handle = dataset.download(destination=tmp_path, progressbar=False)

    assert started.wait(2)  # the worker thread really started
    assert handle.done is False  # returned without waiting for it
    assert not (tmp_path / dataset.file).exists()
    # Consuming the path blocks until the worker finishes, then resolves.
    assert Path(os.fspath(handle)).read_bytes() == b"payload"
    assert handle.done is True


def test_download_handle_derived_paths_also_wait(tmp_path, monkeypatch):
    """A path rebuilt from the handle names the same file, so it must wait too."""
    dataset = getattr(data, TINY_DATASET)()
    started = threading.Event()
    monkeypatch.setattr(dataset, "_retrieve", _slow_retrieve(dataset, tmp_path, started))
    handle = dataset.download(destination=tmp_path, progressbar=False)
    assert started.wait(2)

    derived = handle.parent / handle.name
    assert derived is not handle
    assert derived.done is False
    assert Path(os.fspath(derived)).read_bytes() == b"payload"


def test_a_path_that_is_not_downloading_never_waits(tmp_path, monkeypatch):
    """Only the file being fetched is pending - its directory is not."""
    dataset = getattr(data, TINY_DATASET)()

    monkeypatch.setattr(dataset, "_retrieve", _slow_retrieve(dataset, tmp_path))
    handle = dataset.download(destination=tmp_path, progressbar=False)
    assert handle.parent.done is True
    handle.wait()


def test_finished_downloads_leave_no_pending_entry(tmp_path, monkeypatch):
    dataset = getattr(data, TINY_DATASET)()
    monkeypatch.setattr(dataset, "_retrieve", _slow_retrieve(dataset, tmp_path))
    handle = dataset.download(destination=tmp_path, progressbar=False)
    handle.wait()
    key = _pending_key(handle)
    # the done-callback that clears the entry runs just after result() returns
    for _ in range(200):
        if key not in _PENDING:
            break
        time.sleep(0.01)
    assert key not in _PENDING


def _failing_retrieve(error):
    """A stand-in for ``_retrieve`` that fails the way an unreachable host does."""

    def retrieve(destination=None, progressbar=True, chunk_size=4096, version=None, refresh=False):
        raise error

    return retrieve


def test_a_failed_background_download_warns(tmp_path, monkeypatch):
    """The failure happens on another thread, so nothing else would report it."""
    dataset = getattr(data, TINY_DATASET)()
    monkeypatch.setattr(
        dataset, "_retrieve", _failing_retrieve(ConnectionError("zenodo.org is unreachable"))
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        handle = dataset.download(destination=tmp_path, progressbar=False)
        for _ in range(300):  # the warning comes from the worker thread
            if caught:
                break
            time.sleep(0.01)

    failures = [w for w in caught if issubclass(w.category, DownloadFailedWarning)]
    assert failures, [str(w.message) for w in caught]
    assert "unreachable" in str(failures[0].message)
    assert handle.failed is True
    assert handle.done is True  # it finished - just not successfully
    assert "failed" in repr(handle)


def test_a_failed_download_re_raises_when_the_path_is_used(tmp_path, monkeypatch):
    """Not FileNotFoundError: the handle still knows why the file is not there."""
    dataset = getattr(data, TINY_DATASET)()
    monkeypatch.setattr(dataset, "_retrieve", _failing_retrieve(ConnectionError("host is down")))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DownloadFailedWarning)
        handle = dataset.download(destination=tmp_path, progressbar=False)
        with pytest.raises(ConnectionError, match="host is down"):
            handle.result()
        with pytest.raises(ConnectionError, match="host is down"):
            os.fspath(handle)


def test_downloading_again_after_a_failure_retries(tmp_path, monkeypatch):
    """A kept failure must not stop the next attempt from replacing it."""
    dataset = getattr(data, TINY_DATASET)()
    monkeypatch.setattr(dataset, "_retrieve", _failing_retrieve(ConnectionError("down")))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DownloadFailedWarning)
        first = dataset.download(destination=tmp_path, progressbar=False)
        with pytest.raises(ConnectionError):
            first.result()

    monkeypatch.setattr(dataset, "_retrieve", _slow_retrieve(dataset, tmp_path))
    second = dataset.download(destination=tmp_path, progressbar=False)
    assert Path(os.fspath(second)).read_bytes() == b"payload"
    assert second.failed is False


def test_keyword_overrides_leave_the_class_spec_alone():
    base = getattr(data, TINY_DATASET)
    overridden = base(checksum="md5:" + "0" * 32)
    assert overridden.checksum == "md5:" + "0" * 32
    assert base().checksum != overridden.checksum


def test_a_dataset_rejects_a_version():
    """Versions are a weights family's; a dataset is one pinned file."""
    dataset = getattr(data, TINY_DATASET)()
    assert dataset.versions == ()
    with pytest.raises(ValueError, match="is a dataset and has no versions"):
        dataset.download(version="260902")


def test_a_dataset_without_a_source_is_an_error():
    with pytest.raises(TypeError):
        DownloadableDataset()


@pytest.mark.filterwarnings("ignore::emdatabase.downloadable_dataset.DownloadFailedWarning")
def test_download_handle_propagates_errors(tmp_path, monkeypatch):
    """A failed background download raises when the handle is consumed.

    The warning that failure also emits is this test's own doing; that it is
    emitted at all is ``test_a_failed_background_download_warns``'s business.
    """
    dataset = getattr(data, TINY_DATASET)()

    def fail(*args):
        raise ValueError("MD5 hash of downloaded file does not match")

    monkeypatch.setattr(dataset, "_retrieve", fail)
    handle = dataset.download(destination=tmp_path, progressbar=False)
    with pytest.raises(ValueError, match="does not match"):
        os.fspath(handle)


@pytest.mark.slow
def test_download_ni_ebsd(tmp_path):
    dataset = NiEBSDLarge()
    dataset.download(destination=tmp_path, progressbar=False, background=False)
    assert (tmp_path / "patterns_v2.h5").exists()


@pytest.mark.slow
def test_download_mgo_nanocrystals(tmp_path):
    dataset = MgONanoCrystals()
    dataset.download(destination=tmp_path, progressbar=False, background=False)
    assert (tmp_path / dataset.file).exists()


@pytest.mark.slow
@pytest.mark.skipif(not QUANTEM_AVAILABLE, reason="quantem is not installed")
def test_quantem_loading(tmp_path):
    assert read_4dstem is not None
    dataset = MgONanoCrystals()
    file_path = dataset.download(destination=tmp_path, progressbar=False, background=False)
    read_4dstem(file_path)


def test_tqdm_bar_waits_for_pooch_to_set_a_total():
    """pooch skips the downloader for a cached file, so the bar must be lazy."""
    progress = _TqdmProgress("demo")
    assert progress._bar is None  # nothing shown yet
    progress.total = 100
    assert progress._bar is not None
    progress.update(50)
    assert progress._bar.n == 50
    progress.reset()
    progress.update(100)
    assert progress._bar.n == 100
    progress.close()
    assert progress._bar is None


def test_tqdm_bar_is_not_squashed_to_79_pixels(monkeypatch):
    """pooch passes ncols=79 meaning terminal columns, but tqdm's notebook
    backend reads ncols as a pixel width - a bar 79 pixels wide, which is where
    the horizontal scrollbar in Jupyter comes from. Ours passes no ncols."""
    notebook_tqdm = pytest.importorskip("tqdm.notebook")

    squashed = notebook_tqdm.tqdm(total=1000, ncols=79)
    assert squashed.container.layout.width == "79px"  # what pooch produces
    squashed.close()

    # _TqdmProgress builds through tqdm.auto; force the notebook backend so the
    # widget layout is the thing under test rather than the terminal one.
    monkeypatch.setattr("tqdm.auto.tqdm", notebook_tqdm.tqdm)
    progress = _TqdmProgress("demo")
    progress.total = 1000
    assert progress._bar.container.layout.width is None  # ipywidgets default
    progress.close()


def test_progressbar_true_is_swapped_for_our_own_bar(tmp_path, monkeypatch):
    """`progressbar=True` must reach pooch as a Progress object, not as True."""
    seen = {}

    def fake_retrieve(**kwargs):
        seen["downloader"] = kwargs["downloader"]
        target = tmp_path / kwargs["fname"]
        target.write_bytes(b"payload")
        return str(target)

    monkeypatch.setattr("pooch.retrieve", fake_retrieve)
    dataset = getattr(data, TINY_DATASET)()
    dataset._retrieve(destination=tmp_path, progressbar=True)

    assert isinstance(seen["downloader"].progressbar, _TqdmProgress)
    assert seen["downloader"].progressbar is not True


def test_shutdown_cancels_queued_downloads():
    """The pool's threads are non-daemon, so anything still queued at exit would
    hold the interpreter open. Queued work is cancelled; started work is not."""
    executor = _get_executor()
    started = threading.Event()
    release = threading.Event()

    def block():
        started.set()
        release.wait(timeout=5)

    running = [executor.submit(block) for _ in range(4)]  # fill every worker
    queued = [executor.submit(block) for _ in range(8)]
    started.wait(timeout=5)
    try:
        _shutdown_executor()
        assert any(f.cancelled() for f in queued)
        assert not any(f.cancelled() for f in running)
    finally:
        release.set()


def test_a_background_download_builds_its_bar_on_the_calling_thread(tmp_path, monkeypatch):
    """A notebook shows a bar in the cell that was running when it was built, which
    a pool thread does not know. A file already on disk gets no bar, and a
    caller's own Progress is passed through untouched."""
    dataset = getattr(data, TINY_DATASET)()
    seen = []
    built_on = []

    def record(destination=None, progressbar=True, chunk_size=4096, version=None, refresh=False):
        seen.append(progressbar)
        target = tmp_path / dataset.file
        target.write_bytes(b"payload")
        return str(target)

    class Bar:
        def __init__(self, **kwargs):
            built_on.append(threading.current_thread())

    monkeypatch.setattr(dataset, "_retrieve", record)
    monkeypatch.setattr("tqdm.auto.tqdm", Bar)

    dataset.download(destination=tmp_path).wait(2)
    assert isinstance(seen[0], _TqdmProgress)
    assert built_on == [threading.current_thread()]

    mine = object()
    dataset.download(destination=tmp_path).wait(2)  # on disk now
    dataset.download(destination=tmp_path, progressbar=mine).wait(2)
    assert seen[1:] == [True, mine]
    assert len(built_on) == 1
