"""Tests for the ``python -m emdatabase.new_dataset`` CLI.

The file the CLI describes is served by the local HTTP server in ``conftest``
rather than a monkeypatched fetch, so the HEAD request that fills in
``size_bytes`` and the redirect that Zenodo and GitHub raw both do are
exercised for real. Nothing here touches the network.
"""

import hashlib
from pathlib import Path

import pytest
import yaml

from emdatabase.metadata import validate_file
from emdatabase.new_dataset import (
    default_name,
    download_md5,
    main,
    version_date,
    write_document,
)

pytest.importorskip("jsonschema")

CONTENT = b"a small 4D-STEM dataset, allegedly" * 100
MD5 = hashlib.md5(CONTENT).hexdigest()


@pytest.fixture
def server(http_server):
    """``(base url, served directory)``, with the dataset file in place."""
    base, served = http_server
    (served / "MyData.zspy").write_bytes(CONTENT)
    return base, served


def _answers(monkeypatch, *values):
    answers = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def _document(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_writes_a_valid_entry_with_the_checksum_and_size(server, tmp_path):
    base, _ = server
    out = tmp_path / "index"
    code = main(
        [
            f"{base}/MyData.zspy",
            "--name",
            "MyData",
            "--out",
            str(out),
            "--description",
            "A 4D-STEM dataset of something.",
            "--yes",
        ]
    )
    assert code == 0

    path = out / "MyData.yaml"
    assert path.read_text(encoding="utf-8").startswith("# $schema: ./json-schema.json\n")
    assert validate_file(path) == []
    entry = _document(path)["MyData"]
    assert entry["checksum"] == f"md5:{MD5}"
    assert entry["size_bytes"] == len(CONTENT)
    assert entry["source"] == base
    assert entry["file"] == "MyData.zspy"
    # The optional fields were not answered, so they are not written at all;
    # `kind` is written whether or not it was asked for.
    assert set(entry) == {"description", "source", "checksum", "file", "size_bytes", "kind"}
    assert entry["kind"] == "dataset"


def test_the_head_request_follows_a_redirect(server, tmp_path):
    base, _ = server
    assert (
        main(
            [
                f"{base}/moved/MyData.zspy",
                "--name",
                "MyData",
                "--out",
                str(tmp_path),
                "--description",
                "A 4D-STEM dataset of something.",
                "--yes",
            ]
        )
        == 0
    )
    entry = _document(tmp_path / "MyData.yaml")["MyData"]
    assert entry["size_bytes"] == len(CONTENT)
    assert entry["checksum"] == f"md5:{MD5}"


def test_a_link_that_names_no_file_is_written_as_a_url(server, tmp_path):
    """A Google-Drive-shaped link: the entry keeps the whole link, and the file
    name comes from the ``Content-Disposition`` the redirect leads to."""
    base, _ = server
    link = f"{base}/uc?export=download&id=MyData.zspy"
    assert (
        main(
            [
                link,
                "--name",
                "MyData",
                "--out",
                str(tmp_path),
                "--description",
                "A 4D-STEM dataset of something.",
                "--yes",
            ]
        )
        == 0
    )
    path = tmp_path / "MyData.yaml"
    assert validate_file(path) == []
    entry = _document(path)["MyData"]
    assert entry["url"] == link
    assert entry["source"] == base
    assert entry["file"] == "MyData.zspy"
    assert entry["checksum"] == f"md5:{MD5}"
    assert entry["size_bytes"] == len(CONTENT)


def test_prompts_fill_in_the_optional_fields(server, tmp_path, monkeypatch):
    base, _ = server
    _answers(
        monkeypatch,
        "MyData",  # entry name
        "A 4D-STEM dataset of something.",  # description
        "4D-STEM",  # technique
        "CC-BY-4.0",  # license
        "Direct Electron",  # detector manufacturer
        "DE-16",  # detector
        "Thermo Fisher Scientific",  # microscope vendor
        "Gen 1 Titan",  # microscope model
        "200 kV",  # voltage
        "",  # camera length
        "",  # DOI
        "Amorphous, Strain",  # tags
        "Jane Doe",  # author name
        "University of Somewhere",  # affiliation
        "0000-0002-1825-0097",  # ORCID
        "",  # no more authors
    )
    assert main([f"{base}/MyData.zspy", "--out", str(tmp_path)]) == 0

    path = tmp_path / "MyData.yaml"
    assert validate_file(path) == []
    entry = _document(path)["MyData"]
    assert entry["technique"] == "4D-STEM"
    assert entry["voltage"] == "200 kV"
    assert entry["tags"] == ["Amorphous", "Strain"]
    assert entry["authors"] == {
        "Jane Doe": {"affiliation": "University of Somewhere", "orcid": "0000-0002-1825-0097"}
    }
    assert "camera_length" not in entry
    assert "doi" not in entry


def _weights_answers(monkeypatch, name="DemoNet"):
    """The prompts a ``--kind weights`` run asks, in order."""
    _answers(
        monkeypatch,
        name,  # entry name
        "A peak-detection network for 4D-STEM patterns.",  # description
        "4D-STEM",  # technique
        "CC-BY-4.0",  # license
        "",  # detector manufacturer
        "",  # detector
        "",  # microscope vendor
        "",  # microscope model
        "",  # voltage
        "",  # camera length
        "",  # DOI
        "",  # tags
        "",  # no authors
        "quantem.diffractive_imaging.ObjectINR",  # model class
        "",  # framework: the default
        ">=0.2,<0.3",  # quantem
    )


def test_kind_weights_asks_for_the_model(server, tmp_path, monkeypatch):
    _weights_answers(monkeypatch)
    base, _ = server
    assert main([f"{base}/MyData.zspy", "--kind", "weights", "--out", str(tmp_path)]) == 0

    path = tmp_path / "DemoNet.yaml"
    assert validate_file(path) == []
    entry = _document(path)["DemoNet"]
    assert entry["kind"] == "weights"
    assert entry["model"] == {
        "class": "quantem.diffractive_imaging.ObjectINR",
        "framework": "torch",
        "quantem": ">=0.2,<0.3",
    }
    # The link becomes the family's `latest` and a version dated today.
    assert list(entry["versions"]) == [version_date()]
    assert entry["versions"][version_date()] == entry["latest"]
    assert entry["latest"] == {
        "url": f"{base}/MyData.zspy",
        "checksum": f"md5:{MD5}",
        "size_bytes": len(CONTENT),
    }
    assert not {"url", "checksum", "size_bytes"} & set(entry)


def test_version_date_files_the_version_under_another_date(server, tmp_path, monkeypatch):
    _weights_answers(monkeypatch)
    base, _ = server
    args = [f"{base}/MyData.zspy", "--kind", "weights", "--out", str(tmp_path)]
    assert main([*args, "--version-date", "260902"]) == 0

    path = tmp_path / "DemoNet.yaml"
    assert validate_file(path) == []
    entry = _document(path)["DemoNet"]
    assert list(entry["versions"]) == ["260902"]
    assert entry["versions"]["260902"] == entry["latest"]


def test_a_version_date_that_is_not_yymmdd_is_refused(server, tmp_path, capsys):
    base, _ = server
    with pytest.raises(SystemExit):
        main([f"{base}/MyData.zspy", "--out", str(tmp_path), "--version-date", "2026-09-02"])
    assert "YYMMDD" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.yaml"))


def test_a_dataset_entry_says_nothing_about_a_model(server, tmp_path):
    base, _ = server
    assert (
        main(
            [
                f"{base}/MyData.zspy",
                "--name",
                "MyData",
                "--out",
                str(tmp_path),
                "--description",
                "A 4D-STEM dataset of something.",
                "--yes",
            ]
        )
        == 0
    )
    entry = _document(tmp_path / "MyData.yaml")["MyData"]
    assert entry["kind"] == "dataset" and "model" not in entry


def test_a_misspelled_vendor_is_asked_for_again(server, tmp_path, monkeypatch):
    base, _ = server
    _answers(
        monkeypatch,
        "MyData",
        "A 4D-STEM dataset of something.",
        "4D-STEM",
        "",
        "Direct Electon",  # a typo: asked for again
        "Direct Electron",
        "",
        "",  # microscope vendor
        "",
        "",
        "",
        "",
        "",
        "",  # no authors
    )
    assert main([f"{base}/MyData.zspy", "--out", str(tmp_path)]) == 0
    assert _document(tmp_path / "MyData.yaml")["MyData"]["detector_manufacturer"] == (
        "Direct Electron"
    )


def test_an_existing_file_is_not_overwritten_without_force(server, tmp_path):
    base, _ = server
    args = [
        f"{base}/MyData.zspy",
        "--name",
        "MyData",
        "--out",
        str(tmp_path),
        "--description",
        "A 4D-STEM dataset of something.",
        "--yes",
    ]
    assert main(args) == 0
    path = tmp_path / "MyData.yaml"
    path.write_text("clobbered", encoding="utf-8")

    assert main(args) == 1
    assert path.read_text(encoding="utf-8") == "clobbered"
    assert main([*args, "--force"]) == 0
    assert validate_file(path) == []


def test_a_given_checksum_skips_the_download(tmp_path):
    """No server: the file is never fetched, so only the HEAD request can fail
    and ``size_bytes`` is simply left out."""
    assert (
        main(
            [
                "https://example.invalid/files/MyData.zspy",
                "--name",
                "MyData",
                "--out",
                str(tmp_path),
                "--description",
                "A 4D-STEM dataset of something.",
                "--checksum",
                f"md5:{MD5}",
                "--yes",
            ]
        )
        == 0
    )
    entry = _document(tmp_path / "MyData.yaml")["MyData"]
    assert entry["checksum"] == f"md5:{MD5}"
    assert "size_bytes" not in entry


def test_a_bad_entry_is_reported_and_nothing_is_written(server, tmp_path, capsys):
    base, _ = server
    code = main(
        [
            f"{base}/MyData.zspy",
            "--name",
            "MyData",
            "--out",
            str(tmp_path),
            "--description",
            "A 4D-STEM dataset of something.",
            "--checksum",
            "not-an-md5",
            "--yes",
        ]
    )
    assert code == 1
    assert "checksum" in capsys.readouterr().out
    assert not (tmp_path / "MyData.yaml").exists()


def test_validate_checks_a_file_written_by_hand(tmp_path, capsys):
    path = tmp_path / "MyData.yaml"
    path.write_text("MyData:\n  description: d\n  file: f\n", encoding="utf-8")
    assert main(["--validate", str(path)]) == 1
    assert "'source' is a required property" in capsys.readouterr().out

    path.write_text(
        "MyData:\n  description: d\n  source: https://example.com/f\n  file: f\n",
        encoding="utf-8",
    )
    assert main(["--validate", str(path)]) == 0
    assert "valid" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("PdNiP.zspy", "PdNiP"),
        ("pd-nip_glass.zspy", "PdNipGlass"),
        ("my data.tar.gz", "MyData"),
    ],
)
def test_default_name(filename, expected):
    assert default_name(filename) == expected


