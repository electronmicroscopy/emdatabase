"""Tests for the issue route into ``index/``, and for the page that points at it.

An issue builds the same file the CLI does, so it is checked the same way: the
document it produces goes through :func:`~emdatabase.metadata.validate_document`
and its keys are compared against ``new_dataset.FIELD_ORDER``. One test runs the
same entry through both routes and compares the bytes.

The docs site's datasets table is built from the same YAML by the same module,
so its tab grouping is checked here too, along with the Add Dataset page, which
is now an explainer pointing at the issue form and the CLI rather than a form of
its own.

The issue script lives in ``.github/scripts`` rather than in the package and is
loaded from its path. Nothing here touches the network: the calls that would are
either stubbed out (``content_length``) or pointed at the local HTTP server in
``conftest``.
"""

import datetime
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from emdatabase.metadata import techniques, validate_document
from emdatabase.new_dataset import FIELD_ORDER, build_document, write_document

pytest.importorskip("jsonschema")

ROOT = Path(__file__).resolve().parents[2]
DOCS_SOURCE = ROOT / "docs" / "source"
ISSUE_SCRIPT = ROOT / ".github" / "scripts" / "issue_to_yaml.py"
ISSUE_FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "new_dataset.yaml"


def _import_path(name, path):
    """Import a module from a path, or skip when the file is not there.

    Neither the docs builder nor the issue script ships in the wheel, so both
    are missing when the tests run against an installed copy.
    """
    if not path.exists():
        pytest.skip(f"{path} is not in this checkout")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_docs():
    return _import_path("_build_docs_under_test", DOCS_SOURCE / "_build_docs.py")


@pytest.fixture(scope="module")
def issue_to_yaml():
    return _import_path("issue_to_yaml_under_test", ISSUE_SCRIPT)


VERSION_DATE = "260902"


def _entry_in_field_order(entry):
    keys = list(entry)
    assert keys == [k for k in FIELD_ORDER if k in keys]


def _assert_weights_family(entry, url, size_bytes=1104287335):
    """A weights entry is a family: one `latest`, one dated version, nothing loose."""
    assert entry["kind"] == "weights"
    assert entry["latest"] == {
        "url": url,
        "checksum": "md5:df9376d5c020a23f0f7f51cfe79f303f",
        "size_bytes": size_bytes,
    }
    assert entry["versions"] == {VERSION_DATE: entry["latest"]}
    assert list(entry["versions"]) == [VERSION_DATE]
    assert not {"url", "checksum", "size_bytes"} & set(entry)


def _issue_body(**answers):
    return "".join(f"### {label}\n\n{value}\n\n" for label, value in answers.items())


def _ticked(*chosen):
    """A checkboxes answer as GitHub writes it - a task list, ticked or not."""
    return "\n".join(f"- [{'x' if o in chosen else ' '}] {o}" for o in techniques())


@pytest.fixture
def parse(issue_to_yaml, monkeypatch):
    """``build_yaml(parse_issue_body(body))``, with the HEAD request stubbed out."""
    monkeypatch.setattr(issue_to_yaml, "content_length", lambda url: 1104287335)

    def run(body):
        return issue_to_yaml.build_yaml(issue_to_yaml.parse_issue_body(body))

    return run


# -- the issue form ----------------------------------------------------------


def test_issue_labels_match_the_fields_the_parser_looks_for(issue_to_yaml):
    form = yaml.safe_load(ISSUE_FORM.read_text(encoding="utf-8"))
    labels = [
        block["attributes"]["label"].strip("-")
        for block in form["body"]
        if block["type"] != "markdown"
    ]
    assert labels == list(issue_to_yaml.FIELDS)


def test_issue_form_offers_the_whole_technique_vocabulary(issue_to_yaml):
    """The template is static YAML, so nothing but a test keeps it in step."""
    form = yaml.safe_load(ISSUE_FORM.read_text(encoding="utf-8"))
    block = next(b for b in form["body"] if b.get("id") == "technique")
    assert [o["label"] for o in block["attributes"]["options"]] == list(techniques())


def test_issue_form_asks_for_the_authors_as_one_block(issue_to_yaml):
    """One required textarea, not a field per author part."""
    form = yaml.safe_load(ISSUE_FORM.read_text(encoding="utf-8"))
    blocks = {b["id"]: b for b in form["body"] if b["type"] != "markdown"}
    assert blocks["authors"]["type"] == "textarea"
    assert blocks["authors"]["validations"]["required"] is True
    assert not {"name", "affiliation", "orcid"} & set(blocks)


