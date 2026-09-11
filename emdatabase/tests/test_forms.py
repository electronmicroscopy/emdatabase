"""Tests for the two web routes into ``index/``: the docs form and the issue form.

Both build the same file the CLI does, so both are checked the same way - the
document they produce goes through :func:`~emdatabase.metadata.validate_document`
and its keys are compared against ``new_dataset.FIELD_ORDER``.

The docs site's datasets table is built from the same YAML by the same module,
so its tab grouping is checked here too.

The docs form builds its YAML in the browser, so the check runs the generator
function itself under ``node``; the tests skip when node is not installed. The
issue-form script lives in ``.github/scripts`` rather than in the package and is
loaded from its path. Nothing here touches the network: the calls that would
are either stubbed out (``content_length``) or pointed at the local HTTP server
in ``conftest``.
"""

import datetime
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
import yaml

from emdatabase.metadata import (
    acquisition_techniques,
    load_schema,
    ml_tasks,
    techniques,
    validate_document,
)
from emdatabase.new_dataset import (
    FIELD_ORDER,
    as_weights_family,
    build_document,
    normalize_url,
    split_url,
)

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


@pytest.fixture
def run_issue_url(build_docs, tmp_path):
    """Run the form's issue-link builder under node.

    Returns ``(params, built)`` - the link's query parameters, decoded and with
    the template name dropped, and the ``{url, trimmed, max}`` the builder gave.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "issue_url.js"
    script.write_text(
        build_docs.ADD_DATASET_YAML_JS
        + '\nvar fields = JSON.parse(require("fs").readFileSync(0, "utf8"));\n'
        + "process.stdout.write(JSON.stringify(Object.assign(emdbIssueUrl("
        + json.dumps(build_docs._ISSUE_URL)
        + ", fields), {max: EMDB_ISSUE_URL_MAX})));\n",
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
        built = json.loads(result.stdout)
        assert built["url"].startswith(build_docs._ISSUE_URL)
        params = dict(parse_qsl(urlsplit(built["url"]).query))
        assert params.pop("template") == "new_dataset.yaml"
        return params, built

    return run


@pytest.fixture
def run_split(build_docs, tmp_path):
    """Run the form's link splitter under node; return ``(source, file, url)``."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "split_url.js"
    script.write_text(
        build_docs.ADD_DATASET_YAML_JS
        + '\nvar p = emdbSplitUrl(require("fs").readFileSync(0, "utf8"));\n'
        + "process.stdout.write(JSON.stringify([p.source, p.file, p.url]));\n",
        encoding="utf-8",
    )

    def run(url):
        result = subprocess.run(
            [node, str(script)], input=url, capture_output=True, text=True, check=True
        )
        return tuple(json.loads(result.stdout))

    return run


VERSION_DATE = "260902"

DRIVE_LINK = "https://drive.google.com/uc?export=download&id=1inQ6DQ2zH40CcdTSiXGnpG"

DATASET_FIELDS: dict[str, Any] = {
    "name": "MgONanoCrystals",
    "description": "A 4D-STEM dataset of MgO nanocrystals, calibrated in mrad.",
    "link": DRIVE_LINK,
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
    "technique": ["4D-STEM"],
    "doi": "10.5281/zenodo.15490547",
    "tags": ["Nanocrystals", "Orientation Mapping"],
    "authors": [
        {"name": "Jane Doe", "aff": "University of Somewhere", "orcid": "0000-0002-1825-0097"}
    ],
    "kind": "dataset",
}

