"""Tests for the weekly weights-archive script.

``.github/scripts/check_latest_weights.py`` follows each weights family's
``latest`` link, so the tests point one at the local HTTP server and change what
it serves. The two things the script does to the outside world are stubbed: the
``gh`` calls are recorded rather than run, and the index it rewrites is a
throwaway directory rather than the shipped one. The script does not ship in the
wheel, so it is loaded from its path the way ``test_forms`` loads the issue
script.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("jsonschema")

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "check_latest_weights.py"

FILE = "demonet.pt"
LATEST_BYTES = b"the weights that are published now" * 8
NEW_BYTES = b"the weights after the model was retrained" * 8
OLD_DATE = "260101"


def _md5(data: bytes) -> str:
    return f"md5:{hashlib.md5(data).hexdigest()}"


@pytest.fixture(scope="module")
def script():
    """The script under test, imported from its path."""
    if not SCRIPT.exists():
        pytest.skip(f"{SCRIPT} is not in this checkout")
    spec = importlib.util.spec_from_file_location("check_latest_weights_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gh(script, monkeypatch):
    """Every ``gh`` command the run would have issued, recorded not run."""
    calls: list[list[str]] = []

    def fake_run_gh(args, *, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(["gh", *args], 0, "", "")

    monkeypatch.setattr(script, "run_gh", fake_run_gh)
    return calls


@pytest.fixture
def index(tmp_path):
    """A directory holding one weights family, and a writer for its YAML."""
    directory = tmp_path / "index"
    directory.mkdir()
    path = directory / "DemoNet.yaml"

    def write(latest, versions):
        document = {
            "DemoNet": {
                "description": "A model that exists only in the tests.",
                "source": "http://127.0.0.1",
                "file": FILE,
                "license": "MIT",
                "kind": "weights",
                "model": {"class": "quantem.core.ml.CNN2d", "framework": "torch"},
                "latest": latest,
                "versions": versions,
            }
        }
        path.write_text(yaml.dump(document, sort_keys=False), encoding="utf-8")
        return path

    return directory, path, write


@pytest.fixture
def unchanged(http_server, index):
    """A family whose ``latest`` serves exactly what the index describes.

    Its one dated version is still on the source link, which is the state a
    freshly contributed entry is in.
    """
    base, served = http_server
    directory, path, write = index
    (served / FILE).write_bytes(LATEST_BYTES)
    pin = {
        "url": f"{base}/{FILE}",
        "checksum": _md5(LATEST_BYTES),
        "size_bytes": len(LATEST_BYTES),
    }
    write(dict(pin), {OLD_DATE: dict(pin)})
    return base, served, directory, path


def _run(script, directory, tmp_path, *extra):
    summary = tmp_path / "changes.md"
    code = script.main(
        [
            "--index",
            str(directory),
            "--summary",
            str(summary),
            "--keep-dir",
            str(tmp_path / "oversize"),
            *extra,
        ]
    )
    return code, summary


def _entry(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))["DemoNet"]


def test_an_unarchived_version_is_uploaded_and_its_url_rewritten(script, gh, unchanged, tmp_path):
    _, _, directory, path = unchanged
    code, summary = _run(script, directory, tmp_path)

    assert code == 0
    entry = _entry(path)
    assert entry["versions"][OLD_DATE]["url"] == (
        "https://github.com/electronmicroscopy/emdatabase/releases/download/"
        f"weights-archive/DemoNet_{OLD_DATE}.pt"
    )
    assert entry["latest"]["checksum"] == _md5(LATEST_BYTES)
    upload = [call for call in gh if call[:2] == ["release", "upload"]]
    assert len(upload) == 1
    assert upload[0][2] == "weights-archive"
    assert Path(upload[0][3]).name == f"DemoNet_{OLD_DATE}.pt"
    assert f"DemoNet_{OLD_DATE}.pt" in summary.read_text()


def test_an_already_archived_version_is_left_alone(script, gh, unchanged, tmp_path):
    base, _, directory, path = unchanged
    archived = {
        "url": "https://github.com/electronmicroscopy/emdatabase/releases/download/"
        f"weights-archive/DemoNet_{OLD_DATE}.pt",
        "checksum": _md5(LATEST_BYTES),
        "size_bytes": len(LATEST_BYTES),
    }
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["DemoNet"]["versions"][OLD_DATE] = archived
    original = yaml.dump(document, sort_keys=False)
    path.write_text(original, encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)

    assert code == 0
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    assert "already archived" in summary.read_text()


def test_a_replaced_file_becomes_a_new_dated_version(script, gh, unchanged, tmp_path):
    _, served, directory, path = unchanged
    (served / FILE).write_bytes(NEW_BYTES)

    code, summary = _run(script, directory, tmp_path)

    assert code == 0
    today = script.version_date()
    entry = _entry(path)
    assert entry["latest"]["checksum"] == _md5(NEW_BYTES)
    assert entry["latest"]["size_bytes"] == len(NEW_BYTES)
    assert entry["versions"][today] == {
        "url": "https://github.com/electronmicroscopy/emdatabase/releases/download/"
        f"weights-archive/DemoNet_{today}.pt",
        "checksum": _md5(NEW_BYTES),
        "size_bytes": len(NEW_BYTES),
    }
    # The old version is still pinned to the bytes it was published with.
    assert entry["versions"][OLD_DATE]["checksum"] == _md5(LATEST_BYTES)
    report = summary.read_text()
    assert _md5(LATEST_BYTES) in report and _md5(NEW_BYTES) in report
    assert [call for call in gh if call[:2] == ["release", "upload"]]


def test_a_file_over_the_threshold_is_kept_for_a_maintainer(script, gh, unchanged, tmp_path):
    _, served, directory, path = unchanged
    (served / FILE).write_bytes(NEW_BYTES)

    code, summary = _run(script, directory, tmp_path, "--threshold-mb", "0")

    assert code == 0
    today = script.version_date()
    kept = tmp_path / "oversize" / f"DemoNet_{today}.pt"
    assert kept.read_bytes() == NEW_BYTES
    assert gh == []
    # The version is written anyway; the summary says how to finish the upload.
    assert _entry(path)["versions"][today]["url"].endswith(f"DemoNet_{today}.pt")
    assert f"gh release upload weights-archive {kept} --clobber" in summary.read_text()


def test_a_link_serving_html_fails_and_writes_nothing(script, gh, http_server, index, tmp_path):
    base, served = http_server
    directory, path, write = index
    (served / "scan-warning.html").write_text("<html>Google Drive cannot scan this file</html>")
    write(
        {"url": f"{base}/scan-warning.html", "checksum": _md5(LATEST_BYTES)},
        {OLD_DATE: {"url": f"{base}/{FILE}", "checksum": _md5(LATEST_BYTES), "size_bytes": 1}},
    )
    original = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)

    assert code == 1
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    assert "text/html" in summary.read_text()


def test_dry_run_writes_nothing(script, gh, unchanged, tmp_path):
    _, served, directory, path = unchanged
    (served / FILE).write_bytes(NEW_BYTES)
    original = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path, "--dry-run")

    assert code == 0
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    assert not summary.exists()


def test_two_states_of_a_file_under_one_date_fail(script, gh, unchanged, tmp_path):
    _, served, directory, path = unchanged
    (served / FILE).write_bytes(NEW_BYTES)
    today = script.version_date()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["DemoNet"]["versions"][today] = {
        "url": f"https://example.com/DemoNet_{today}.pt",
        "checksum": _md5(b"something else entirely"),
        "size_bytes": 23,
    }
    original = yaml.dump(document, sort_keys=False)
    path.write_text(original, encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)

    assert code == 1
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    assert f"`{today}` already exists" in summary.read_text()


CONCEPT = "1000"
OLD_RECORD = "1001"
NEW_RECORD = "1002"
NEW_DATE = "260304"


def _zenodo_file(base, record_id, key, data):
    return {
        "key": key,
        "size": len(data),
        "checksum": _md5(data),
        "links": {"self": f"{base}/api/records/{record_id}/files/{key}/content"},
    }


@pytest.fixture
def zenodo(http_server, index):
    """A weights family whose ``latest`` is a Zenodo record file link.

    ``publish`` writes one record's API JSON into the served directory, at the
    record id and, when it is the concept's newest, at the concept id as well -
    which is where both ``links.latest`` and the ``conceptrecid`` fallback
    lead. The file itself is never served, so a run that downloaded it fails.
    """
    base, served = http_server
    directory, path, write = index
    api = served / "api" / "records"
    api.mkdir(parents=True)

    def publish(record_id, published, files, *, newest=True):
        record = {
            "id": int(record_id),
            "conceptrecid": CONCEPT,
            "links": {"latest": f"{base}/api/records/{CONCEPT}"},
            "metadata": {"publication_date": published},
            "files": files,
        }
        for name in [record_id] + ([CONCEPT] if newest else []):
            (api / name).write_text(json.dumps(record), encoding="utf-8")
        return record

    pin = {
        "url": f"{base}/records/{OLD_RECORD}/files/{FILE}",
        "checksum": _md5(LATEST_BYTES),
        "size_bytes": len(LATEST_BYTES),
    }
    write(dict(pin), {OLD_DATE: dict(pin)})
    publish(OLD_RECORD, "2026-01-01", [_zenodo_file(base, OLD_RECORD, FILE, LATEST_BYTES)])
    return base, served, directory, path, publish


def test_a_zenodo_family_on_the_newest_record_is_left_alone(script, gh, zenodo, tmp_path):
    _, _, directory, path, _ = zenodo
    original = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)

    assert code == 0
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    assert f"record {OLD_RECORD} is still the latest version" in summary.read_text()


def test_a_new_zenodo_record_becomes_a_dated_version(script, gh, zenodo, tmp_path):
    base, _, directory, path, publish = zenodo
    publish(
        OLD_RECORD,
        "2026-01-01",
        [_zenodo_file(base, OLD_RECORD, FILE, LATEST_BYTES)],
        newest=False,
    )
    publish(NEW_RECORD, "2026-03-04", [_zenodo_file(base, NEW_RECORD, FILE, NEW_BYTES)])

    code, summary = _run(script, directory, tmp_path)

    assert code == 0
    assert gh == []
    entry = _entry(path)
    new_url = f"{base}/records/{NEW_RECORD}/files/{FILE}"
    assert entry["latest"] == {
        "url": new_url,
        "checksum": _md5(NEW_BYTES),
        "size_bytes": len(NEW_BYTES),
    }
    assert entry["versions"][NEW_DATE] == {
        "url": new_url,
        "checksum": _md5(NEW_BYTES),
        "size_bytes": len(NEW_BYTES),
    }
    # The record the entry pointed at before is immutable, so it stays as it is.
    assert entry["versions"][OLD_DATE]["url"] == f"{base}/records/{OLD_RECORD}/files/{FILE}"
    report = summary.read_text()
    assert f"new Zenodo record {NEW_RECORD}" in report
    assert _md5(LATEST_BYTES) in report and _md5(NEW_BYTES) in report


def test_a_new_zenodo_record_is_followed_without_links_latest(script, gh, zenodo, tmp_path):
    base, served, directory, path, publish = zenodo
    record = publish(NEW_RECORD, "2026-03-04", [_zenodo_file(base, NEW_RECORD, FILE, NEW_BYTES)])
    current = json.loads((served / "api" / "records" / OLD_RECORD).read_text(encoding="utf-8"))
    current["links"] = {}
    (served / "api" / "records" / OLD_RECORD).write_text(json.dumps(current), encoding="utf-8")
    assert record["conceptrecid"] == CONCEPT

    code, _ = _run(script, directory, tmp_path)

    assert code == 0
    assert _entry(path)["versions"][NEW_DATE]["checksum"] == _md5(NEW_BYTES)


def test_a_zenodo_record_without_the_named_file_fails(script, gh, zenodo, tmp_path):
    base, _, directory, path, publish = zenodo
    publish(
        NEW_RECORD,
        "2026-03-04",
        [
            _zenodo_file(base, NEW_RECORD, "demonet_v2.pt", NEW_BYTES),
            _zenodo_file(base, NEW_RECORD, "README.md", b"read me"),
        ],
    )
    original = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)

    assert code == 1
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    assert f"no file `{FILE}`" in summary.read_text()


def test_a_zenodo_record_whose_md5_disagrees_with_the_index_fails(script, gh, zenodo, tmp_path):
    base, _, directory, path, publish = zenodo
    publish(OLD_RECORD, "2026-01-01", [_zenodo_file(base, OLD_RECORD, FILE, NEW_BYTES)])
    original = path.read_text(encoding="utf-8")

    code, summary = _run(script, directory, tmp_path)

    assert code == 1
    assert path.read_text(encoding="utf-8") == original
    assert gh == []
    report = summary.read_text()
    assert _md5(LATEST_BYTES) in report and _md5(NEW_BYTES) in report


def test_backfill_archives_a_source_link_version_but_not_a_zenodo_one(
    script, gh, unchanged, tmp_path
):
    base, _, directory, path = unchanged
    zenodo_url = f"https://zenodo.org/records/{OLD_RECORD}/files/{FILE}"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["DemoNet"]["versions"]["251201"] = {
        "url": zenodo_url,
        "checksum": _md5(LATEST_BYTES),
        "size_bytes": len(LATEST_BYTES),
    }
    path.write_text(yaml.dump(document, sort_keys=False), encoding="utf-8")

    code, _ = _run(script, directory, tmp_path)

    assert code == 0
    versions = _entry(path)["versions"]
    assert versions["251201"]["url"] == zenodo_url
    assert versions[OLD_DATE]["url"].startswith(script.RELEASE_DOWNLOADS)
    upload = [call for call in gh if call[:2] == ["release", "upload"]]
    assert len(upload) == 1
    assert Path(upload[0][3]).name == f"DemoNet_{OLD_DATE}.pt"
