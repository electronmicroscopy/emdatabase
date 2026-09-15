"""An anywidget dataset browser for Jupyter: ``emdatabase.browse()``.

Renders every dataset grouped by technique, marks which are already downloaded
(○ / ●), shows metadata on hover, and downloads on click. Each download runs on
the shared background thread pool (so the kernel stays responsive) and reports
progress, with a cancel button, inside the widget through pooch's progress-bar
hook.

anywidget is an optional dependency; :func:`browse` raises a helpful error if it
is not installed. Importing this module never imports anywidget at module load,
so ``import emdatabase`` stays cheap and dependency-light.
"""

from __future__ import annotations

import functools
import itertools
import logging
import threading
import time
import warnings
from pathlib import Path

import pooch

from emdatabase import catalogue as _catalogue
from emdatabase.downloadable_dataset import _get_executor

_STATIC = Path(__file__).parent / "static"

# How often (seconds) a running download pushes a progress update to the
# frontend, so a fast connection does not flood the widget comm.
_PROGRESS_INTERVAL = 0.15

_pooch_quieted = False
_colab_enabled = False


def _enable_colab_widgets():
    """On Google Colab, third-party (anywidget) widgets render only once the
    custom widget manager is enabled - do it once, automatically. No-op anywhere
    else, so widgets work out of the box on Colab and Jupyter alike.
    """
    global _colab_enabled
    if _colab_enabled:
        return
    try:
        from google.colab import output  # pyright: ignore[reportMissingImports]

        output.enable_custom_widget_manager()
    except Exception:
        pass
    finally:
        _colab_enabled = True


def _prepare_frontend():
    """Everything that should happen before a widget renders.

    pooch's "Downloading data from ..." INFO logs render as red output in
    Jupyter, and the widget or the progress bar shows the same thing, so they are
    silenced - once, so a level set afterwards is left alone. Warnings and
    errors still come through.
    """
    global _pooch_quieted
    if not _pooch_quieted:
        pooch.get_logger().setLevel(logging.WARNING)
        _pooch_quieted = True
    _enable_colab_widgets()


def _label(name, version=None):
    """What a download is called in the widget: ``Name`` or ``Name@260902``.

    The frontend splits on the ``@`` to find the entry a running download
    belongs to, so a dated download still marks its row.
    """
    return f"{name}@{version}" if version else name


def _frontend(name):
    """A widget's ``_esm``: ``common.js``, which both widgets share, then its own file.

    anywidget loads ``_esm`` as a single module and there is no bundler, so the
    shared code is put in front rather than imported.
    """
    return (_STATIC / "common.js").read_text("utf-8") + (_STATIC / name).read_text("utf-8")


class DownloadCancelled(Exception):
    """Raised inside pooch's stream when the user cancels a download.

    It is not a ``ValueError``/requests error, so pooch's retry loop does not
    re-attempt a cancelled download; pooch streams to a temp file and deletes it
    on error, so no partial file is left in the cache.
    """


class _WidgetProgress:
    """A pooch-compatible progress object that pushes to the widget.

    pooch drives it per file: it assigns ``total`` before streaming, calls
    ``update(n)`` per chunk, then ``reset()`` + ``update(total)`` + ``close()``
    at the end. Raising from ``update`` when the cancel flag is set aborts the
    stream. Emits are throttled to :data:`_PROGRESS_INTERVAL`.
    """

    def __init__(self, widget, token, label, cancel):
        self._widget = widget
        self.token = token
        self.label = label
        self._cancel = cancel
        self._total = 0
        self._done = 0
        self._last_emit = 0.0
        self._closing = False

    # pooch assigns `progress.total = content_length` before streaming a file.
    @property
    def total(self):
        return self._total

    @total.setter
    def total(self, value):
        self._total = int(value or 0)
        self._done = 0
        self._closing = False
        self._emit(force=True)

    def update(self, n):
        if self._cancel.is_set():
            raise DownloadCancelled(self.token)
        self._done += int(n)
        if self._total:
            self._done = min(self._done, self._total)
        self._emit(force=self._closing)

    def reset(self):
        # pooch's end-of-file sequence is reset() -> update(total) -> close();
        # mark it so the final update emits un-throttled (bar reaches 100%).
        self._done = 0
        self._closing = True

    def close(self):
        self._closing = False

    def _emit(self, force=False):
        now = time.monotonic()
        if not force and (now - self._last_emit) < _PROGRESS_INTERVAL:
            return
        self._last_emit = now
        self._widget._set_progress(self.token, self.label, self._done, self._total)