WEIGHTS_FIELDS: dict[str, Any] = dict(
    DATASET_FIELDS,
    name="DemoNet",
    description="Trained weights for the peak-finding U-Net.",
    technique=["4D-STEM", "ML - peak finding"],
    file="DemoNet.pt",
    kind="weights",
    version_date=VERSION_DATE,
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


def _assert_weights_family(entry, url, size_bytes=1104287335):
    """A weights entry is a family: one `latest`, one dated version, nothing loose."""
    assert entry["kind"] == "weights"
    assert entry["latest"] == {
        "url": url,
        "checksum": DATASET_FIELDS["checksum"],
        "size_bytes": size_bytes,
    }
    assert entry["versions"] == {VERSION_DATE: entry["latest"]}
    assert list(entry["versions"]) == [VERSION_DATE]
    assert not {"url", "checksum", "size_bytes"} & set(entry)


def test_form_dataset_with_an_opaque_url_validates(run_form):
    text = run_form(DATASET_FIELDS)
    document, entry = _entry(text)
    assert validate_document(document) == []
    _assert_in_field_order(entry)
    assert entry["source"] == "https://drive.google.com"
    assert entry["url"] == DRIVE_LINK
    assert entry["file"] == "MgONanoCrystals.zspy"
    assert entry["size_bytes"] == 1104287335
    assert entry["authors"] == {
        "Jane Doe": {"affiliation": "University of Somewhere", "orcid": "0000-0002-1825-0097"}
    }
    # `kind` is always written out, `dataset` included.
    assert entry["kind"] == "dataset"
    assert "model" not in entry


def test_form_writes_every_technique_as_a_list(run_form):
    _, one = _entry(run_form(DATASET_FIELDS))
    assert one["technique"] == ["4D-STEM"]
    fields = dict(DATASET_FIELDS, technique=["In-situ", "4D-STEM"])
    document, entry = _entry(run_form(fields))
    assert validate_document(document) == []
    assert entry["technique"] == ["In-situ", "4D-STEM"]


def test_form_weights_validates_and_carries_the_model(run_form):
    text = run_form(WEIGHTS_FIELDS)
    document, entry = _entry(text)
    assert validate_document(document) == []
    _assert_in_field_order(entry)
    assert entry["model"] == {
        "class": "quantem.core.ml.CNN2d",
        "framework": "torch",
        "quantem": ">=0.2,<0.3",
    }
    _assert_weights_family(entry, DRIVE_LINK, int(WEIGHTS_FIELDS["size_bytes"]))


def test_form_takes_today_when_the_version_date_is_blank(run_form):
    _, entry = _entry(run_form(dict(WEIGHTS_FIELDS, version_date="")))
    assert list(entry["versions"]) == [datetime.date.today().strftime("%y%m%d")]


def test_form_drops_the_model_block_for_a_dataset(run_form):
    fields = dict(WEIGHTS_FIELDS, kind="dataset", technique=["4D-STEM"])
    document, entry = _entry(run_form(fields))
    assert validate_document(document) == []
    assert "model" not in entry
    assert entry["kind"] == "dataset"


def test_form_omits_the_url_when_the_file_is_at_source_slash_file(run_form):
    link = "https://zenodo.org/records/15490547/files/MgONanoCrystals.zspy"
    _, entry = _entry(run_form(dict(DATASET_FIELDS, link=link, file="")))
    assert "url" not in entry
    assert entry["source"] == "https://zenodo.org/records/15490547/files"
    assert entry["file"] == "MgONanoCrystals.zspy"


# Every shape of link the form may be handed, run through both implementations.
LINKS = (
    "https://drive.google.com/file/d/1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV/view?usp=drive_link",
    "https://drive.google.com/file/d/1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV/view",
    "https://drive.google.com/file/d/1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV/edit",
    "https://drive.google.com/open?id=1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV",
    "https://drive.google.com/open?usp=drive_link&id=1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV",
    DRIVE_LINK,
    "https://zenodo.org/records/15490547/files/smallPtychography.hspy",
    "https://zenodo.org/records/15490547/files/smallPtychography.hspy?download=1",
    "https://github.com/electronmicroscopy/emdatabase/raw/abc1234/data/small.zspy",
    "https://example.com/downloads/no-extension-here",
    "https://example.com",
    "HTTPS://Example.COM/a/b.zspy",
    "not a url",
)


@pytest.mark.parametrize("url", LINKS)
def test_form_splits_a_link_the_way_the_cli_does(run_split, url):
    """One field, two implementations: the JS port has to answer as split_url does."""
    assert run_split(url) == split_url(url)


def test_form_takes_a_drive_share_link(run_form):
    share = "https://drive.google.com/file/d/1jHE-XImhTFI9sFVdyvUWfwOXhdsxvPQV/view?usp=drive_link"
    fields = dict(DATASET_FIELDS, link=share, file="example.zspy")
    document, entry = _entry(run_form(fields))
    assert validate_document(document) == []
    assert entry["source"] == "https://drive.google.com"
    assert entry["url"] == normalize_url(share)
    assert entry["file"] == "example.zspy"


# What the issue form's field ids are called on the docs form. The submit link
# is only worth having if the two agree, so the mapping is written out here
# rather than read back off the page.
ISSUE_IDS = {
    "dataset_name": "DemoNet",
    "name": "Jane Doe",
    "affiliation": "University of Somewhere",
    "orcid": "0000-0002-1825-0097",
    "url": DRIVE_LINK,
    "file_name": "DemoNet.pt",
    "checksum": "md5:df9376d5c020a23f0f7f51cfe79f303f",
    "size_bytes": "1104287335",
    "description": "Trained weights for the peak-finding U-Net.",
    "detector_manufacturer": "Direct Electron",
    "detector_model": "CeleritasXS",
    "microscope_vendor": "Thermo Fisher Scientific",
    "microscope_model": "Gen 1 Titan",
    "camera_length": "100 mm",
    "accelerating_voltage": "200 kV",
    "license": "CC-BY-4.0",
    "doi": "10.5281/zenodo.15490547",
    "tags": "Nanocrystals, Orientation Mapping",
    "kind": "weights",
    "version_date": VERSION_DATE,
    "model_class": "quantem.core.ml.CNN2d",
    "model_framework": "torch",
    "model_quantem": ">=0.2,<0.3",
}


def test_form_submits_as_an_issue(build_docs):
    """One button, and it goes to the issue form; nothing opens a pull request."""
    html = build_docs.generate_add_dataset_html()
    assert 'id="submit-issue" class="btn-primary"' in html
    assert build_docs._ISSUE_URL in html
    assert build_docs._ISSUE_URL.endswith("/issues/new?template=new_dataset.yaml")
    assert "/new/main" not in html and "filename=" not in html
    assert "create new file" not in html
    assert not hasattr(build_docs, "_REPO") and not hasattr(build_docs, "_BRANCH")


def test_form_shows_the_yaml_below_the_submit_button(build_docs):
    """The entry is a preview of what the issue produces, not the way to submit it."""
    html = build_docs.generate_add_dataset_html()
    assert html.index('id="submit-issue"') < html.index('id="copy-yaml"')
    assert html.index('id="copy-yaml"') < html.index('id="yaml-preview"')


def test_form_issue_link_carries_every_field_the_template_has(run_issue_url):
    """The link's query has to decode back to the values the YAML is built from."""
    params, built = run_issue_url(WEIGHTS_FIELDS)
    assert params == ISSUE_IDS
    assert built["trimmed"] == 0


def test_form_issue_link_ids_are_the_ones_the_template_declares(run_issue_url):
    """Every prefillable field on the template, and nothing GitHub will not prefill."""
    form = yaml.safe_load(ISSUE_FORM.read_text(encoding="utf-8"))
    blocks = {b["id"]: b["type"] for b in form["body"] if b["type"] != "markdown"}
    params, _built = run_issue_url(WEIGHTS_FIELDS)
    assert set(params) <= set(blocks)
    # GitHub prefills `input` and `textarea` only, so the technique tick boxes
    # are left to be filled in on the issue itself.
    assert blocks["technique"] == "checkboxes"
    assert "technique" not in params
    assert set(blocks) - set(params) == {"technique"}


def test_form_issue_link_leaves_out_what_the_form_was_not_given(run_issue_url):
    """A blank field is absent from the query rather than sent empty."""
    params, _built = run_issue_url(dict(DATASET_FIELDS, doi="", authors=[], tags=[]))
    assert "doi" not in params and "tags" not in params
    assert "name" not in params and "affiliation" not in params
    assert params["dataset_name"] == "MgONanoCrystals"
    assert params["kind"] == "dataset"


def test_form_issue_link_trims_a_description_that_will_not_fit(run_issue_url):
    """GitHub answers an over-long URL with 414, so the description gives way."""
    long_description = ("A 4D-STEM dataset of MgO nanocrystals. " * 400).strip()
    params, built = run_issue_url(dict(DATASET_FIELDS, description=long_description))
    trimmed = built["trimmed"]
    assert trimmed > 0
    assert len(built["url"]) <= built["max"] <= 8192
    assert len(params["description"]) + trimmed == len(long_description) + 2
    assert params["description"].endswith(" \u2026")
    for key, value in ISSUE_IDS.items():
        if key in ("description", "dataset_name", "file_name", "kind", "version_date"):
            continue
        if key.startswith("model_"):
            continue
        assert params[key] == value


def test_form_offers_a_local_file_picker(build_docs):
    """The picker fills in name, size and md5; the md5 comes from SparkMD5."""
    html = build_docs.generate_add_dataset_html()
    assert 'id="f-localfile" type="file"' in html
    assert 'id="hint-f-localfile"' in html
    assert "spark-md5/3.0.2/spark-md5.min.js" in html


def _field_html(html, fid):
    """The one field block for ``fid``: from its label to its error line."""
    return html[html.index(f'<label for="{fid}"') : html.index(f'id="err-{fid}"')]


@pytest.mark.parametrize("fid", ["f-checksum", "f-size_bytes"])
def test_form_does_not_require_the_checksum_or_the_size(build_docs, fid):
    """Both are filled in on the pull request, so the form takes them blank."""
    block = _field_html(build_docs.generate_add_dataset_html(), fid)
    assert '<span class="req">' not in block
    assert "Filled in automatically on the pull request" in block


def test_form_and_cli_write_the_same_document(run_form):
    """The two routes are only worth having if they end in the same file."""
    _, from_form = _entry(run_form(WEIGHTS_FIELDS))
    entry: dict[str, Any] = {k: WEIGHTS_FIELDS.get(k) for k in FIELD_ORDER}
    entry["source"], _, entry["url"] = split_url(WEIGHTS_FIELDS["link"])
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
    entry = as_weights_family(entry, VERSION_DATE)
    from_cli = build_document(WEIGHTS_FIELDS["name"], entry)[WEIGHTS_FIELDS["name"]]
    assert from_form == from_cli
    assert list(from_form) == list(from_cli)
    _assert_weights_family(from_cli, DRIVE_LINK, int(WEIGHTS_FIELDS["size_bytes"]))


def test_form_keeps_the_underscore_in_an_entry_name(run_form):
    """An underscore is legal in an entry name, so it survives the cleaning."""
    document, _ = _entry(run_form(dict(DATASET_FIELDS, name="AmorphousFilm4nm_4DSTEM")))
    assert list(document) == ["AmorphousFilm4nm_4DSTEM"]


def test_form_has_a_field_for_every_schema_property(build_docs):
    html = build_docs.generate_add_dataset_html()
    properties = load_schema()["patternProperties"]["^.+$"]["properties"]
    for name in properties:
        # One "Download link" field stands for both, and is split the way the CLI
        # splits it; the form never asks for either on its own.
        if name in ("authors", "model", "latest", "versions", "source", "url"):
            continue
        assert f'id="f-{name}"' in html, name
    assert 'id="f-link"' in html
    assert 'id="f-source"' not in html and 'id="f-url"' not in html
    for name in properties["model"]["properties"]:
        assert f'id="f-model_{name}"' in html, name
    for cls in ("a-name", "a-aff", "a-orcid"):
        assert f'class="{cls}"' in html, cls


def test_form_renders_the_technique_vocabulary_in_two_groups(build_docs):
    """The form is the vocabulary, split the way techniques.yaml splits it."""
    html = build_docs.generate_add_dataset_html()
    heads = [
        html.index(f'<div class="check-set-label">{group}</div>')
        for group in ("Acquisition", "ML task")
    ]
    assert heads[0] < heads[1]
    for start, end, options in (
        (heads[0], heads[1], acquisition_techniques()),
        (heads[1], len(html), ml_tasks()),
    ):
        where = [html.index(f'<input type="checkbox" value="{name}">') for name in options]
        assert where == sorted(where)
        assert start < where[0] and where[-1] < end


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


# -- the issue form ----------------------------------------------------------


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


def test_issue_weights_entry_validates(parse):
    body = _issue_body(
        **{
            "--Dataset Name--": "DemoNet",
            "--Author--": "Jane Doe",
            "--Affiliation--": "University of Somewhere",
            "--ORCID--": "0000-0002-1825-0097",
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
    document, name = parse(body)
    assert name == "DemoNet"
    assert validate_document(document) == []
    entry = document[name]
    _assert_in_field_order(entry)
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
    document, name = parse(body)
    assert validate_document(document) == []
    assert list(document[name]["versions"]) == [datetime.date.today().strftime("%y%m%d")]


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
            "Technique": _ticked("4D-STEM", "In-situ"),
            "Tags": "Nanocrystals",
        }
    )
    document, name = parse(body)
    assert validate_document(document) == []
    entry = document[name]
    _assert_in_field_order(entry)
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


def test_issue_takes_the_size_the_form_measured(issue_to_yaml, monkeypatch):
    """The picker fills the size in, so the server is not asked for it."""

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
    document, name = issue_to_yaml.build_yaml(issue_to_yaml.parse_issue_body(body))
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
        document, name = issue_to_yaml.build_yaml(issue_to_yaml.parse_issue_body(body))
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
    _assert_in_field_order(entry)
    assert entry["checksum"] == FILE_MD5
    # The size the HEAD request gave is kept as it is.
    assert entry["size_bytes"] == len(FILE_BYTES)
