"""Tests for downloading datasets.

The expensive part of testing a download index is not the download - it is
knowing that every ``source`` still resolves. Checking that costs a HEAD request
per dataset, so it is done for all of them. Actually pulling bytes only proves
that pooch and the checksum verification are wired up correctly, which is
identical for every entry, so it is done once with the smallest file in the
index. The large downloads are marked ``slow`` and deselected by default; run
them with ``pytest -m slow``.
"""

import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import emdatabase.data as data
from emdatabase import catalogue
from emdatabase.data import MgONanoCrystals, NiEBSDLarge
from emdatabase.downloadable_dataset import (
    _PENDING,
    DatasetPath,
    DownloadableDataset,
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
    resolved = getattr(data, name)()._resolve(version)
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
    length = response.headers.get("Content-Length")
    if resolved.pinned and length is not None and resolved.size_bytes is not None:
        assert int(length) == resolved.size_bytes, (
            f"{name}: {url} is {int(length)} bytes, but the YAML declares {resolved.size_bytes}"
        )


@pytest.mark.parametrize("name", ALL_DATASETS)
def test_metadata_is_complete(name):
    """Entries need enough metadata for pooch to fetch and verify them."""
    dataset = getattr(data, name)()
    assert dataset.source, f"{name} has no source"
    assert dataset.file, f"{name} has no file"
    assert dataset.metadata.description, f"{name} has no description"
    assert dataset.checksum and dataset.checksum.startswith("md5:"), (
        f"{name} has no md5 checksum, so a corrupt or truncated download would go unnoticed"
    )
    assert dataset.size_bytes, f"{name} has no size_bytes"


def test_download_url_joins_the_source_and_the_file():
    dataset = getattr(data, TINY_DATASET)()
    assert dataset.download_url == f"{dataset.source}/{dataset.file}"


def test_an_explicit_url_is_what_gets_downloaded():
    """A link that does not end in the file name is given whole, as ``url``."""
    dataset = DownloadableDataset(
        description="A dataset behind an opaque link.",
        source="https://drive.google.com",
        url="https://drive.google.com/uc?export=download&id=abc",
        file="MyData.zspy",
    )
    assert dataset.download_url == "https://drive.google.com/uc?export=download&id=abc"


def test_download_verifies_checksum(tmp_path):
    """A real download, to prove pooch and checksum verification are wired up."""
    dataset = getattr(data, TINY_DATASET)()
    path = dataset.download(destination=tmp_path, progressbar=False, background=False)
    assert (tmp_path / dataset.file).exists()
    assert isinstance(path, DatasetPath)
    assert isinstance(path, Path)
    assert path.done is True  # nothing pending, so the handle needs no waiting
    assert path == tmp_path / dataset.file


def test_download_default_returns_path_handle(tmp_path):
    """The default download runs in the background and hands back a path handle
    that is a real ``Path`` and resolves to the downloaded file."""
    dataset = getattr(data, TINY_DATASET)()
    handle = dataset.download(destination=tmp_path, progressbar=False)
    assert isinstance(handle, DatasetPath)
    assert isinstance(handle, Path)
    # Using it as a path blocks until the bytes are there, then behaves normally.
    assert os.fspath(handle) == str(tmp_path / dataset.file)
    assert handle.is_file()
    assert (tmp_path / dataset.file).exists()
    assert handle.done


def test_download_handle_is_nonblocking_then_blocks_on_use(tmp_path, monkeypatch):
    """download() returns before the file exists; touching the path waits for it."""
    dataset = getattr(data, TINY_DATASET)()
    started = threading.Event()

    def slow_retrieve(
        destination=None, progressbar=True, chunk_size=4096, version=None, refresh=False
    ):
        started.set()
        time.sleep(0.4)
        target = tmp_path / dataset.file
        target.write_bytes(b"payload")
        return str(target)

    monkeypatch.setattr(dataset, "_retrieve", slow_retrieve)
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

    def slow_retrieve(
        destination=None, progressbar=True, chunk_size=4096, version=None, refresh=False
    ):
        started.set()
        time.sleep(0.4)
        target = tmp_path / dataset.file
        target.write_bytes(b"payload")
        return str(target)

    monkeypatch.setattr(dataset, "_retrieve", slow_retrieve)
    handle = dataset.download(destination=tmp_path, progressbar=False)
    assert started.wait(2)

    derived = handle.parent / handle.name
    assert derived is not handle
    assert derived.done is False
    assert Path(os.fspath(derived)).read_bytes() == b"payload"


def test_a_path_that_is_not_downloading_never_waits(tmp_path, monkeypatch):
    """Only the file being fetched is pending - its directory is not."""
    dataset = getattr(data, TINY_DATASET)()

    def slow_retrieve(
        destination=None, progressbar=True, chunk_size=4096, version=None, refresh=False
    ):
        time.sleep(0.3)
        target = tmp_path / dataset.file
        target.write_bytes(b"payload")
        return str(target)

    monkeypatch.setattr(dataset, "_retrieve", slow_retrieve)
    handle = dataset.download(destination=tmp_path, progressbar=False)
    assert handle.parent.done is True
    handle.wait()


def test_finished_downloads_leave_no_pending_entry(tmp_path):
    dataset = getattr(data, TINY_DATASET)()
    handle = dataset.download(destination=tmp_path, progressbar=False)
    handle.wait()
    key = _pending_key(handle)
    # the done-callback that clears the entry runs just after result() returns
    for _ in range(200):
        if key not in _PENDING:
            break
        time.sleep(0.01)
    assert key not in _PENDING


def test_generated_class_can_be_subclassed():
    base = getattr(data, TINY_DATASET)

    class Subclass(base):
        pass

    assert Subclass().file == base().file


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


def test_download_handle_propagates_errors(tmp_path):
    """A failed background download raises when the handle is consumed."""
    dataset = getattr(data, TINY_DATASET)(checksum="md5:" + "0" * 32)
    handle = dataset.download(destination=tmp_path, progressbar=False)
    with pytest.raises(Exception):
        os.fspath(handle)


def test_download_is_cached(tmp_path):
    """A second download of the same file must not refetch it."""
    dataset = getattr(data, TINY_DATASET)()
    first = dataset.download(destination=tmp_path, progressbar=False, background=False)
    mtime = (tmp_path / dataset.file).stat().st_mtime_ns
    second = dataset.download(destination=tmp_path, progressbar=False, background=False)
    assert first == second
    assert (tmp_path / dataset.file).stat().st_mtime_ns == mtime


def test_download_rejects_a_bad_checksum(tmp_path):
    """A wrong checksum must raise rather than hand back the file."""
    dataset = getattr(data, TINY_DATASET)(checksum="md5:" + "0" * 32)
    with pytest.raises(Exception):
        dataset.download(destination=tmp_path, progressbar=False, background=False)


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


def test_a_malformed_entry_warns_instead_of_vanishing(monkeypatch):
    """catalogue.datasets() used to swallow every exception, so a bad dataset
    just disappeared from the browser with nothing said."""
    broken = type(
        "BrokenDataset",
        (DownloadableDataset,),
        {"_spec": {"description": "d", "source": "s"}, "_metadata": None},  # no 'file'
    )
    monkeypatch.setattr(data, "BrokenDataset", broken, raising=False)
    monkeypatch.setattr(data, "__all__", [*data.__all__, "BrokenDataset"])

    with pytest.warns(UserWarning, match="BrokenDataset"):
        found = dict(catalogue.datasets())
    assert "BrokenDataset" not in found  # skipped, but not silently
