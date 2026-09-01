"""Shared test fixtures.

Every test runs against an isolated, empty config directory (in a tmp dir), with
every ``EMDATABASE_*`` environment variable cleared and the first-run notice
already marked shown, so the developer's real configuration never affects a test
and a test never writes to the real one.

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


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve the directory, with two paths that stand in for real hosts.

    ``/moved/<name>`` redirects to ``/<name>``, the way Zenodo and GitHub raw
    both do. ``/uc?export=download&id=<name>`` is the Google Drive shape: a link
    that names no file, redirecting to bytes that name themselves in a
    ``Content-Disposition`` header.
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
        return super().send_head()

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
