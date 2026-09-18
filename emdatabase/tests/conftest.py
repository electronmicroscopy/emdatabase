"""Shared test fixtures.

Every test runs against an isolated, empty config directory (in a tmp dir), with
every ``EMDATABASE_*`` environment variable cleared and the first-run notice
already marked shown, so the developer's real configuration never affects a test
and a test never writes to the real one.

:func:`two_techniques` installs a dataset declaring more than one technique,
which the shipped index has none of.

:func:`http_server` is the other shared piece: a real server on localhost, so
the tests that fetch a file exercise the HEAD request and the redirect rather
than a monkeypatched download. Nothing here touches the network.
"""

import http.server
import io
import os
import threading
from functools import partial
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    from emdatabase import config

    for name in list(os.environ):
        if name.startswith(config.ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EMDATABASE_CONFIG", str(tmp_path / "config"))
    monkeypatch.setattr(config, "_NOTICE_SHOWN", True)
    config.refresh()
    yield
    config.refresh()


TWO_TECHNIQUE_SPEC = {
    "description": "An in-situ 4D-STEM dataset of something.",
    "source": "https://zenodo.org/records/0000000/files",
    "file": "TwoTechniques.zspy",
    "technique": ["4D-STEM", "In-situ"],
}


@pytest.fixture
def two_techniques(monkeypatch):
    """Install a dataset declaring two techniques into ``emdatabase.data``.

    Nothing in the shipped index is more than one technique yet, and the point
    of the feature is what happens when one is.
    """
    import emdatabase.data as data
    from emdatabase.downloadable_dataset import DownloadableDataset
    from emdatabase.metadata import DatasetMetadata

    name = "TwoTechniques"
    cls = type(
        name,
        (DownloadableDataset,),
        {
            "_spec": TWO_TECHNIQUE_SPEC,
            "_metadata": DatasetMetadata.from_spec(TWO_TECHNIQUE_SPEC),
        },
    )
    monkeypatch.setattr(data, name, cls, raising=False)
    monkeypatch.setattr(data, "__all__", [*data.__all__, name])
    return name


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve the directory, with two paths that stand in for real hosts.

    ``/moved/<name>`` redirects to ``/<name>``, the way Zenodo and GitHub raw
    both do. ``/uc?export=download&id=<name>`` is the Google Drive shape: a link
    that names no file, redirecting to bytes that name themselves in a
    ``Content-Disposition`` header.

    A plain path answers a ``Range`` header with ``206`` and that slice, which is
    what reading one member out of a remote zip needs. ``/attached/`` keeps
    ignoring ``Range`` and answering ``200``, standing in for a host that does
    not do ranges at all.
    """

    def send_head(self):
        if self.path.startswith("/moved/"):
            self.send_response(302)
            self.send_header("Location", self.path[len("/moved") :])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if self.path.startswith("/uc?"):
            self.send_response(302)
            self.send_header("Location", "/attached/" + self.path.rpartition("=")[2])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if self.path.startswith("/attached/"):
            name = self.path[len("/attached/") :]
            body = (Path(self.directory) / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            return io.BytesIO(body)
        if self.path.startswith("/flaky/"):
            return self._die_mid_read()
        if "Range" in self.headers:
            return self._send_range()
        return super().send_head()

    def _die_mid_read(self):
        """Says how big the file is, then refuses to serve any of it.

        A host that goes down between the HEAD that finds the archive's
        directory and the ranges that read it - Zenodo under load answering
        ``503`` - which is a failure arriving mid-read rather than up front.
        """
        body = (Path(self.directory) / self.path[len("/flaky/") :]).read_bytes()
        if self.command == "HEAD":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return None
        self.send_error(503)
        return None

    def _send_range(self):
        """``206`` with the requested slice, for ``bytes=<first>-[<last>]``."""
        body = Path(self.translate_path(self.path)).read_bytes()
        first, _, last = self.headers["Range"].partition("=")[2].partition("-")
        start = int(first)
        end = int(last) if last else len(body) - 1
        chunk = body[start : end + 1]
        self.send_response(206)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
        self.end_headers()
        return io.BytesIO(chunk)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def http_server(tmp_path):
    """``(base url, served directory)`` for a local HTTP server.

    The directory starts empty and is read on each request, so a test writes
    whatever it wants served into it, before or after asking for the URL.
    """
    served = tmp_path / "served"
    served.mkdir()
    handler = partial(_Handler, directory=str(served))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", served
    httpd.shutdown()
    thread.join()