def test_issue_weights_entry_validates(parse):
    body = _issue_body(
        **{
            "--Dataset Name--": "DemoNet",
            "--Authors--": "Jane Doe; University of Somewhere; 0000-0002-1825-0097",
            "--URL--": "https://zenodo.org/records/15490547/files/DemoNet.pt",
            "--File Name--": "_No response_",
            "--Checksum--": "md5:df9376d5c020a23f0f7f51cfe79f303f",
            "--Description--": "Trained weights for the peak-finding U-Net.",
            "--Detector Manufacturer--": "_No response_",
            "Detector Model": "_No response_",
            "Microscope Vendor": "_No response_",
            "Microscope Model": "_No response_",
            "Camera Length": "_No response_",
            "Accelerating Voltage": "_No response_",
            "Dataset License": "MIT",
            "Technique": _ticked("STEM", "ML - peak finding"),
            "DOI": "10.5281/zenodo.15490547",
            "Tags": "Machine Learning, Segmentation",
            "Kind": "weights",
            "Version Date": VERSION_DATE,
            "Model Class": "quantem.core.ml.CNN2d",
            "Model Framework": "torch",
            "Model quantem": ">=0.2,<0.3",
        }
    )
    document, name, problems = parse(body)
    assert problems == []
    assert name == "DemoNet"
    assert validate_document(document) == []
    entry = document[name]
    _entry_in_field_order(entry)
    assert "url" not in entry
    assert entry["source"] == "https://zenodo.org/records/15490547/files"
    assert entry["file"] == "DemoNet.pt"
    assert entry["doi"] == "10.5281/zenodo.15490547"
    assert entry["tags"] == ["Machine Learning", "Segmentation"]
    assert entry["technique"] == ["STEM", "ML - peak finding"]
    assert entry["authors"]["Jane Doe"]["orcid"] == "0000-0002-1825-0097"
    assert entry["model"] == {
        "class": "quantem.core.ml.CNN2d",
        "framework": "torch",
        "quantem": ">=0.2,<0.3",
    }
    _assert_weights_family(entry, "https://zenodo.org/records/15490547/files/DemoNet.pt")


def test_issue_takes_today_when_the_version_date_is_blank(parse):
    body = _issue_body(
        **{
            "--Dataset Name--": "DemoNet",
            "--URL--": "https://zenodo.org/records/15490547/files/DemoNet.pt",
            "--Checksum--": "md5:df9376d5c020a23f0f7f51cfe79f303f",
            "--Description--": "Trained weights for the peak-finding U-Net.",
            "--Dataset License--": "MIT",
            "Technique": _ticked("STEM", "ML - peak finding"),
            "Kind": "weights",
            "Version Date": "_No response_",
            "Model Class": "quantem.core.ml.CNN2d",
            "Model Framework": "torch",
        }
    )
    document, name, problems = parse(body)
    assert problems == []
    assert validate_document(document) == []
    assert list(document[name]["versions"]) == [datetime.date.today().strftime("%y%m%d")]


def test_issue_drive_link_becomes_url_plus_file_name(parse):
    body = _issue_body(
        **{
            "--Dataset Name--": "MgONanoCrystals",
            "--Authors--": "Jane Doe; University of Somewhere",
            "--URL--": "https://drive.google.com/uc?export=download&id=1inQ6DQ2zH40Ccd",
            "--File Name--": "MgONanoCrystals.zspy",
            "--Checksum--": "md5:df9376d5c020a23f0f7f51cfe79f303f",
            "--Description--": "A 4D-STEM dataset of MgO nanocrystals.\nTwo lines of it.",
            "--Detector Manufacturer--": "Direct Electron",
            "Detector Model": "CeleritasXS",
            "Microscope Vendor": "Thermo Fisher Scientific",
            "Microscope Model": "Gen 1 Titan",
            "Camera Length": "100 mm",
            "Accelerating Voltage": "200 kV",
            "Dataset License": "CC-BY-4.0",
            "Technique": _ticked("4D-STEM", "In-situ"),
            "Tags": "Nanocrystals",
        }
    )
    document, name, problems = parse(body)
    assert problems == []
    assert validate_document(document) == []
    entry = document[name]
    _entry_in_field_order(entry)
    assert entry["technique"] == ["4D-STEM", "In-situ"]
    assert entry["source"] == "https://drive.google.com"
    assert entry["url"] == "https://drive.google.com/uc?export=download&id=1inQ6DQ2zH40Ccd"
    assert entry["file"] == "MgONanoCrystals.zspy"
    assert entry["description"].splitlines() == [
        "A 4D-STEM dataset of MgO nanocrystals.",
        "Two lines of it.",
    ]
    assert entry["kind"] == "dataset"
    assert "model" not in entry


# -- the authors block -------------------------------------------------------


