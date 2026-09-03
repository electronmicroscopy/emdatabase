import atexit
import os
import sys
import threading
import urllib.request
import warnings
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

import pooch
import yaml

from emdatabase.config import LocationName
from emdatabase.metadata import DatasetMetadata, WeightsVersion, versioned_filename

USER_AGENT = "emdatabase (https://github.com/electronmicroscopy/emdatabase)"

# The index as it stands on main, which the weekly job keeps current: a weights
# family retrained since this release was cut has its new checksum there long
# before it has it in an installed copy.
UPSTREAM_INDEX = (
    "https://raw.githubusercontent.com/electronmicroscopy/emdatabase/main/emdatabase/index/"
)

# Parsed upstream documents by file name, and the families already warned
# about, both for the life of the process: a notebook loop asks about the same
# weights over and over, and neither the fetch nor the warning is worth
# repeating. A failed fetch caches as None, so an offline session pays the
# timeout once.
_UPSTREAM_CACHE: dict[str, dict[str, Any] | None] = {}
_UPSTREAM_LOCK = threading.Lock()
_WARNED_STALE: set[str] = set()


class StaleIndexWarning(UserWarning):
    """The file behind a weights family's ``latest`` link is not the one the
    index describes, so the shipped checksum is out of date."""


def _clear_upstream_cache() -> None:
    """Forget the fetched index documents and which families have warned."""
    with _UPSTREAM_LOCK:
        _UPSTREAM_CACHE.clear()
    _WARNED_STALE.clear()


def _upstream_document(origin_filename: str) -> dict[str, Any] | None:
    """The parsed index file of that name from main, or None if it is not had.

    Every failure - no network, a 404, a proxy serving something that is not
    YAML - is the same answer: nothing to compare against. An update check is
    not worth an exception in the middle of a download.
    """
    with _UPSTREAM_LOCK:
        if origin_filename in _UPSTREAM_CACHE:
            return _UPSTREAM_CACHE[origin_filename]
    document: dict[str, Any] | None = None
    try:
        request = urllib.request.Request(
            UPSTREAM_INDEX + origin_filename, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            parsed = yaml.safe_load(response.read())
        if isinstance(parsed, dict):
            document = parsed
    except Exception:
        document = None
    with _UPSTREAM_LOCK:
        _UPSTREAM_CACHE[origin_filename] = document
    return document


def upstream_metadata(name: str, origin_filename: str) -> DatasetMetadata | None:
    """The entry named ``name`` in ``origin_filename`` on main, or None.

    ``origin_filename`` is the index file the entry ships in, so a file holding
    several entries is fetched once and read for whichever one is asked about.
    """
    document = _upstream_document(origin_filename)
    if document is None:
        return None
    spec = document.get(name)
    if spec is None:
        # The class name is the YAML key with its spaces and hyphens replaced.
        spec = next(
            (v for k, v in document.items() if str(k).replace(" ", "_").replace("-", "_") == name),
            None,
        )
    if not isinstance(spec, Mapping):
        return None
    try:
        return DatasetMetadata.from_spec(spec, origin_filename)
    except Exception:
        return None


@dataclass(frozen=True)
class _Resolved:
    """What one call to :meth:`DownloadableDataset.download` fetches.

    ``pinned`` is False only for a weights family's ``latest``, where the
    checksum describes what the link served when the index was written rather
    than what it has to serve now.
    """

    url: str
    checksum: str | None
    size_bytes: int | None
    file: str
    pinned: bool


class Progress(Protocol):
    """What pooch drives while streaming a file, and what the widgets provide."""

    @property
    def total(self) -> int: ...

    @total.setter
    def total(self, value: int) -> None: ...

    def update(self, n: int) -> None: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


# A single, lazily-created thread pool shared by every dataset. Background
# downloads run here so that a notebook cell returns immediately instead of
# blocking on the network. It is created on first use so that simply importing
# the package costs nothing.
_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Return the shared download thread pool, creating it on first use."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=4,
                    thread_name_prefix="emdatabase_download",
                )
                atexit.register(_shutdown_executor)
    return _executor


