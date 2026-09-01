"""Tests for the dataset record and the files it is built from.

The shipped YAML is the product this package exists to hand out, and until now
nothing checked it against the schema sitting next to it. These tests are that
check, plus the ones that keep the schema, the dataclass and the vendor list
from drifting apart - three descriptions of the same record, in three files.
"""

import dataclasses

import pytest
import yaml

from emdatabase.metadata import (
    TEMPLATE_PATH,
    Author,
    DatasetMetadata,
    check_vendor,
    dataset_files,
    format_size,
    load_schema,
    load_vendors,
    validate_document,
    validate_file,
)

pytest.importorskip("jsonschema")

DATASET_FILES = dataset_files()
SCHEMA = load_schema()
ENTRY_SCHEMA = SCHEMA["patternProperties"]["^.+$"]
VENDORS = load_vendors()


def entries():
    """``(file, name, spec)`` for every entry in every dataset YAML."""
    for path in DATASET_FILES:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, spec in document.items():
            yield path, name, spec


ENTRIES = list(entries())


def test_datasets_are_found():
    assert DATASET_FILES, "no dataset YAML found"
    assert all(p.name != "vendors.yaml" for p in DATASET_FILES)


@pytest.mark.parametrize("path", DATASET_FILES, ids=lambda p: p.name)
def test_yaml_is_valid(path):
    assert validate_file(path) == []


def test_template_is_valid():
    """The template is not a dataset, so nothing else here looks at it; a
    placeholder that does not validate is a contributor's first impression."""
    assert validate_file(TEMPLATE_PATH) == []


@pytest.mark.parametrize("name", [name for _, name, _ in ENTRIES])
def test_entry_builds_a_record(name):
    path, _, spec = next(e for e in ENTRIES if e[1] == name)
    metadata = DatasetMetadata.from_spec(spec, path)
    assert metadata.description and metadata.source and metadata.file


def test_schema_and_dataclass_agree():
    """The schema and :class:`DatasetMetadata` describe one record, in two files."""
    assert list(ENTRY_SCHEMA["properties"]) == [
        f.name for f in dataclasses.fields(DatasetMetadata)
    ]
    assert set(ENTRY_SCHEMA["required"]) == {
        f.name
        for f in dataclasses.fields(DatasetMetadata)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    }


def test_author_schema_and_dataclass_agree():
    author_schema = ENTRY_SCHEMA["properties"]["authors"]["patternProperties"]["^.+$"]
    assert list(author_schema["properties"]) == [f.name for f in dataclasses.fields(Author)]


def test_unknown_field_names_the_file_and_the_key():
    with pytest.raises(TypeError, match=r"somewhere\.yaml.*'folder'"):
        DatasetMetadata.from_spec(
            {"description": "d", "source": "s", "file": "f", "folder": "x"},
            "somewhere.yaml",
        )


def test_missing_required_field_is_an_error():
    with pytest.raises(TypeError, match="'file'"):
        DatasetMetadata.from_spec({"description": "d", "source": "s"})


def test_author_without_affiliation_is_an_error():
    with pytest.raises(TypeError, match="affiliation"):
        DatasetMetadata.from_spec(
            {"description": "d", "source": "s", "file": "f", "authors": {"Jane Doe": {}}}
        )


def test_tags_and_authors_are_converted():
    metadata = DatasetMetadata.from_spec(
        {
            "description": "d",
            "source": "s",
            "file": "f",
            "tags": ["One", "Two"],
            "authors": {"Jane Doe": {"affiliation": "Somewhere", "orcid": None}},
        }
    )
    assert metadata.tags == ("One", "Two")
    assert metadata.authors["Jane Doe"] == Author(affiliation="Somewhere")


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [
        (None, ""),
        (0, "0 B"),
        (999, "999 B"),
        (1000, "1.00 kB"),
        (34043, "34.0 kB"),
        (466089, "466.1 kB"),
        (104291721, "104.3 MB"),
        (1104287335, "1.10 GB"),
        (5748299565, "5.75 GB"),
    ],
)
def test_format_size(size_bytes, expected):
    assert format_size(size_bytes) == expected