def _authors_body(authors):
    return _issue_body(
        **{
            "--Dataset Name--": "MgONanoCrystals",
            "--Authors--": authors,
            "--URL--": "https://zenodo.org/records/1/files/MgONanoCrystals.zspy",
            "--Checksum--": "md5:df9376d5c020a23f0f7f51cfe79f303f",
            "--Size (bytes)--": "1104287335",
            "--Description--": "A 4D-STEM dataset of MgO nanocrystals.",
            "--Dataset License--": "CC-BY-4.0",
            "Technique": _ticked("4D-STEM"),
        }
    )


def test_issue_parses_several_authors(parse):
    """One author per line, the ORCID optional, blank lines skipped."""
    document, name, problems = parse(
        _authors_body(
            "Jane Doe; University of Somewhere; 0000-0002-1825-0097\n"
            "\n"
            "  John Roe ; Institute of Elsewhere  \n"
        )
    )
    assert problems == []
    assert validate_document(document) == []
    assert document[name]["authors"] == {
        "Jane Doe": {
            "affiliation": "University of Somewhere",
            "orcid": "0000-0002-1825-0097",
        },
        "John Roe": {"affiliation": "Institute of Elsewhere"},
    }


def test_issue_author_without_an_affiliation_is_unspecified(parse):
    document, name, problems = parse(_authors_body("Jane Doe;"))
    assert problems == []
    assert document[name]["authors"] == {"Jane Doe": {"affiliation": "Unspecified"}}


def test_issue_author_line_without_a_semicolon_is_a_problem(parse):
    """It cannot be split into name and affiliation, so it is reported, not guessed at."""
    document, name, problems = parse(
        _authors_body("Jane Doe; University of Somewhere\nJohn Roe\n")
    )
    assert len(problems) == 1
    assert "John Roe" in problems[0] and "Name; Affiliation; ORCID" in problems[0]
    assert document[name]["authors"] == {"Jane Doe": {"affiliation": "University of Somewhere"}}


def test_issue_a_bad_author_line_stops_the_run_and_says_so(issue_to_yaml, tmp_path, capsys):
    """The problem reaches the log the workflow comments back onto the issue."""
    issue = tmp_path / "issue.txt"
    issue.write_text(_authors_body("John Roe"), encoding="utf-8")
    out = tmp_path / "index"
    out.mkdir()
    with pytest.raises(SystemExit):
        issue_to_yaml.write_yaml(issue, out)
    assert "Name; Affiliation; ORCID" in capsys.readouterr().out
    assert list(out.iterdir()) == []


# -- the size and the checksum -----------------------------------------------


def test_issue_takes_the_size_it_was_given(issue_to_yaml, monkeypatch):
    """A size on the issue means the server is not asked for it."""

    def no_head(url):
        raise AssertionError(f"asked the server about {url}")

    monkeypatch.setattr(issue_to_yaml, "content_length", no_head)
    body = _issue_body(
        **{
            "--Dataset Name--": "MgONanoCrystals",
            "--URL--": "https://drive.google.com/uc?export=download&id=1inQ6DQ2zH40Ccd",
            "--File Name--": "MgONanoCrystals.zspy",
            "--Checksum--": "md5:df9376d5c020a23f0f7f51cfe79f303f",
            "--Size (bytes)--": "1104287335",
            "--Description--": "A 4D-STEM dataset of MgO nanocrystals.",
            "--Dataset License--": "CC-BY-4.0",
            "Technique": _ticked("4D-STEM"),
        }
    )
    document, name, problems = issue_to_yaml.build_yaml(issue_to_yaml.parse_issue_body(body))
    assert problems == []
    assert validate_document(document) == []
    assert document[name]["size_bytes"] == 1104287335


def test_issue_asks_the_server_when_the_size_is_not_a_number(issue_to_yaml, monkeypatch):
    """A blank or unparseable answer falls back to the HEAD request."""
    monkeypatch.setattr(issue_to_yaml, "content_length", lambda url: 4242)
    for answer in ("_No response_", "about 1 GB"):
        body = _issue_body(
            **{
                "--Dataset Name--": "MgONanoCrystals",
                "--URL--": "https://zenodo.org/records/1/files/MgONanoCrystals.zspy",
                "--Checksum--": "md5:df9376d5c020a23f0f7f51cfe79f303f",
                "--Size (bytes)--": answer,
                "--Description--": "A 4D-STEM dataset of MgO nanocrystals.",
                "--Dataset License--": "CC-BY-4.0",
                "Technique": _ticked("4D-STEM"),
            }
        )
        document, name, _problems = issue_to_yaml.build_yaml(issue_to_yaml.parse_issue_body(body))
        assert document[name]["size_bytes"] == 4242


FILE_BYTES = b"a small 4D-STEM dataset, allegedly" * 100
FILE_MD5 = f"md5:{hashlib.md5(FILE_BYTES).hexdigest()}"