def _shutdown_executor() -> None:
    """Drop queued downloads on the way out of the interpreter.

    The pool's threads are non-daemon, so Python joins them at exit: queue up
    several large datasets and the process hangs on the last one long after you
    asked it to stop, with Ctrl-C going to the main thread and being ignored.
    Cancelling clears everything not yet started.

    A transfer already streaming still runs to completion - there is no way to
    interrupt pooch mid-read from here - so this shortens the wait rather than
    removing it. The widget's toast has a cancel button for that case.
    """
    global _executor
    executor, _executor = _executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


# Subclass the *concrete* Path for this OS (WindowsPath / PosixPath) so that
# instances are real ``pathlib.Path`` objects. This matters: consumers such as
# ``hyperspy.load`` do ``isinstance(arg, Path)`` and reject anything else, so a
# plain ``Future`` (or a bare ``os.PathLike``) would not work as a drop-in for
# the download path — but a Path subclass does.
_ConcretePath = type(Path())

# Downloads in flight, keyed by the destination path. Keeping this off the
# instance is what makes a derived path behave: pathlib builds a brand new
# object for ``handle.parent / handle.name``, and an instance attribute would
# not survive that, so the copy would report itself finished and never wait.
_PENDING: dict[str, "Future[Path]"] = {}
_PENDING_LOCK = threading.Lock()


def _pending_key(path: object) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _release_pending(key: str, future: "Future[Path]") -> None:
    with _PENDING_LOCK:
        if _PENDING.get(key) is future:
            del _PENDING[key]


class DatasetPath(_ConcretePath):
    """The local path to a dataset, which may still be downloading.

    It is a genuine :class:`pathlib.Path` pointing at the file's final location
    (known before the download starts), so it can be passed anywhere a path is
    expected — ``hs.load(dataset.download())`` just works. The moment something
    actually touches the file (``open``, ``is_file``, ``os.fspath`` — the hooks
    every file reader ultimately goes through) it blocks until the download has
    finished, re-raising any error that occurred.

    ``done`` reports status without blocking; ``result()``/``wait()`` block
    until the file is ready. A path to a file that is already on disk is simply
    one that is already done, so :meth:`DownloadableDataset.download` returns
    this type whether or not it downloaded anything.

    Any path pointing at the same file waits, however it was built. ``str()``
    and ``Path()`` are the exceptions: they hand back a plain value with no
    download attached, so ``hs.load(str(handle))`` will not block.
    """

    @property
    def _future(self) -> "Future[Path] | None":
        return _PENDING.get(_pending_key(self))

    def _attach(self, future: "Future[Path]") -> "DatasetPath":
        key = _pending_key(self)
        with _PENDING_LOCK:
            _PENDING[key] = future
        future.add_done_callback(lambda finished: _release_pending(key, finished))
        return self

    def __fspath__(self) -> str:
        # is_file()/exists()/stat()/open() and every os.fspath() consumer route
        # through here, so blocking here makes all of them wait for the bytes.
        future = self._future
        if future is not None:
            future.result()  # blocks; re-raises a failed download
        return str(self)

    def result(self, timeout: float | None = None) -> Path:
        """Block until the download finishes and return the file path."""
        future = self._future
        if future is not None:
            future.result(timeout)
        return Path(str(self))

    @property
    def done(self) -> bool:
        """Whether the download has finished. Never blocks."""
        future = self._future
        return future.done() if future is not None else True

    def wait(self, timeout: float | None = None) -> "DatasetPath":
        """Block until the download finishes and return self (for chaining)."""
        self.result(timeout)
        return self

    def __repr__(self) -> str:  # never block just to display the object
        state = "done" if self.done else "downloading"
        return f"<DatasetPath {str(self)!r} [{state}]>"


