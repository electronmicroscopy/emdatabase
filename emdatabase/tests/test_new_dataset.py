"""Tests for the ``python -m emdatabase.new_dataset`` CLI.

The file the CLI describes is served by the local HTTP server in ``conftest``
rather than a monkeypatched fetch, so the HEAD request that fills in
``size_bytes`` and the redirect that Zenodo and GitHub raw both do are
exercised for real. Nothing here touches the network.

``fill_download_fields``, which the pull-request workflow runs over an entry a
form left incomplete, is tested against the same server at the end.
"""

import hashlib
from pathlib import Path

import pytest
import yaml

from emdatabase.metadata import validate_file
from emdatabase.new_dataset import (
    default_name,
    download_md5,
    fill_download_fields,
    main,
    normalize_url,
    split_url,
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
    assert entry["technique"] == ["4D-STEM"]
    assert entry["voltage"] == "200 kV"
    assert entry["tags"] == ["Amorphous", "Strain"]
    assert entry["authors"] == {
        "Jane Doe": {"affiliation": "University of Somewhere", "orcid": "0000-0002-1825-0097"}
    }
    assert "camera_length" not in entry
    assert "doi" not in entry


def test_the_technique_prompt_takes_a_comma_separated_list(server, tmp_path, monkeypatch):
    base, _ = server
    _answers(
        monkeypatch,
        "MyData",  # entry name
        "An in-situ 4D-STEM dataset of something.",  # description
        "In-situ, 4D-STEM",  # techniques
        "",  # license
        "",  # detector manufacturer
        "",  # detector
        "",  # microscope vendor
        "",  # microscope model
        "",  # voltage
        "",  # camera length
        "",  # DOI
        "",  # tags
        "",  # no authors
    )
    assert main([f"{base}/MyData.zspy", "--out", str(tmp_path)]) == 0

    path = tmp_path / "MyData.yaml"
    assert validate_file(path) == []
    assert _document(path)["MyData"]["technique"] == ["In-situ", "4D-STEM"]


def _weights_answers(monkeypatch, name="DemoNet"):
    """The prompts a ``--kind weights`` run asks, in order."""
    _answers(
        monkeypatch,
        name,  # entry name
        "A peak-detection network for 4D-STEM patterns.",  # description
        "4D-STEM, ML - peak finding",  # technique
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


def test_a_technique_outside_the_vocabulary_is_asked_for_again(
    server, tmp_path, monkeypatch, capsys
):
    """Unlike the vendor list, the technique vocabulary is closed."""
    base, _ = server
    _answers(
        monkeypatch,
        "MyData",
        "A 4D-STEM dataset of something.",
        "4D-STEM, Ptychography",  # not a technique: asked for again
        "4D-STEM",
        "",  # license
        "",  # detector manufacturer
        "",  # detector
        "",  # microscope vendor
        "",  # microscope model
        "",  # voltage
        "",  # camera length
        "",  # DOI
        "",  # tags
        "",  # no authors
    )
    assert main([f"{base}/MyData.zspy", "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "'Ptychography' not on the list" in printed
    assert "Tomography" in printed  # the options it offers instead
    assert _document(tmp_path / "MyData.yaml")["MyData"]["technique"] == ["4D-STEM"]


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


DRIVE_ID = "1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV"
DRIVE_DOWNLOAD = f"https://drive.google.com/uc?export=download&id={DRIVE_ID}"


@pytest.mark.parametrize(
    "url",
    [
        f"https://drive.google.com/file/d/{DRIVE_ID}/view?usp=drive_link",
        f"https://drive.google.com/file/d/{DRIVE_ID}/view?usp=sharing",
        f"https://drive.google.com/file/d/{DRIVE_ID}/view",
        f"https://drive.google.com/file/d/{DRIVE_ID}/edit",
        f"https://drive.google.com/file/d/{DRIVE_ID}",
        f"https://drive.google.com/open?id={DRIVE_ID}",
        f"https://drive.google.com/open?usp=drive_link&id={DRIVE_ID}",
        DRIVE_DOWNLOAD,
    ],
)
def test_a_drive_share_link_becomes_the_download_link(url):
    assert normalize_url(url) == DRIVE_DOWNLOAD


@pytest.mark.parametrize(
    "url",
    [
        "https://zenodo.org/records/15490547/files/PdNiP.zspy",
        "https://example.com/data/file.zspy?download=1",
        "https://docs.google.com/file/d/abc/view",
        "not a url",
        "",
    ],
)
def test_a_link_that_is_not_a_drive_share_link_is_left_alone(url):
    assert normalize_url(url) == url


def test_split_url_normalises_a_drive_share_link():
    """The CLI and the issue route get the rewrite for free, through split_url."""
    source, filename, link = split_url(f"https://drive.google.com/file/d/{DRIVE_ID}/view")
    assert (source, filename, link) == ("https://drive.google.com", "", DRIVE_DOWNLOAD)


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


def test_write_document_matches_the_hand_written_style(tmp_path):
    long_text = "word " * 30
    url = "https://example.org/" + "x" * 90
    document = {
        "Demo": {
            "description": long_text.strip(),
            "source": url,
            "file": "d.pt",
            "tags": ["A", "B"],
            "kind": "weights",
            "model": {"class": "m.M", "framework": "torch", "quantem": ">=0.1"},
            "latest": {"url": url, "checksum": "md5:" + "0" * 32},
            "versions": {"260902": {"url": url, "checksum": "md5:" + "0" * 32, "size_bytes": 1}},
        }
    }
    path = tmp_path / "Demo.yaml"
    write_document(path, document)
    text = path.read_text()
    assert "  description: >-\n    word word" in text
    assert "  tags:\n    - A\n    - B\n" in text
    assert '    quantem: ">=0.1"\n' in text
    assert '    "260902":\n' in text
    assert "'" not in text
    assert f"  source: {url}\n" in text
    assert yaml.safe_load(text) == document


# -- filling in a checksum and a size a form left blank -----------------------


def _entry(base, **extra):
    return {
        "MyData": {
            "description": "A 4D-STEM dataset of something.",
            "source": base,
            "file": "MyData.zspy",
            **extra,
        }
    }


def test_fill_download_fields_fills_in_both(server):
    base, _ = server
    document = _entry(base)
    lines = fill_download_fields(document)
    assert document["MyData"]["checksum"] == f"md5:{MD5}"
    assert document["MyData"]["size_bytes"] == len(CONTENT)
    assert len(lines) == 1
    assert f"md5:{MD5}" in lines[0] and str(len(CONTENT)) in lines[0]


def test_fill_download_fields_leaves_what_is_already_there(server):
    """Only the missing field is written; a checksum given by hand is not second-guessed."""
    base, _ = server
    stated = "md5:" + "0" * 32
    document = _entry(base, checksum=stated)
    lines = fill_download_fields(document)
    assert document["MyData"]["checksum"] == stated
    assert document["MyData"]["size_bytes"] == len(CONTENT)
    assert "size_bytes" in lines[0] and "checksum" not in lines[0]


def test_fill_download_fields_follows_a_url(server):
    """A link that names no file is followed as it stands, not as source/file."""
    base, _ = server
    document = _entry(base, url=f"{base}/uc?export=download&id=MyData.zspy", file="Renamed.zspy")
    fill_download_fields(document)
    assert document["MyData"]["checksum"] == f"md5:{MD5}"


def test_fill_download_fields_downloads_nothing_for_a_complete_entry(http_server):
    """Nothing is served here, so a request of any kind would fail the test."""
    base, _ = http_server
    document = _entry(base, checksum=f"md5:{MD5}", size_bytes=len(CONTENT))
    assert fill_download_fields(document) == []


def test_fill_download_fields_follows_every_weights_pin(server):
    """A family carries the two fields per pin, and each pin has its own link."""
    base, served = server
    older = b"the weights before the model was retrained" * 8
    (served / "older.pt").write_bytes(older)
    document = {
        "DemoNet": {
            "description": "A peak-detection network.",
            "source": base,
            "file": "DemoNet.pt",
            "kind": "weights",
            "latest": {"url": f"{base}/MyData.zspy"},
            "versions": {
                "260101": {"url": f"{base}/older.pt"},
                "260902": {
                    "url": f"{base}/MyData.zspy",
                    "checksum": f"md5:{MD5}",
                    "size_bytes": len(CONTENT),
                },
            },
        }
    }
    lines = fill_download_fields(document)
    entry = document["DemoNet"]
    assert entry["latest"] == {
        "url": f"{base}/MyData.zspy",
        "checksum": f"md5:{MD5}",
        "size_bytes": len(CONTENT),
    }
    assert entry["versions"]["260101"] == {
        "url": f"{base}/older.pt",
        "checksum": f"md5:{hashlib.md5(older).hexdigest()}",
        "size_bytes": len(older),
    }
    # The pin that was already complete is not downloaded, and not reported.
    assert [line.split(":")[0] for line in lines] == ["DemoNet latest", "DemoNet version 260101"]
    # Nothing is written at the top level, where a family may not carry them.
    assert not {"checksum", "size_bytes"} & set(entry)


def test_fill_download_fields_refuses_a_page(server):
    """A Drive viewer page, or a 404 dressed up as HTML, is not the file."""
    base, served = server
    (served / "scan.html").write_text("<html>virus scan warning</html>", encoding="utf-8")
    document = _entry(base, file="scan.html")
    with pytest.raises(ValueError, match="served a page rather than the file"):
        fill_download_fields(document)
    assert "checksum" not in document["MyData"]
