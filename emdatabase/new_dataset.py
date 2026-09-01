"""Build a dataset YAML entry from a URL, ready to open a pull request with.

``python -m emdatabase.new_dataset <url>`` takes the direct link to a hosted
file, asks the server how big it is, streams it to a temporary file to get its
md5, prompts for the rest of the metadata and writes
``emdatabase/index/<Name>.yaml``. Nothing is written until the entry passes
:func:`~emdatabase.metadata.validate_document`, which is the same check the
test suite and the issue-form workflow run.

``--kind weights`` describes a model checkpoint instead, and asks for the
version and the model it belongs to.

``--validate PATH`` runs that check on a file you wrote by hand and does
nothing else.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from emdatabase.metadata import (
    INDEX_DIR,
    check_vendor,
    load_vendors,
    validate_document,
    validate_file,
)

HEADERS = {"User-Agent": "emdatabase (https://github.com/electronmicroscopy/emdatabase)"}

# Key order for a written entry, matching the files already in index/.
FIELD_ORDER = (
    "description",
    "source",
    "checksum",
    "file",
    "size_bytes",
    "detector_manufacturer",
    "detector",
    "microscope_vendor",
    "microscope_model",
    "camera_length",
    "voltage",
    "license",
    "technique",
    "doi",
    "tags",
    "authors",
    "kind",
    "version",
    "model",
)


def content_length(url: str) -> int | None:
    """The file's size in bytes, or None if the server will not say.

    A HEAD request, following redirects - Zenodo and GitHub raw both serve the
    bytes from somewhere other than the URL that is quoted.
    """
    request = urllib.request.Request(url, method="HEAD", headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            length = response.headers.get("Content-Length")
        return int(length) if length else None
    except Exception:
        return None


def download_md5(url: str, destination: Path, progressbar: bool = True) -> tuple[str, int]:
    """Stream ``url`` to ``destination``; return its ``(md5 hex, byte count)``.

    The count is the fallback for ``size_bytes`` when the server would not
    answer a HEAD request.
    """
    from tqdm.auto import tqdm

    request = urllib.request.Request(url, headers=HEADERS)
    digest = hashlib.md5()
    downloaded = 0
    with urllib.request.urlopen(request, timeout=60) as response:
        declared = response.headers.get("Content-Length")
        bar = tqdm(
            total=int(declared) if declared else None,
            desc=destination.name,
            unit="B",
            unit_scale=True,
            ascii=sys.platform == "win32",
            disable=not progressbar,
        )
        with destination.open("wb") as handle, bar:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                bar.update(len(chunk))
    return digest.hexdigest(), downloaded


def default_name(filename: str) -> str:
    """An entry name from a file name: ``pd-nip_glass.zspy`` -> ``PdNipGlass``."""
    stem = Path(filename).name.split(".")[0]
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^0-9A-Za-z]+", stem) if p)


def _ask(prompt: str, default: str = "", assume_yes: bool = False) -> str:
    if assume_yes:
        return default
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def _ask_vendor(prompt: str, known: list[str], assume_yes: bool) -> str:
    """Prompt for a vendor name, re-asking on one that is a likely misspelling."""
    if assume_yes:
        return ""
    print(f"  known: {', '.join(known)}")
    while True:
        value = _ask(prompt)
        result = check_vendor(value, known)
        if result is None:
            return value
        level, message = result
        print(f"  {level}: {message}")
        if level != "error":
            return value


def _ask_authors(assume_yes: bool) -> dict[str, dict[str, str]]:
    if assume_yes:
        return {}
    authors: dict[str, dict[str, str]] = {}
    while True:
        name = _ask("author name (blank to finish)")
        if not name:
            return authors
        authors[name] = {"affiliation": _ask("  affiliation") or "Unspecified"}
        orcid = _ask("  ORCID, 0000-0000-0000-0000")
        if orcid:
            authors[name]["orcid"] = orcid


def build_document(name: str, entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{name: entry}`` in the shipped key order, with the empty fields dropped."""
    return {name: {k: entry[k] for k in FIELD_ORDER if entry.get(k) not in (None, "", [], {})}}


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# $schema: ./json-schema.json\n")
        yaml.dump(document, handle, sort_keys=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m emdatabase.new_dataset",
        description="Write a dataset YAML entry for a hosted file.",
    )
    parser.add_argument("url", nargs="?", help="direct link to the hosted file")
    parser.add_argument(
        "--validate", metavar="PATH", help="check an existing dataset YAML and exit"
    )
    parser.add_argument("--name", help="entry name; default is derived from the file name")
    parser.add_argument(
        "--out", type=Path, default=INDEX_DIR, help=f"directory to write to (default {INDEX_DIR})"
    )
    parser.add_argument("--description", help="what the data is; required, and prompted for")
    parser.add_argument("--checksum", help="md5:<32 hex>, to skip the download")
    parser.add_argument(
        "--kind",
        choices=("dataset", "weights"),
        default="dataset",
        help="what the entry hands out (default dataset)",
    )
    parser.add_argument("--yes", action="store_true", help="take the defaults and do not prompt")
    parser.add_argument("--keep", action="store_true", help="keep the downloaded temporary file")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.validate:
        problems = validate_file(args.validate)
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print(f"{args.validate}: valid")
        return 0

    if not args.url:
        parser.error("a URL is required (or --validate PATH)")

    url = args.url.rstrip("/")
    source, _, filename = url.rpartition("/")
    if not source or not filename:
        print(f"{args.url!r} is not a direct link to a file")
        return 1

    name = args.name or _ask("entry name", default_name(filename), args.yes)
    if not name:
        print("the entry needs a name")
        return 1
    out_path = args.out / f"{name}.yaml"
    if out_path.exists() and not args.force:
        print(f"{out_path} already exists; pass --force to overwrite it")
        return 1

    size_bytes = content_length(url)
    checksum = args.checksum
    if checksum is None:
        temporary = Path(tempfile.gettempdir()) / filename
        try:
            digest, downloaded = download_md5(url, temporary)
        except OSError as error:
            print(f"could not download {url}: {error}")
            return 1
        checksum = f"md5:{digest}"
        size_bytes = size_bytes if size_bytes is not None else downloaded
        if args.keep:
            print(f"kept {temporary}")
        else:
            temporary.unlink(missing_ok=True)

    description = args.description or _ask("description", assume_yes=args.yes)
    if not description:
        print("a description is required")
        return 1
    vendors = load_vendors()
    entry: dict[str, Any] = {
        "description": description,
        "source": source,
        "checksum": checksum,
        "file": filename,
        "size_bytes": size_bytes,
        "technique": _ask("technique, e.g. 4D-STEM", assume_yes=args.yes),
        "license": _ask("license, e.g. CC-BY-4.0", assume_yes=args.yes),
        "detector_manufacturer": _ask_vendor(
            "detector manufacturer", vendors["detector_manufacturer"], args.yes
        ),
        "detector": _ask("detector model", assume_yes=args.yes),
        "microscope_vendor": _ask_vendor(
            "microscope vendor", vendors["microscope_vendor"], args.yes
        ),
        "microscope_model": _ask("microscope model", assume_yes=args.yes),
        "voltage": _ask("voltage, e.g. 200 kV", assume_yes=args.yes),
        "camera_length": _ask("camera length, e.g. 100 mm", assume_yes=args.yes),
        "doi": _ask("DOI", assume_yes=args.yes),
        "tags": [t.strip() for t in _ask("tags, comma separated", assume_yes=args.yes).split(",")],
        "authors": _ask_authors(args.yes),
    }
    entry["tags"] = [t for t in entry["tags"] if t]
    if args.kind == "weights":
        entry["kind"] = "weights"
        entry["version"] = _ask("model version, e.g. 3", assume_yes=args.yes)
        model = {
            "class": _ask("model class, e.g. quantem.ml.inr.INR", assume_yes=args.yes),
            "framework": _ask("framework", "torch", args.yes),
            "quantem": _ask('quantem versions, e.g. ">=0.2,<0.3"', assume_yes=args.yes),
        }
        entry["model"] = {k: v for k, v in model.items() if v}

    document = build_document(name, entry)
    problems = validate_document(document, origin=out_path)
    if problems:
        for problem in problems:
            print(problem)
        return 1

    _write(out_path, document)
    print(f"wrote {out_path}")
    print("next: open a pull request adding this file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