@pytest.mark.parametrize(("path", "name", "spec"), ENTRIES, ids=[e[1] for e in ENTRIES])
def test_declared_vendors_are_spelled_correctly(path, name, spec):
    """A vendor close to a known one is a typo; one nothing like it is just new."""
    for field, known in (
        ("detector_manufacturer", VENDORS["detector_manufacturer"]),
        ("microscope_vendor", VENDORS["microscope_vendor"]),
    ):
        result = check_vendor(spec.get(field, ""), known)
        if result is None:
            continue
        level, message = result
        assert level != "error", f"{path.name}: {name}: {field}: {message}"


def test_validate_document_names_the_file_and_the_field():
    problems = validate_document({"X": {"description": "d", "file": "f"}}, origin="somewhere.yaml")
    assert len(problems) == 1
    assert problems[0].startswith("somewhere.yaml: X: ")
    assert "'source' is a required property" in problems[0]


def test_validate_document_reports_a_misspelled_vendor_and_warns_about_a_new_one():
    entry = {"description": "d", "source": "https://example.com/f", "file": "f"}
    with pytest.warns(UserWarning, match="JOEL"):
        assert validate_document({"X": {**entry, "microscope_vendor": "JOEL"}}) == []
    problems = validate_document({"X": {**entry, "microscope_vendor": "Hitachy"}})
    assert problems == [
        "dataset entry: X: microscope_vendor: 'Hitachy' looks like a misspelling of 'Hitachi'"
    ]


def test_check_vendor_tells_a_typo_from_a_new_vendor():
    known = ["Direct Electron", "Gatan"]

    def level(value):
        result = check_vendor(value, known)
        return result[0] if result else None

    assert level("Gatan") is None
    assert level("") is None
    assert level("Direct electron") == "error"
    assert level("Direct Electon") == "error"
    assert level("Nion") == "warning"


def test_vendors_yaml_covers_what_the_datasets_declare():
    for field in ("detector_manufacturer", "microscope_vendor"):
        declared = {spec[field] for _, _, spec in ENTRIES if spec.get(field)}
        assert declared <= set(VENDORS[field])


def _record(**overrides):
    spec = {
        "description": "A description.",
        "source": "https://example.com/files",
        "file": "d.zspy",
    }
    return DatasetMetadata.from_spec({**spec, **overrides})


def test_repr_is_one_short_identifying_line():
    """The generated dataclass repr is ~1000 chars of mostly description, which
    is useless as the output of a bare `ds.metadata` in a notebook."""
    metadata = _record(technique="4D-STEM", size_bytes=12492298)
    text = repr(metadata)
    assert "\n" not in text
    assert len(text) < 100
    assert text == "<DatasetMetadata d.zspy · 4D-STEM · 12.5 MB>"
    assert "A description." not in text


def test_repr_drops_the_parts_it_does_not_have():
    assert repr(_record()) == "<DatasetMetadata d.zspy>"


def test_str_shows_the_record_and_omits_empty_fields():
    metadata = _record(technique="EELS", license="CC-BY-4.0", tags=["One", "Two"])
    text = str(metadata)
    assert "A description." in text
    assert "license: CC-BY-4.0" in text
    assert "tags: One, Two" in text
    assert "checksum" not in text  # not set, so not shown
    assert "camera_length" not in text


def test_str_shows_bytes_and_the_readable_size_together():
    assert "size_bytes: 12492298 (12.5 MB)" in str(_record(size_bytes=12492298))


def test_str_formats_authors_with_affiliations():
    metadata = _record(authors={"Jane Doe": {"affiliation": "Somewhere"}})
    assert "authors: Jane Doe (Somewhere)" in str(metadata)


def test_str_never_breaks_a_url_across_lines():
    """A wrapped URL cannot be copied, so long tokens overrun the width instead."""
    url = "https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets"
    assert url in str(_record(source=url))


def test_str_wraps_a_long_value_under_its_label():
    tags = [f"Tag Number {n}" for n in range(12)]
    lines = str(_record(tags=tags)).splitlines()
    tag_lines = [line for line in lines if "Tag Number" in line]
    assert len(tag_lines) > 1  # wrapped
    assert all(len(line) <= 88 for line in tag_lines)
    assert tag_lines[1].startswith(" " * 8)  # continuation is indented under the label


def test_str_without_a_description():
    text = str(DatasetMetadata(description="", source="https://example.com", file="d.zspy"))
    assert text.startswith("d.zspy\n\n")
    assert "source: https://example.com" in text
