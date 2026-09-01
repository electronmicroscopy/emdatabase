"""Turn a filled-in "New Dataset" issue into a dataset YAML file.

Run by ``.github/workflows/on_new_issue.yml``. The output goes through
``emdatabase.metadata.validate_document`` before it is written - the same check
the test suite and ``emdatabase.new_dataset`` run - so a malformed issue fails
here rather than in the pull request the workflow opens.
"""

import re
import sys
from pathlib import Path

import yaml

from emdatabase.metadata import validate_document
from emdatabase.new_dataset import content_length

FIELDS = {
    "Dataset Name": r"--Dataset Name--\s*(.*)",
    "Author": r"--Author--\s*(.*)",
    "Affiliation": r"--Affiliation--\s*(.*)",
    "URL": r"--URL--\s*(.*)",
    "Checksum": r"--Checksum--\s*(.*)",
    "Description": r"--Description--\s*([\s\S]*?)--Detector Manufacturer--",
    "Detector Manufacturer": r"--Detector Manufacturer--\s*(.*)",
    "Detector Model": r"Detector Model\s*(.*)",
    "Microscope Vendor": r"Microscope Vendor\s*(.*)",
    "Microscope Model": r"Microscope Model\s*(.*)",
    "Accelerating Voltage": r"Accelerating Voltage\s*(.*)",
    "Dataset License": r"Dataset License\s*(.*)",
    "Technique": r"Technique\s*(.*)",
    "Tags": r"Tags\s*(.*)",
}


def clean(value):
    """Trim what GitHub adds around an issue-form answer.

    Answers are separated by ``###`` headings, and the multi-line ones run up
    to the next heading; an optional field left blank comes through as the
    literal ``_No response_``.
    """
    value = value.strip().rstrip("#").strip()
    return "" if value == "_No response_" else value


def parse_issue_body(text):
    data = {}
    for key, pattern in FIELDS.items():
        match = re.search(pattern, text)
        data[key] = clean(match.group(1)) if match else ""
    return data


def build_yaml(data):
    """``(document, dataset_name)`` for a parsed issue."""
    name = re.sub(r"\W+", "", data["Dataset Name"])
    if not name:
        sys.exit("the issue has no dataset name")
    # The form asks for a direct link to the file; the YAML wants the directory
    # and the file name separately.
    url = data["URL"].rstrip("/")
    source, _, filename = url.rpartition("/")
    if not source or not filename:
        sys.exit(f"{data['URL']!r} is not a direct link to a file")

    entry = {
        "description": data["Description"],
        "source": source,
        "checksum": data["Checksum"],
        "file": filename,
        "size_bytes": content_length(url),
        "detector_manufacturer": data["Detector Manufacturer"],
        "detector": data["Detector Model"],
        "microscope_vendor": data["Microscope Vendor"],
        "microscope_model": data["Microscope Model"],
        "voltage": data["Accelerating Voltage"],
        "license": data["Dataset License"],
        "technique": data["Technique"],
        "tags": [t.strip() for t in data["Tags"].split(",") if t.strip()],
    }
    if data["Author"]:
        entry["authors"] = {data["Author"]: {"affiliation": data["Affiliation"] or "Unspecified"}}
    return {name: {k: v for k, v in entry.items() if v not in (None, "", [])}}, name


if __name__ == "__main__":
    issue_file, out_dir = sys.argv[1], Path(sys.argv[2])
    document, dataset_name = build_yaml(parse_issue_body(Path(issue_file).read_text()))
    out_path = out_dir / f"{dataset_name}.yaml"
    problems = validate_document(document, origin=out_path)
    for problem in problems:
        print(problem)
    if problems:
        sys.exit("fix the issue and reopen it")

    with open(out_path, "w") as f:
        f.write("# $schema: ./json-schema.json\n")
        yaml.dump(document, f, sort_keys=False)
    print(f"wrote {out_path}")