def test_issue_a_blank_checksum_is_filled_in_from_the_file(issue_to_yaml, http_server, tmp_path):
    """The checksum is optional on the form, so the script downloads the file for it."""
    base, served = http_server
    (served / "MyData.zspy").write_bytes(FILE_BYTES)
    issue = tmp_path / "issue.txt"
    issue.write_text(
        _issue_body(
            **{
                "--Dataset Name--": "MyData",
                "--URL--": f"{base}/MyData.zspy",
                "--Checksum--": "_No response_",
                "--Description--": "A 4D-STEM dataset of something.",
                "--Dataset License--": "CC-BY-4.0",
                "Technique": _ticked("4D-STEM"),
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "index"
    issue_to_yaml.write_yaml(issue, out)

    document = yaml.safe_load((out / "MyData.yaml").read_text(encoding="utf-8"))
    assert validate_document(document) == []
    entry = document["MyData"]
    _entry_in_field_order(entry)
    assert entry["checksum"] == FILE_MD5
    # The size the HEAD request gave is kept as it is.
    assert entry["size_bytes"] == len(FILE_BYTES)


# -- the two routes ----------------------------------------------------------


def test_issue_and_cli_write_the_same_file(issue_to_yaml, monkeypatch, tmp_path):
    """The two routes are only worth having if they end in the same bytes."""

    def no_head(url):
        raise AssertionError(f"asked the server about {url}")

    monkeypatch.setattr(issue_to_yaml, "content_length", no_head)
    issue = tmp_path / "issue.txt"
    issue.write_text(
        _authors_body(
            "Jane Doe; University of Somewhere; 0000-0002-1825-0097\nJohn Roe; Elsewhere"
        ),
        encoding="utf-8",
    )
    from_issue = tmp_path / "issue-index"
    from_issue.mkdir()
    issue_to_yaml.write_yaml(issue, from_issue)

    entry = {
        "description": "A 4D-STEM dataset of MgO nanocrystals.",
        "source": "https://zenodo.org/records/1/files",
        "checksum": "md5:df9376d5c020a23f0f7f51cfe79f303f",
        "file": "MgONanoCrystals.zspy",
        "size_bytes": 1104287335,
        "license": "CC-BY-4.0",
        "technique": ["4D-STEM"],
        "authors": {
            "Jane Doe": {
                "affiliation": "University of Somewhere",
                "orcid": "0000-0002-1825-0097",
            },
            "John Roe": {"affiliation": "Elsewhere"},
        },
    }
    from_cli = tmp_path / "cli-index" / "MgONanoCrystals.yaml"
    from_cli.parent.mkdir()
    write_document(from_cli, build_document("MgONanoCrystals", entry))

    assert (from_issue / "MgONanoCrystals.yaml").read_bytes() == from_cli.read_bytes()


# -- the Add Dataset page ----------------------------------------------------


def test_add_dataset_page_points_at_the_issue_form_and_the_cli(build_docs):
    """The page is an explainer now: two routes named, no form of its own."""
    html = build_docs.generate_add_dataset_html()
    assert build_docs._ISSUE_URL in html
    assert build_docs._ISSUE_URL.endswith("/issues/new?template=new_dataset.yaml")
    assert "python -m emdatabase.new_dataset" in html
    assert "--kind weights" in html
    assert "Name; Affiliation; ORCID" in html
    for gone in ("<form", "<input", "spark-md5", "emdbBuildYaml"):
        assert gone not in html, gone


def test_generated_pages_load_nothing_from_outside(build_docs):
    """Every page is self-contained; the only external host left is a link target."""
    for generate in (
        build_docs.generate_add_dataset_html,
        build_docs.generate_landing_html,
        build_docs.generate_all_data_html,
        build_docs.generate_weights_html,
    ):
        html = generate()
        assert "<script src=" not in html
        assert "<link rel=" not in html


# -- the docs datasets table -------------------------------------------------


def test_docs_table_lists_a_two_technique_dataset_under_each(build_docs, tmp_path):
    """One row, both tabs: the tabs filter on the row's whole technique list."""
    (tmp_path / "TwoTechniques.yaml").write_text(
        yaml.safe_dump(
            {
                "TwoTechniques": {
                    "description": "An in-situ 4D-STEM dataset.",
                    "source": "https://zenodo.org/records/0000000/files",
                    "file": "TwoTechniques.zspy",
                    "technique": ["4D-STEM", "In-situ"],
                }
            }
        ),
        encoding="utf-8",
    )
    by_technique = build_docs.parse_datasets(tmp_path)
    assert sorted(by_technique) == ["4D-STEM", "In-situ"]
    assert [d["name"] for d in by_technique["4D-STEM"]] == ["TwoTechniques"]
    assert [d["name"] for d in by_technique["In-situ"]] == ["TwoTechniques"]

    html = build_docs.generate_html_table(by_technique)
    assert html.count("<strong>TwoTechniques</strong>") == 1
    assert 'data-technique="4D-STEM, In-situ"' in html