class _TqdmProgress:
    """A tqdm bar for a pooch download, created only once bytes start arriving.

    Two reasons not to let pooch build its own. It passes ``ncols=79``, meaning
    79 *terminal columns*, but tqdm's notebook backend reads ``ncols`` as a
    pixel width and sets ``layout.width = "79px"`` - a bar squashed to 79 pixels
    with its own horizontal scrollbar. And ``pooch.retrieve`` skips the
    downloader entirely for a file that is already cached, so building the bar
    up front would flash an empty one on every cached call; pooch assigns
    ``total`` exactly once, before streaming, which is the moment there is
    something worth showing.
    """

    def __init__(self, desc: str = "") -> None:
        self._desc = desc
        self._bar: Any = None  # a tqdm.auto bar; which backend depends on the host
        self._total = 0

    @property
    def total(self) -> int:
        return self._total

    @total.setter
    def total(self, value: int) -> None:
        from tqdm.auto import tqdm

        self._total = int(value or 0)
        if self._bar is None:
            self._bar = tqdm(
                total=self._total,
                desc=self._desc,
                unit="B",
                unit_scale=True,
                # Windows terminals do not always have the box-drawing glyphs.
                ascii=sys.platform == "win32",
                leave=True,
            )
        else:
            self._bar.reset(total=self._total)

    def update(self, n: int) -> None:
        if self._bar is not None:
            self._bar.update(n)

    def reset(self) -> None:
        if self._bar is not None:
            self._bar.reset(total=self._total)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None