def _delete_file(dataset, name, version):
    """Delete a dataset's downloaded file, warning rather than raising if it cannot be."""
    try:
        dataset.delete(version=version)
    except OSError as error:  # read-only dir, permissions, a vanished file
        warnings.warn(f"could not delete {name}: {error}", stacklevel=3)


@functools.cache
def _make_downloads_class():
    """Build the base of the browser and the card, importing anywidget lazily.

    Both draw one toast per running download from ``downloads``, which maps a
    per-download token to ``{label, done, total}`` while it runs and to
    ``{label, error}`` once it has failed, and send the download, delete,
    refresh, cancel and dismiss commands.
    """
    import anywidget
    import traitlets

    class DownloadsWidget(anywidget.AnyWidget):
        _css = _STATIC / "browser.css"

        downloads = traitlets.Dict().tag(sync=True)
        # Commands from the frontend arrive as a synced dict (more reliable than
        # custom comm messages): the frontend bumps a nonce so repeats register.
        _command = traitlets.Dict().tag(sync=True)

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._lock = threading.RLock()
            self._cancels: dict[str, threading.Event] = {}
            self._labels: dict[str, str] = {}
            self._counter = itertools.count()
            self.observe(self._on_command, names="_command")

        # NB: do NOT name a method `_handle_msg` - that is ipywidgets' own
        # internal comm callback, and overriding it breaks all comm handling
        # (including trait sync). Commands arrive via the `_command` trait.
        def _on_command(self, change):
            command = change["new"]
            action = command.get("action")
            name = str(command.get("name", ""))
            version = command.get("version") or None
            token = str(command.get("token", ""))
            if action == "download":
                self._start_download(name, version)
            elif action == "delete":
                self._delete(name, version)
            elif action == "refresh":
                self.refresh()
            elif action == "cancel":
                self._cancel(token)
            elif action == "dismiss":
                self._clear_progress(token)

        def refresh(self):
            """Re-check which files are on disk."""
            raise NotImplementedError

        def _resolve(self, name):
            return _catalogue.resolve(name)

        def _delete(self, name, version=None):
            """Delete a dataset's downloaded file and refresh its status."""
            ds = self._resolve(name)
            if ds is not None:
                _delete_file(ds, name, version)
                self.refresh()

        def _start_download(self, name, version=None):
            """Kick off a background download for ``name`` and show a toast."""
            ds = self._resolve(name)
            if ds is None:
                return None
            monitor, token = self.begin(_label(name, version))
            future = _get_executor().submit(
                ds.download, progressbar=monitor, background=False, version=version
            )
            future.add_done_callback(lambda f, tk=token: self.finish(tk, f))
            return future

        def begin(self, label):
            """Register a new download; return its (monitor, token)."""
            token = f"{label}-{next(self._counter)}"
            cancel = threading.Event()
            with self._lock:
                self._cancels[token] = cancel
                self._labels[token] = label
            # Show the toast immediately - indeterminate until the first bytes,
            # and it also covers the cached case where no bytes ever flow.
            self._set_progress(token, label, 0, 0)
            return _WidgetProgress(self, token, label, cancel), token

        def finish(self, token, future):
            with self._lock:
                self._cancels.pop(token, None)
                label = self._labels.pop(token, token)
            error = future.exception()
            if error is not None and not isinstance(error, DownloadCancelled):
                self._set_error(token, label, str(error))
            else:
                self._clear_progress(token)
            self.refresh()

        def _cancel(self, token):
            with self._lock:
                event = self._cancels.get(token)
            if event is not None:
                event.set()

        # -- progress trait plumbing (called from worker threads) ----------
        # ipykernel routes widget comm messages through a dedicated iopub
        # thread, so assigning these traits from a pool thread is safe.
        def _set_progress(self, token, label, done, total):
            with self._lock:
                downloads = dict(self.downloads)
                downloads[token] = {"label": label, "done": int(done), "total": int(total)}
                self.downloads = downloads

        def _clear_progress(self, token):
            with self._lock:
                downloads = dict(self.downloads)
                if downloads.pop(token, None) is not None:
                    self.downloads = downloads

        def _set_error(self, token, label, message):
            with self._lock:
                downloads = dict(self.downloads)
                downloads[token] = {"label": label, "error": message}
                self.downloads = downloads

    return DownloadsWidget


