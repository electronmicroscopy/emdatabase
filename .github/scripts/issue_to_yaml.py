"""Turn a filled-in "New Dataset" issue into a dataset YAML file.

Run by ``.github/workflows/on_new_issue.yml``. The entry is assembled by
``emdatabase.new_dataset.build_document``, so the issue route writes the same
keys in the same order as the CLI and the docs form, and it goes through
``emdatabase.metadata.validate_document`` before it is written - the same check
the test suite and ``emdatabase.new_dataset`` run - so a malformed issue fails
here rather than in the pull request the workflow opens.

The form's checksum and size are both optional - the size falls back to what a
HEAD request says - so ``emdatabase.new_dataset.fill_download_fields`` downloads
the file for whichever of the two is still missing before any of that.
"""

import re
import sys
from pathlib import Path

from emdatabase.metadata import validate_document
from emdatabase.new_dataset import (
    as_weights_family,
    build_document,
    content_length,
    fill_download_fields,
    normalize_url,
    split_url,
    version_date,
    write_document,
)

# The form's field labels, with the ``--...--`` markers stripped off.
FIELDS = (
    "Dataset Name",
    "Author",
    "Affiliation",
    "ORCID",
    "URL",
    "File Name",
    "Checksum",
    "Size (bytes)",
    "Description",
    "Detector Manufacturer",
    "Detector Model",
    "Microscope Vendor",
    "Microscope Model",
    "Camera Length",
    "Accelerating Voltage",
    "Dataset License",
    "Technique",
    "DOI",
    "Tags",
    "Kind",
    "Version Date",
    "Model Class",
    "Model Framework",
    "Model quantem",
)


def clean(value):
    """Trim what GitHub adds around an issue-form answer.

    An optional field left blank comes through as the literal ``_No response_``.
    """
    value = value.strip()
    return "" if value == "_No response_" else value


def checked(value):
    """The options ticked in a checkboxes answer, in the order the form lists them.

    GitHub writes a checkboxes field out as a markdown task list - a line
    ``- [x] 4D-STEM`` per ticked option, ``- [ ]`` per one left alone.
    """
    return [
        match.group(1).strip()
        for match in re.finditer(r"^\s*-\s*\[[xX]\]\s*(.+)$", value, flags=re.MULTILINE)
    ]


def parse_issue_body(text):
    """The answers, keyed by field label, for everything the form asks.

    GitHub writes each answer under a ``###`` heading naming the field, so the
    body is split on those headings rather than matched field by field. A
    heading the form no longer has is ignored, and a field the body does not
    carry comes back empty.
    """
    data = {name: "" for name in FIELDS}
    for chunk in re.split(r"^#{1,6}[ \t]*", text, flags=re.MULTILINE)[1:]:
        label, _, value = chunk.partition("\n")
        key = label.strip().strip("-").strip()
        if key in data:
            data[key] = clean(value)
    return data


def build_yaml(data):
    """``(document, dataset_name)`` for a parsed issue."""
    name = re.sub(r"\W+", "", data["Dataset Name"])
    if not name:
        sys.exit("the issue has no dataset name")
    # The form asks for the download link; the YAML wants the directory and the
    # file name separately, and keeps the whole link as `url` only when the file
    # is not served at `source/file`. A Drive share link is rewritten to the
    # download link before either, so the HEAD request below asks about the file
    # rather than the viewer page.
    url = normalize_url(data["URL"].rstrip("/"))
    source, filename, link = split_url(url)
    if not source:
        sys.exit(f"{data['URL']!r} is not a link to a file")
    filename = data["File Name"] or filename
    if not filename:
        sys.exit(f"{data['URL']!r} does not end in a file name; fill in --File Name--")
    # The Add Dataset form's file picker fills the size in from the local copy;
    # without it the server is asked for the file's Content-Length.
    size = data["Size (bytes)"].replace(",", "").replace("_", "").strip()

    entry = {
        "description": data["Description"],
        "source": source,
        "url": link,
        "checksum": data["Checksum"],
        "file": filename,
        "size_bytes": int(size) if size.isdigit() else content_length(url),
        "detector_manufacturer": data["Detector Manufacturer"],
        "detector": data["Detector Model"],
        "microscope_vendor": data["Microscope Vendor"],
        "microscope_model": data["Microscope Model"],
        "camera_length": data["Camera Length"],
        "voltage": data["Accelerating Voltage"],
        "license": data["Dataset License"],
        "technique": checked(data["Technique"]),
        "doi": data["DOI"],
        "tags": [t.strip() for t in data["Tags"].split(",") if t.strip()],
    }
    if data["Author"]:
        author = {"affiliation": data["Affiliation"] or "Unspecified"}
        if data["ORCID"]:
            author["orcid"] = data["ORCID"]
        entry["authors"] = {data["Author"]: author}
    if data["Kind"] == "weights":
        entry["kind"] = "weights"
        model = {
            "class": data["Model Class"],
            "framework": data["Model Framework"],
            "quantem": data["Model quantem"],
        }
        entry["model"] = {k: v for k, v in model.items() if v}
        entry = as_weights_family(entry, data["Version Date"] or version_date())
    return build_document(name, entry), name


def write_yaml(issue_file, out_dir):
    """Parse one issue body and write the entry it describes into ``out_dir``."""
    document, dataset_name = build_yaml(parse_issue_body(Path(issue_file).read_text()))
    out_path = Path(out_dir) / f"{dataset_name}.yaml"
    for line in fill_download_fields(document):
        print(line)
    # A field the issue left blank is missing from the entry rather than at the
    # end of it, so the document is rebuilt into the shipped key order.
    document = {name: build_document(name, entry)[name] for name, entry in document.items()}
    problems = validate_document(document, origin=out_path)
    for problem in problems:
        print(problem)
    if problems:
        sys.exit("fix the issue and reopen it")

    write_document(out_path, document)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    write_yaml(sys.argv[1], Path(sys.argv[2]))
