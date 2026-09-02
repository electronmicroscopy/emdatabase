"""Tests for the two web routes into ``index/``: the docs form and the issue form.

Both build the same file the CLI does, so both are checked the same way - the
document they produce goes through :func:`~emdatabase.metadata.validate_document`
and its keys are compared against ``new_dataset.FIELD_ORDER``.

The docs form builds its YAML in the browser, so the check runs the generator
function itself under ``node``; the tests skip when node is not installed. The
issue-form script lives in ``.github/scripts`` rather than in the package and is
loaded from its path. Nothing here touches the network - the one call that would
(``content_length``) is stubbed out.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from emdatabase.metadata import load_schema, validate_document
from emdatabase.new_dataset import FIELD_ORDER, build_document

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


@pytest.fixture
def run_form(build_docs, tmp_path):
    """Run the form's YAML generator under node; return the YAML it writes."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "build_yaml.js"
    script.write_text(
        build_docs.ADD_DATASET_YAML_JS
        + '\nprocess.stdout.write(emdbBuildYaml(JSON.parse(require("fs")'
        + '.readFileSync(0, "utf8"))));\n',
        encoding="utf-8",
    )

    def run(fields):
        result = subprocess.run(
            [node, str(script)],
            input=json.dumps(fields),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    return run


DATASET_FIELDS: dict[str, Any] = {
    "name": "MgONanoCrystals",
    "description": "A 4D-STEM dataset of MgO nanocrystals, calibrated in mrad.",
    "source": "https://drive.google.com",
    "url": "https://drive.google.com/uc?export=download&id=1inQ6DQ2zH40CcdTSiXGnpG",
    "checksum": "md5:df9376d5c020a23f0f7f51cfe79f303f",
    "file": "MgONanoCrystals.zspy",
    "size_bytes": "1104287335",
    "detector_manufacturer": "Direct Electron",
    "detector": "CeleritasXS",
    "microscope_vendor": "Thermo Fisher Scientific",
    "microscope_model": "Gen 1 Titan",
    "camera_length": "100 mm",
    "voltage": "200 kV",
    "license": "CC-BY-4.0",
    "technique": "4D-STEM",
    "doi": "10.5281/zenodo.15490547",
    "tags": ["Nanocrystals", "Orientation Mapping"],
    "authors": [
        {"name": "Jane Doe", "aff": "University of Somewhere", "orcid": "0000-0002-1825-0097"}
    ],
    "kind": "dataset",
    "version": "1",
}

WEIGHTS_FIELDS: dict[str, Any] = dict(
    DATASET_FIELDS,
    name="DemoNet_v3",
    description="Trained weights for the peak-finding U-Net.",
    file="DemoNet_v3.pt",
    kind="weights",
    version="3",
    model_class="quantem.core.ml.CNN2d",
    model_framework="torch",
    model_quantem=">=0.2,<0.3",
)


def _entry(text):
    """The single entry in a generated document, after checking the header."""
    assert text.startswith("# $schema: ./json-schema.json\n")
    document = yaml.safe_load(text)
    assert len(document) == 1
    return document, next(iter(document.values()))


def _assert_in_field_order(entry):
    keys = list(entry)
    assert keys == [k for k in FIELD_ORDER if k in keys]


def test_form_dataset_with_an_opaque_url_validates(run_form):
    text = run_form(DATASET_FIELDS)
    document, entry = _entry(text)
    assert validate_document(document) == []
    _assert_in_field_order(entry)
    assert entry["url"] == DATASET_FIELDS["url"]
    assert entry["file"] == "MgONanoCrystals.zspy"
    assert entry["size_bytes"] == 1104287335
    assert entry["authors"] == {
        "Jane Doe": {"affiliation": "University of Somewhere", "orcid": "0000-0002-1825-0097"}
    }
    # `kind` is always written out, `dataset` included.
    assert entry["kind"] == "dataset"
    assert "model" not in entry


def test_form_weights_validates_and_carries_the_model(run_form):
    text = run_form(WEIGHTS_FIELDS)
    document, entry = _entry(text)
    assert validate_document(document) == []
    _assert_in_field_order(entry)
    assert entry["kind"] == "weights"
    assert entry["version"] == "3"
    assert entry["model"] == {
        "class": "quantem.core.ml.CNN2d",
        "framework": "torch",
        "quantem": ">=0.2,<0.3",
    }


def test_form_drops_the_model_block_for_a_dataset(run_form):
    fields = dict(WEIGHTS_FIELDS, kind="dataset")
    document, entry = _entry(run_form(fields))
    assert validate_document(document) == []
    assert "model" not in entry
    assert entry["kind"] == "dataset"


def test_form_omits_the_url_when_the_file_is_at_source_slash_file(run_form):
    fields = dict(DATASET_FIELDS, source="https://zenodo.org/records/15490547/files", url="")
    _, entry = _entry(run_form(fields))
    assert "url" not in entry


def test_form_and_cli_write_the_same_document(run_form):
    """The two routes are only worth having if they end in the same file."""
    _, from_form = _entry(run_form(WEIGHTS_FIELDS))
    entry: dict[str, Any] = {k: WEIGHTS_FIELDS.get(k) for k in FIELD_ORDER}
    entry["size_bytes"] = int(WEIGHTS_FIELDS["size_bytes"])
    entry["authors"] = {
        a["name"]: {"affiliation": a["aff"], "orcid": a["orcid"]}
        for a in WEIGHTS_FIELDS["authors"]
    }
    entry["model"] = {
        "class": WEIGHTS_FIELDS["model_class"],
        "framework": WEIGHTS_FIELDS["model_framework"],
        "quantem": WEIGHTS_FIELDS["model_quantem"],
    }
    from_cli = build_document(WEIGHTS_FIELDS["name"], entry)[WEIGHTS_FIELDS["name"]]
    assert from_form == from_cli
    assert list(from_form) == list(from_cli)


def test_form_keeps_the_underscore_in_a_weights_entry_name(run_form):
    """A weights entry is named with its version on the end - `DemoNet_v3`."""
    document, _ = _entry(run_form(WEIGHTS_FIELDS))
    assert list(document) == ["DemoNet_v3"]


def test_form_has_a_field_for_every_schema_property(build_docs):
    html = build_docs.generate_add_dataset_html()
    properties = load_schema()["patternProperties"]["^.+$"]["properties"]
    for name in properties:
        if name in ("authors", "model"):
            continue
        assert f'id="f-{name}"' in html, name
    for name in properties["model"]["properties"]:
        assert f'id="f-model_{name}"' in html, name
    for cls in ("a-name", "a-aff", "a-orcid"):
        assert f'class="{cls}"' in html, cls


# -- the issue form ----------------------------------------------------------


def _issue_body(**answers):
    return "".join(f"### {label}\n\n{value}\n\n" for label, value in answers.items())


@pytest.fixture
def parse(issue_to_yaml, monkeypatch):
    """``build_yaml(parse_issue_body(body))``, with the HEAD request stubbed out."""
    monkeypatch.setattr(issue_to_yaml, "content_length", lambda url: 1104287335)

    def run(body):
        return issue_to_yaml.build_yaml(issue_to_yaml.parse_issue_body(body))

    return run


def test_issue_labels_match_the_fields_the_parser_looks_for(issue_to_yaml):
    form = yaml.safe_load(ISSUE_FORM.read_text(encoding="utf-8"))
    labels = [
        block["attributes"]["label"].strip("-")
        for block in form["body"]
        if block["type"] != "markdown"
    ]
    assert labels == list(issue_to_yaml.FIELDS)


def test_issue_weights_entry_validates(parse):
    body = _issue_body(
        **{
            "--Dataset Name--": "DemoNet_v3",
            "--Author--": "Jane Doe",
            "--Affiliation--": "University of Somewhere",
            "--ORCID--": "0000-0002-1825-0097",
            "--URL--": "https://zenodo.org/records/15490547/files/DemoNet_v3.pt",
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
            "Technique": "Other",
            "DOI": "10.5281/zenodo.15490547",
            "Tags": "Machine Learning, Segmentation",
            "Kind": "weights",
            "Version": "3",
            "Model Class": "quantem.core.ml.CNN2d",
            "Model Framework": "torch",
            "Model quantem": ">=0.2,<0.3",
        }
    )
    document, name = parse(body)
    assert name == "DemoNet_v3"
    assert validate_document(document) == []
    entry = document[name]
    _assert_in_field_order(entry)
    assert "url" not in entry
    assert entry["source"] == "https://zenodo.org/records/15490547/files"
    assert entry["file"] == "DemoNet_v3.pt"
    assert entry["doi"] == "10.5281/zenodo.15490547"
    assert entry["tags"] == ["Machine Learning", "Segmentation"]
    assert entry["authors"]["Jane Doe"]["orcid"] == "0000-0002-1825-0097"
    assert entry["kind"] == "weights"
    assert entry["version"] == "3"
    assert entry["model"] == {
        "class": "quantem.core.ml.CNN2d",
        "framework": "torch",
        "quantem": ">=0.2,<0.3",
    }


def test_issue_drive_link_becomes_url_plus_file_name(parse):
    body = _issue_body(
        **{
            "--Dataset Name--": "MgONanoCrystals",
            "--Author--": "Jane Doe",
            "--Affiliation--": "University of Somewhere",
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
            "Technique": "4D-STEM",
            "Tags": "Nanocrystals",
        }
    )
    document, name = parse(body)
    assert validate_document(document) == []
    entry = document[name]
    _assert_in_field_order(entry)
    assert entry["source"] == "https://drive.google.com"
    assert entry["url"] == "https://drive.google.com/uc?export=download&id=1inQ6DQ2zH40Ccd"
    assert entry["file"] == "MgONanoCrystals.zspy"
    assert entry["description"].splitlines() == [
        "A 4D-STEM dataset of MgO nanocrystals.",
        "Two lines of it.",
    ]
    assert entry["kind"] == "dataset"
    assert "model" not in entry