class DownloadableDataset:
    """A downloadable dataset, described by the YAML entry in :attr:`_spec`.

    The generated subclasses in :mod:`emdatabase.data` carry their entry as
    ``_spec``; keyword arguments override it for a single instance.

    Everything the YAML declares is on :attr:`metadata`
    (``ds.metadata.technique``). The fields the download machinery itself
    needs are also reachable directly, as :attr:`source`, :attr:`file`,
    :attr:`url`, :attr:`checksum` and :attr:`size_bytes`; the link that is
    actually fetched is :attr:`download_url`.

    A ``kind: weights`` entry is a family rather than a single file:
    :attr:`versions` lists the dated snapshots it can be pinned to, and the
    accessors above describe its ``latest``. Downloading that ``latest`` also
    asks the index on the project's ``main`` branch whether newer weights have
    been published since this release, warning if they have and fetching them
    with ``download(refresh=True)``.
    """

    _spec: ClassVar[dict[str, Any]] = {}
    _origin: ClassVar[Path | None] = None
    # Built when the class is, so a malformed YAML fails the import that reads
    # it rather than making the dataset quietly disappear from the catalogue.
    _metadata: ClassVar[DatasetMetadata | None] = None

    def __init__(self, **overrides: Any):
        if self._metadata is not None and not overrides:
            self.metadata = self._metadata
        else:
            self.metadata = DatasetMetadata.from_spec({**self._spec, **overrides}, self._origin)

    @property
    def source(self) -> str:
        return self.metadata.source

    @property
    def file(self) -> str:
        return self.metadata.file

    @property
    def url(self) -> str | None:
        return self.metadata.url

    def _resolve(self, version: str | None = None) -> _Resolved:
        """The link, checksum and local name for one version of this entry.

        A dataset is a single pinned file and takes no version. A weights entry
        is a family: with no version it is the ``latest`` link, which is not
        pinned, and with one it is that dated snapshot, which is.
        """
        md = self.metadata
        if md.kind != "weights":
            if version is not None:
                raise ValueError(f"{type(self).__name__} is a dataset and has no versions")
            return _Resolved(
                url=md.url or f"{md.source}/{md.file}",
                checksum=md.checksum,
                size_bytes=md.size_bytes,
                file=md.file,
                pinned=True,
            )
        if version is None:
            if md.latest is None:
                raise ValueError(f"{type(self).__name__} is a weights entry with no 'latest'")
            return _Resolved(
                url=md.latest.url,
                checksum=md.latest.checksum,
                size_bytes=md.latest.size_bytes,
                file=md.file,
                pinned=False,
            )
        pin = md.versions.get(version)
        if pin is None:
            raise ValueError(
                f"{type(self).__name__} has no version {version!r}; "
                f"available: {', '.join(self.versions) or 'none'}"
            )
        return _Resolved(
            url=pin.url,
            checksum=pin.checksum,
            size_bytes=pin.size_bytes,
            file=versioned_filename(md.file, version),
            pinned=True,
        )

    @property
    def download_url(self) -> str:
        """The link the file is fetched from, ``latest`` for a weights family.

        ``source`` is where the file comes from and ``file`` is what it is
        called locally, which for most hosts is also the last segment of the
        link. Where it is not - a Google Drive link, or anything else with a
        query string - the entry gives the whole link as ``url`` instead, and a
        weights entry gives one link per version.
        """
        return self._resolve(None).url

    @property
    def checksum(self) -> str | None:
        return self._resolve(None).checksum

    @property
    def size_bytes(self) -> int | None:
        return self._resolve(None).size_bytes

    @property
    def versions(self) -> tuple[str, ...]:
        """The dated versions of a weights family, newest first.

        Empty for a dataset, which is one pinned file and has no versions.
        """
        return tuple(sorted(self.metadata.versions, reverse=True))

    @property
    def latest_checksum(self) -> str | None:
        """What the ``latest`` link served when the index was written."""
        return self._resolve(None).checksum

    def filename(self, version: str | None = None) -> str:
        """The name the file is saved under locally.

        A dated version of a weights family carries the date - ``w.pt`` becomes
        ``w_260902.pt`` - so that it sits next to ``latest`` rather than
        replacing it.
        """
        return self._resolve(version).file

    @property
    def size(self) -> str:
        """:attr:`size_bytes` formatted for display, or ``""`` if unknown."""
        return self.metadata.size

    def __repr__(self):
        # __class__ rather than its __name__ nested one set of angle brackets
        # inside another, which a list of results made unreadable.
        headline = " · ".join(p for p in (self.file, self.metadata.technique, self.size) if p)
        return f"<{type(self).__name__} {headline}>"

    def _repr_mimebundle_(self, **kwargs):
        """Rich display in Jupyter: an interactive card with download/metadata.

        Falls back to the plain repr if anywidget is not installed.
        """
        try:
            from emdatabase.widget import card

            widget = card(self)
        except ImportError:
            return {"text/plain": repr(self)}  # anywidget not installed
        except Exception as error:
            # Still fall back - a repr that raises is worse than a plain one -
            # but say so, rather than making a widget bug look like a missing
            # optional dependency.
            warnings.warn(f"falling back to the plain repr: {error}", stacklevel=2)
            return {"text/plain": repr(self)}
        return widget._repr_mimebundle_(**kwargs)

    @staticmethod
    def _resolve_destination(destination: Path | LocationName | None) -> Path:
        """Return the directory the dataset should live in.

        A string that is the name of a configured location resolves to that
        location's directory; anything else is a path, and None is the personal
        directory downloads go to.
        """
        from emdatabase import config

        resolved = config.resolve_destination(destination)
        return config.data_dir() if resolved is None else resolved

    def download(
        self,
        destination: Path | LocationName | None = None,
        progressbar: bool | Progress = True,
        chunk_size: int = 4096,
        background: bool = True,
        version: str | None = None,
        refresh: bool = False,
    ) -> DatasetPath:
        """Return a verified local path to the file, downloading it if needed.

        With no ``destination`` the search order from :func:`emdatabase.locations`
        is consulted first: a copy in any shared location, or in the personal
        one, is returned without downloading. Only if the file is nowhere is it
        fetched into the personal location.

        With a ``destination`` the file is written there, whether or not a copy
        exists elsewhere. Naming a shared location is how it is seeded; naming
        ``"personal"`` forces your own copy even when the share has one. The
        file is left with whatever permissions it was written with; making it
        group-readable is the caller's job.

        Parameters
        ----------
        destination : Path or LocationName, optional
            Where to write the file. A string naming a location configured with
            :func:`emdatabase.add_location` (including ``"personal"``) resolves
            to that location's directory; any other string or a ``Path`` is a
            directory path. ``None`` (the default) resolves through the search
            order as described above.
        progressbar : bool, optional
            Whether to show a progress bar during download, by default True.
        chunk_size : int, optional
            The chunk size to use for downloading the file, by default 4096. Increasing this value will sometimes
            increase download speed at the cost of higher memory usage.
        background : bool, optional
            If True (the default), the download runs on a background thread and this
            returns immediately so a Jupyter cell stays responsive. The returned
            :class:`DatasetPath` is a real path pointing at the file's final
            location, so you can hand it straight to a loader
            (``hs.load(dataset.download())``): it blocks only at the point the file
            is actually opened. Use ``.done`` to poll and ``.result()`` to wait
            explicitly. If False, the download blocks until the file is there.
        version : str, optional
            For a ``kind: weights`` entry, the dated version to fetch, e.g.
            ``"260902"`` - see :attr:`versions`. It is saved under its own name
            (``w_260902.pt``) and is pinned: a download that does not match the
            checksum in the index fails. ``None`` (the default) fetches the
            ``latest`` link, which serves whatever the current file is; if
            those bytes are not the ones the index describes the download still
            succeeds and warns with :class:`StaleIndexWarning`. A copy of
            ``latest`` already on disk is handed back as it is, so refreshing a
            stale one means ``refresh=True`` (or :meth:`delete` and then
            ``download`` again). There is no checksum to fail on for ``latest``,
            so a host that answers with an HTML page instead of the file -
            Google Drive's virus-scan interstitial for a large file - is saved
            and warned about rather than refused. A dataset has no versions and
            passing one is an error.
        refresh : bool, optional
            Fetch the file again rather than using the copy on disk. For a
            weights family's ``latest`` this also reads the family's entry from
            the index on the project's ``main`` branch, which is kept current
            between releases, and downloads from there - pinned to that entry's
            checksum - when it names newer weights than the installed index
            knows about. Otherwise the shipped ``latest`` link is re-fetched.
            The file is always written to the resolved destination, never to a
            shared location. ``False`` (the default) still asks the index on
            ``main`` about a weights family's ``latest`` and warns with
            :class:`StaleIndexWarning`, once per family, if newer weights are
            published there; the ``check_updates`` config key turns that check
            off.

        Returns
        -------
        DatasetPath
            The local path to the file, as a :class:`pathlib.Path` subclass that also
            reports download state. With ``background`` False it is already done.
        """
        if not background:
            return DatasetPath(
                self._retrieve(destination, progressbar, chunk_size, version, refresh)
            )
        # Resolve where the file will end up: an existing copy in a shared
        # location or in the personal one, otherwise the personal one.
        name = self.filename(version)
        if destination is not None:
            target = self._resolve_destination(destination) / name
        elif refresh:
            target = self._resolve_destination(None) / name
        else:
            target = self.filepath(version) or self._resolve_destination(None) / name
        # In Jupyter (with the widget installed) a background download pops a
        # cancelable toast; the toast's monitor replaces the plain progress bar.
        monitor = finish = None
        if progressbar:
            try:
                from emdatabase.widget import _attach_toast

                label = type(self).__name__ + (f"@{version}" if version else "")
                monitor, finish = _attach_toast(label)
            except Exception:
                monitor = finish = None
        progress = monitor if monitor is not None else progressbar
        future = _get_executor().submit(
            self._retrieve, destination, progress, chunk_size, version, refresh
        )
        if finish is not None:
            future.add_done_callback(finish)
        return DatasetPath(target)._attach(future)

    def _retrieve(
        self,
        destination: Path | LocationName | None = None,
        progressbar: bool | Progress = True,
        chunk_size: int = 4096,
        version: str | None = None,
        refresh: bool = False,
    ) -> Path:
        """Fetch the file and return its local path (blocking).

        With no explicit destination, an existing copy in a shared location is
        used as-is (never re-downloaded); otherwise pooch downloads into the
        personal directory. ``refresh`` skips both: the file is re-fetched into
        the resolved destination, from the newer link on ``main`` if there is
        one.
        """
        resolved = self._resolve(version)
        newer = self._check_upstream(version, refresh)
        if progressbar is True:
            try:
                import tqdm  # noqa: F401
            except ImportError:
                print("`tqdm` is not installed, progress bar will be disabled.")
                progressbar = False
            else:
                # Our own bar rather than pooch's; see _TqdmProgress.
                progressbar = _TqdmProgress(resolved.file)
        if destination is None:
            # A refresh is about replacing your own copy, so it never reads and
            # never writes a shared location.
            shared = None if refresh else self._find_in_shared_locations(version)
            if shared is not None:
                return shared
            destination = self._resolve_destination(None)
        else:
            destination = self._resolve_destination(destination)
        # Instantiate an Http downloader with a custom user agent
        headers = {"User-Agent": USER_AGENT}
        downloader = pooch.HTTPDownloader(
            progressbar=progressbar,  # pyright: ignore[reportArgumentType]
            chunk_size=chunk_size,
            headers=headers,
        )
        try:
            if refresh:
                # pooch keeps a file whose hash it was not given anything to
                # check against, so the copy has to go before it will re-fetch.
                (Path(destination) / resolved.file).unlink(missing_ok=True)
            if newer is not None:
                filepath = pooch.retrieve(
                    url=newer.url,
                    known_hash=newer.checksum,
                    fname=resolved.file,
                    path=destination,
                    downloader=downloader,  # pyright: ignore[reportArgumentType]
                )
            elif resolved.pinned:
                filepath = pooch.retrieve(
                    url=resolved.url,
                    known_hash=resolved.checksum,
                    fname=resolved.file,
                    path=destination,
                    downloader=downloader,  # pyright: ignore[reportArgumentType]
                )
            else:
                filepath = self._retrieve_latest(resolved, Path(destination), downloader)
        finally:
            # pooch only closes the bar on the happy path, so a failed or
            # cancelled download would leave it hanging open.
            if isinstance(progressbar, _TqdmProgress):
                progressbar.close()
        return Path(filepath)

    def _check_upstream(self, version: str | None, refresh: bool) -> WeightsVersion | None:
        """Ask the index on ``main`` whether this family's ``latest`` has moved.

        The weekly job keeps that index current, so it knows about weights
        retrained since this release was cut. Returns the newer ``latest`` to
        download from, which only happens for ``refresh``; otherwise a family
        that has moved on warns once and the shipped link is used as it is.

        Only a weights family's ``latest`` asks: a dataset and a dated version
        are pinned, and there is nothing for a newer index to tell them.
        """
        from emdatabase import config

        if self.metadata.kind != "weights" or version is not None or self._origin is None:
            return None
        if not refresh and not config.get("check_updates", True):
            return None
        upstream = upstream_metadata(type(self).__name__, self._origin.name)
        latest = upstream.latest if upstream is not None else None
        if upstream is None or latest is None or latest.checksum == self._resolve(None).checksum:
            return None
        if refresh:
            return latest
        key = f"{self._origin.name}:{type(self).__name__}"
        if key not in _WARNED_STALE:
            _WARNED_STALE.add(key)
            versions = ", ".join(sorted(upstream.versions, reverse=True))
            warnings.warn(
                f"{type(self).__name__}: newer weights are in the emdatabase index "
                f"({latest.checksum}" + (f", versions {versions}" if versions else "") + "); "
                "upgrade emdatabase, or download(refresh=True) to fetch them now.",
                StaleIndexWarning,
                stacklevel=2,
            )
        return None

    def _retrieve_latest(self, resolved: _Resolved, destination: Path, downloader: Any) -> str:
        """Fetch a weights family's ``latest`` link, warning on a new checksum.

        The link serves whatever the newest file is, so the checksum in the
        index goes stale the moment the model is retrained. Verifying it would
        refuse the download of a file that is not wrong, only newer, so the
        file is fetched unverified and hashed afterwards.

        A copy already on disk is used as it is: its bytes cannot be told apart
        from a newer or an older publication of the same link, and re-fetching
        would need the network for a file that is already there.
        """
        target = destination / resolved.file
        already_there = target.exists()
        filepath = pooch.retrieve(
            url=resolved.url,
            known_hash=None,
            fname=resolved.file,
            path=destination,
            downloader=downloader,
        )
        if already_there or not resolved.checksum:
            return filepath
        digest = f"md5:{pooch.file_hash(filepath, 'md5')}"
        if digest != resolved.checksum:
            pinned = (
                f'download(version="{self.versions[0]}")' if self.versions else "an older copy"
            )
            warnings.warn(
                f"{type(self).__name__}: the latest weights are {digest}, but the index "
                f"describes {resolved.checksum}. The file was kept - it is what the link "
                f"serves now - but it is not the one this version of emdatabase was built "
                f"against; upgrade emdatabase, or use {pinned} for the state it knows.",
                StaleIndexWarning,
                stacklevel=2,
            )
        return filepath

    def _find_in_shared_locations(self, version: str | None = None) -> Path | None:
        """Path to an existing copy in a configured shared location, or None."""
        from emdatabase import config

        name = self.filename(version)
        for location in config.locations():
            if location.kind == "personal":
                continue
            candidate = location.path / name
            if candidate.exists():
                return candidate
        return None

    def filepaths(self, version: str | None = None) -> list[Path]:
        """Every copy of the dataset on disk, in search order.

        A dataset can be in more than one place at once - a copy in a shared
        location and your own download of the same file - and which one gets
        used is only a matter of the search order. :meth:`filepath` returns the
        winner; this returns all of them, so a caller can tell the difference
        between the one copy that is shared and a shared copy that you also
        have your own of.

        ``version`` asks about one dated version of a weights family; with no
        version it is the ``latest`` file, which is a different name on disk.
        """
        from emdatabase import config

        name = self.filename(version)
        return [d / name for d in config.data_search_dirs() if (d / name).exists()]

    def filepath(self, version: str | None = None) -> Path | None:
        """Return the local file path of the dataset if present.

        Looks in the configured shared locations first, then the personal
        directory. Returns None if the dataset is not downloaded anywhere.

        With no ``version`` this asks whether ``latest`` is on disk, so a
        weights family with only a dated copy downloaded answers None: handing
        back pinned old bytes as the latest weights is exactly the substitution
        the checksums are there to prevent."""
        found = self.filepaths(version)
        return found[0] if found else None

    def delete(
        self, destination: Path | LocationName | None = None, version: str | None = None
    ) -> bool:
        """Delete the downloaded file if it is present.

        Parameters
        ----------
        destination : str or Path, optional
            The directory the dataset was downloaded to. A string naming a
            location configured with :func:`emdatabase.add_location` resolves to
            that location's directory; anything else is a path. If None, uses
            the personal directory - never a shared one - by default None.
        version : str, optional
            Which dated version of a weights family to remove. None (the
            default) is the ``latest`` file, which is also how a stale copy of
            it is refreshed: delete it, then download again.

        Returns
        -------
        bool
            True if a file was removed, False if there was nothing to delete.
        """
        path = self._resolve_destination(destination) / self.filename(version)
        if path.exists():
            path.unlink()
            return True
        return False
