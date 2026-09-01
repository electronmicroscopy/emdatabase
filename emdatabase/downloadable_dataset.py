import atexit
import os
import sys
import threading
import warnings
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar, Protocol

import pooch

from emdatabase.metadata import DatasetMetadata


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
    (``ds.metadata.technique``). The four fields the download machinery itself
    needs are also reachable directly, as :attr:`source`, :attr:`file`,
    :attr:`checksum` and :attr:`size_bytes`.
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
    def checksum(self) -> str | None:
        return self.metadata.checksum

    @property
    def size_bytes(self) -> int | None:
        return self.metadata.size_bytes

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
    def _resolve_destination(destination: str | os.PathLike | None) -> Path:
        """Return the directory the dataset should live in."""
        if destination is None:
            from emdatabase import config

            return config.data_dir()
        return Path(destination)

    def download(
        self,
        destination: str | os.PathLike | None = None,
        progressbar: bool | Progress = True,
        chunk_size: int = 4096,
        background: bool = True,
    ) -> DatasetPath:
        """Download the dataset to the specified destination if not already present.

        By default, this will download to the defined emdata.data_dir directory. You can set
        a custom default download directory with emdata.data_dir = 'your/path/here' which will
        in turn set the corresponding environment variable.

        If the file already exists in the destination directory and the checksum matches,
        it will not be downloaded again and the existing file path will be returned.

        Parameters
        ----------
        destination : str or Path, optional
            The directory to download the dataset to. If None, uses the default emdata.data_dir
            directory, by default None.
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

        Returns
        -------
        DatasetPath
            The local path to the file, as a :class:`pathlib.Path` subclass that also
            reports download state. With ``background`` False it is already done.
        """
        if not background:
            return DatasetPath(self._retrieve(destination, progressbar, chunk_size))
        # Resolve where the file will end up: an existing copy in a store or in
        # the user's directory, otherwise the user's download location.
        if destination is not None:
            target = Path(destination) / self.file
        else:
            target = self.filepath() or self._resolve_destination(None) / self.file
        # In Jupyter (with the widget installed) a background download pops a
        # cancelable toast; the toast's monitor replaces the plain progress bar.
        monitor = finish = None
        if progressbar:
            try:
                from emdatabase.widget import _attach_toast

                monitor, finish = _attach_toast(type(self).__name__)
            except Exception:
                monitor = finish = None
        progress = monitor if monitor is not None else progressbar
        future = _get_executor().submit(self._retrieve, destination, progress, chunk_size)
        if finish is not None:
            future.add_done_callback(finish)
        return DatasetPath(target)._attach(future)

    def _retrieve(
        self,
        destination: str | os.PathLike | None = None,
        progressbar: bool | Progress = True,
        chunk_size: int = 4096,
    ) -> Path:
        """Fetch the file and return its local path (blocking).

        With no explicit destination, an existing copy in a store is used as-is
        (never re-downloaded); otherwise pooch downloads into the user's data
        directory.
        """
        if progressbar is True:
            try:
                import tqdm  # noqa: F401
            except ImportError:
                print("`tqdm` is not installed, progress bar will be disabled.")
                progressbar = False
            else:
                # Our own bar rather than pooch's; see _TqdmProgress.
                progressbar = _TqdmProgress(self.file)
        if destination is None:
            in_store = self._find_in_stores()
            if in_store is not None:
                return in_store
            destination = self._resolve_destination(None)
        else:
            destination = self._resolve_destination(destination)
        # Instantiate an Http downloader with a custom user agent
        headers = {"User-Agent": "emdatabase (https://github.com/electronmicroscopy/emdatabase)"}
        downloader = pooch.HTTPDownloader(
            progressbar=progressbar,  # pyright: ignore[reportArgumentType]
            chunk_size=chunk_size,
            headers=headers,
        )
        try:
            filepath = pooch.retrieve(
                url=self.source + "/" + self.file,
                known_hash=self.checksum,
                fname=self.file,
                path=destination,
                downloader=downloader,  # pyright: ignore[reportArgumentType]
            )
        finally:
            # pooch only closes the bar on the happy path, so a failed or
            # cancelled download would leave it hanging open.
            if isinstance(progressbar, _TqdmProgress):
                progressbar.close()
        return Path(filepath)

    def _find_in_stores(self) -> Path | None:
        """Path to an existing copy in one of the configured stores, or None."""
        from emdatabase import config

        for directory in config.stores().values():
            candidate = directory / self.file
            if candidate.exists():
                return candidate
        return None

    def filepaths(self) -> list[Path]:
        """Every copy of the dataset on disk, in search order.

        A dataset can be in more than one place at once - a copy in a store and
        your own download of the same file - and which one gets used is only a
        matter of the search order. :meth:`filepath` returns the winner; this
        returns all of them, so a caller can tell the difference between the
        one copy that is in a store and a store copy that you also have your
        own of.
        """
        from emdatabase import config

        return [d / self.file for d in config.data_search_dirs() if (d / self.file).exists()]

    def filepath(self) -> Path | None:
        """Return the local file path of the dataset if present.

        Looks in the configured stores first, then the user's data directory.
        Returns None if the dataset is not downloaded anywhere."""
        found = self.filepaths()
        return found[0] if found else None

    def delete(self, destination: str | None = None) -> bool:
        """Delete the downloaded file if it is present.

        Parameters
        ----------
        destination : str or Path, optional
            The directory the dataset was downloaded to. If None, uses the
            default emdata.data_dir directory, by default None.

        Returns
        -------
        bool
            True if a file was removed, False if there was nothing to delete.
        """
        path = self._resolve_destination(destination) / self.file
        if path.exists():
            path.unlink()
            return True
        return False
