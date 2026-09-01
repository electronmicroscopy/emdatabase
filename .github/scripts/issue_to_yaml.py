"""Turn a filled-in "New Dataset" issue into a dataset YAML file.

Run by ``.github/workflows/on_new_issue.yml``. The output is validated against
``emdatabase/index/json-schema.json`` before it is written, so a malformed
issue fails here rather than in the pull request the workflow opens.
"""

import re
import sys
import urllib.request
from pathlib import Path

import jsonschema
import yaml

from emdatabase.metadata import check_vendor, load_schema, load_vendors

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


def content_length(url):
    """The file's size in bytes, or None if the server will not say."""
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "emdatabase (https://github.com/electronmicroscopy/emdatabase)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            length = response.headers.get("Content-Length")
        return int(length) if length else None
    except Exception:
        return None


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


def report_vendors(entry):
    """Print vendor warnings; exit on a name that is a likely misspelling."""
    vendors = load_vendors()
    failed = False
    for field, known in (
        ("detector_manufacturer", vendors["detector_manufacturer"]),
        ("microscope_vendor", vendors["microscope_vendor"]),
    ):
        result = check_vendor(entry.get(field, ""), known)
        if result is None:
            continue
        level, message = result
        print(f"{level}: {field}: {message}")
        failed = failed or level == "error"
    if failed:
        sys.exit("fix the vendor spelling in the issue and reopen it")


if __name__ == "__main__":
    issue_file, out_dir = sys.argv[1], Path(sys.argv[2])
    document, dataset_name = build_yaml(parse_issue_body(Path(issue_file).read_text()))
    jsonschema.validate(document, load_schema())
    report_vendors(document[dataset_name])

    out_path = out_dir / f"{dataset_name}.yaml"
    with open(out_path, "w") as f:
        f.write("# $schema: ./json-schema.json\n")
        yaml.dump(document, f, sort_keys=False)
    print(f"wrote {out_path}")
