"""Tests for the pull-request script that fills in a checksum and a size.

``.github/scripts/fill_download_fields.py`` downloads whatever an entry is
missing, so the tests point one at the local HTTP server in ``conftest``. The
index it rewrites is a throwaway directory rather than the shipped one. The
script does not ship in the wheel, so it is loaded from its path the way
``test_check_weights`` loads the weights script.
"""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from emdatabase.new_dataset import FIELD_ORDER

pytest.importorskip("jsonschema")

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "fill_download_fields.py"

FILE = "MyData.zspy"
CONTENT = b"a small 4D-STEM dataset, allegedly" * 100
MD5 = f"md5:{hashlib.md5(CONTENT).hexdigest()}"


@pytest.fixture(scope="module")
def script():
    """The script under test, imported from its path."""
    if not SCRIPT.exists():
        pytest.skip(f"{SCRIPT} is not in this checkout")
    spec = importlib.util.spec_from_file_location("fill_download_fields_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def index(http_server, tmp_path):
    """``(served directory, index directory, writer)`` for one entry."""
    base, served = http_server
    (served / FILE).write_bytes(CONTENT)
    directory = tmp_path / "index"
    directory.mkdir()

    def write(**extra):
        document = {
            "MyData": {
                "description": "A 4D-STEM dataset of something.",
                "source": base,
                "file": FILE,
                "license": "CC-BY-4.0",
                "technique": ["4D-STEM"],
                **extra,
            }
        }
        path = directory / "MyData.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    return served, directory, write


def _run(script, directory, tmp_path, *paths):
    summary = tmp_path / "filled.md"
    code = script.main(["--index", str(directory), "--summary", str(summary), *paths])
    return code, summary.read_text(encoding="utf-8")


def test_a_blank_entry_is_filled_in_and_written(script, index, tmp_path):
    _, directory, write = index
    path = write()
    code, summary = _run(script, directory, tmp_path)

    assert code == 0
    entry = yaml.safe_load(path.read_text(encoding="utf-8"))["MyData"]
    assert entry["checksum"] == MD5
    assert entry["size_bytes"] == len(CONTENT)
    # Rewritten through build_document, so the filled-in fields land in order.
    assert list(entry) == [key for key in FIELD_ORDER if key in entry]
    assert MD5 in summary and str(path) in summary


def test_a_complete_index_is_not_rewritten(script, index, tmp_path):
    _, directory, write = index
    path = write(checksum=MD5, size_bytes=len(CONTENT))
    before = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)
    assert code == 0
    assert path.read_text(encoding="utf-8") == before
    assert summary.strip() == "Every entry already has its checksum and size."


def test_only_the_files_named_are_looked_at(script, index, tmp_path):
    """The workflow passes the files a pull request changed."""
    _, directory, write = index
    path = write()
    other = directory / "Other.yaml"
    other.write_text(path.read_text(encoding="utf-8").replace("MyData:", "Other:"), "utf-8")

    code, _ = _run(script, directory, tmp_path, str(path))
    assert code == 0
    assert "checksum" in path.read_text(encoding="utf-8")
    assert "checksum" not in other.read_text(encoding="utf-8")


def test_a_link_that_serves_a_page_fails_and_writes_nothing(script, index, tmp_path):
    served, directory, write = index
    (served / "scan.html").write_text("<html>virus scan warning</html>", encoding="utf-8")
    path = write(file="scan.html")
    before = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)
    assert code == 1
    assert path.read_text(encoding="utf-8") == before
    assert "served a page" in summary


def test_a_link_that_does_not_resolve_fails(script, index, tmp_path):
    _, directory, write = index
    path = write(file="NotThere.zspy")
    code, summary = _run(script, directory, tmp_path)
    assert code == 1
    assert "NotThere.zspy" in summary or "404" in summary
    assert "checksum" not in path.read_text(encoding="utf-8")


def test_an_entry_that_will_not_validate_is_not_written(script, index, tmp_path):
    """The same check the test suite runs, before anything is rewritten."""
    _, directory, write = index
    path = write(technique=["Tomograhy"])
    before = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)
    assert code == 1
    assert path.read_text(encoding="utf-8") == before
    assert "Tomograhy" in summary


def test_a_file_the_pull_request_deleted_is_skipped(script, index, tmp_path):
    """A removed entry is named by the diff but is not there to read."""
    _, directory, write = index
    path = write()
    gone = directory / "Removed.yaml"

    code, _ = _run(script, directory, tmp_path, str(path), str(gone))
    assert code == 0
    assert "checksum" in path.read_text(encoding="utf-8")
    assert not gone.exists()