@functools.cache
def _make_browser_class():
    """Build the ``DatasetBrowser`` class, importing anywidget lazily."""
    import traitlets

    class DatasetBrowser(_make_downloads_class()):
        """Interactive, hoverable list of the emdatabase datasets."""

        _esm = _frontend("browser.js")

        groups = traitlets.List().tag(sync=True)
        data_dir = traitlets.Unicode().tag(sync=True)
        n_downloaded = traitlets.Int().tag(sync=True)
        n_total = traitlets.Int().tag(sync=True)

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.refresh()

        def refresh(self):
            """Rebuild the catalogue - re-checks which files are on disk."""
            cat = _catalogue.catalogue()
            self.data_dir = cat["data_dir"]
            self.groups = cat["groups"]
            self.n_downloaded = cat["n_downloaded"]
            self.n_total = cat["n_total"]

    return DatasetBrowser


@functools.cache
def _make_card_class():
    """Build the ``DatasetCard`` class (one dataset), importing anywidget lazily."""
    import traitlets

    class DatasetCard(_make_downloads_class()):
        """An interactive card for a single dataset - what ``display(ds)`` shows."""

        _esm = _frontend("card.js")

        info = traitlets.Dict().tag(sync=True)  # the catalogue entry() dict

        def __init__(self, dataset, **kwargs):
            super().__init__(**kwargs)
            self._dataset = dataset
            self.refresh()

        def refresh(self):
            self.info = _catalogue.entry(type(self._dataset).__name__, self._dataset)

        def _resolve(self, name):
            return self._dataset

    return DatasetCard


def card(dataset):
    """Return an interactive card widget for a single dataset (Jupyter).

    This backs ``display(dataset)`` / a dataset being the last line in a cell.
    Requires anywidget (``pip install emdatabase[widget]``).
    """
    _prepare_frontend()
    try:
        cls = _make_card_class()
    except ImportError as error:
        raise ImportError(
            "Displaying a dataset needs anywidget. Install it with "
            "`pip install emdatabase[widget]` (or `pip install anywidget`)."
        ) from error
    return cls(dataset)


def browse(**kwargs):
    """Return an interactive dataset browser widget for Jupyter.

    Requires anywidget (``pip install emdatabase[widget]``). The widget lists
    every dataset grouped by technique, shows which are downloaded, reveals full
    metadata on hover, and downloads on click with a live progress toast.
    """
    _prepare_frontend()
    try:
        cls = _make_browser_class()
    except ImportError as error:
        raise ImportError(
            "emdatabase.browse() needs anywidget. Install it with "
            "`pip install emdatabase[widget]` (or `pip install anywidget`)."
        ) from error
    return cls(**kwargs)


def _in_notebook():
    """True in a notebook frontend that can render widgets (Jupyter, Colab,
    VS Code, ...), False in plain Python or a terminal IPython."""
    try:
        from IPython.core.getipython import get_ipython

        ip = get_ipython()
        if ip is None:
            return False
        # ZMQInteractiveShell = Jupyter; "Shell" = Colab; exclude only the
        # terminal shell, which cannot render widgets.
        return ip.__class__.__name__ != "TerminalInteractiveShell"
    except Exception:
        return False