def test_write_document_writes_the_header_and_makes_the_directory(tmp_path):
    """The CI script reuses this to rewrite a family file."""
    path = tmp_path / "index" / "MyData.yaml"
    document = {"MyData": {"description": "d", "file": "f"}}
    write_document(path, document)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# $schema: ./json-schema.json\n")
    assert yaml.safe_load(text) == document


def test_download_md5_reports_the_content_type(server, tmp_path):
    """A host that answers a download link with a page, not the file."""
    base, served = server
    (served / "scan.html").write_text("<html>virus scan warning</html>", encoding="utf-8")
    _, _, name, content_type = download_md5(
        f"{base}/scan.html", tmp_path / "scan", progressbar=False
    )
    assert content_type.startswith("text/html")
    assert name == ""

    digest, size, name, content_type = download_md5(
        f"{base}/uc?export=download&id=MyData.zspy", tmp_path / "data", progressbar=False
    )
    assert (digest, size, name) == (MD5, len(CONTENT), "MyData.zspy")
    assert content_type == "application/octet-stream"


def test_the_temporary_download_does_not_stay_behind(server, tmp_path, monkeypatch):
    base, served = server
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()
    assert (
        main(
            [
                f"{base}/MyData.zspy",
                "--name",
                "MyData",
                "--out",
                str(tmp_path),
                "--description",
                "A 4D-STEM dataset of something.",
                "--yes",
            ]
        )
        == 0
    )
    assert list((tmp_path / "scratch").iterdir()) == []
    assert (served / "MyData.zspy").exists()  # the source file is left alone


def test_keep_leaves_the_temporary_download(server, tmp_path, monkeypatch):
    base, _ = server
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()
    main(
        [
            f"{base}/MyData.zspy",
            "--name",
            "MyData",
            "--out",
            str(tmp_path),
            "--description",
            "A 4D-STEM dataset of something.",
            "--yes",
            "--keep",
        ]
    )
    assert Path(tmp_path / "scratch" / "MyData.zspy").read_bytes() == CONTENT
