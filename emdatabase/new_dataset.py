"""Build a dataset YAML entry from a URL, ready to open a pull request with.

``python -m emdatabase.new_dataset <url>`` takes the link to a hosted file,
asks the server how big it is, streams it to a temporary file to get its md5,
prompts for the rest of the metadata and writes
``emdatabase/index/<Name>.yaml``. A link that does not end in the file name - a
Google Drive link, or anything else with a query string - is written out as
``url``, with the file name taken from the server. A Google Drive share link is
rewritten to the ``uc?export=download&id=`` link that serves the file. Nothing is written until the
entry passes :func:`~emdatabase.metadata.validate_document`, which is the same
check the test suite and the issue-form workflow run.

``--kind weights`` describes a model checkpoint instead, and asks for the model
it belongs to. A weights entry is a family: the link becomes both its ``latest``
and a version dated today, so the entry starts out pinned to what is published
now and keeps that state when the link moves on. ``--version-date YYMMDD`` files
that version under another date.

``--validate PATH`` runs that check on a file you wrote by hand and does
nothing else.

:func:`fill_download_fields` is the same download from the other end: it takes a
parsed entry that is missing its ``checksum`` or ``size_bytes`` and fills them
in. The issue route and ``.github/workflows/fill_download_fields.yml`` run it
over an entry the forms left blank.
"""

from __future__ import annotations

import argparse
import datetime
import email.message
import hashlib
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from emdatabase.metadata import (
    INDEX_DIR,
    check_vendor,
    load_vendors,
    techniques,
    validate_document,
    validate_file,
)

HEADERS = {"User-Agent": "emdatabase (https://github.com/electronmicroscopy/emdatabase)"}

# Key order for a written entry, matching the files already in index/.
FIELD_ORDER = (
    "description",
    "source",
    "url",
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
    "model",
    "latest",
    "versions",
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


def _served_name(headers: email.message.Message) -> str:
    """The file name a response's ``Content-Disposition`` gives, or ``""``.

    It is the only thing that names the file behind a link that does not end in
    it, which is how Google Drive and other query-string links serve.
    """
    message = email.message.Message()
    message["Content-Disposition"] = headers.get("Content-Disposition", "")
    return Path(message.get_filename() or "").name


def download_md5(
    url: str, destination: Path, progressbar: bool = True
) -> tuple[str, int, str, str]:
    """Stream ``url`` to ``destination``; return ``(md5, bytes, name, type)``.

    The count is the fallback for ``size_bytes`` when the server would not
    answer a HEAD request, and the name is what the server called the file, if
    it said - redirects are followed, so all of it comes from wherever the bytes
    actually are. The type is the ``Content-Type`` header, verbatim: a host that
    answers a download link with ``text/html`` served a page, not the file.
    """
    from tqdm.auto import tqdm

    request = urllib.request.Request(url, headers=HEADERS)
    digest = hashlib.md5()
    downloaded = 0
    with urllib.request.urlopen(request, timeout=60) as response:
        served = _served_name(response.headers)
        content_type = response.headers.get("Content-Type", "")
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
    return digest.hexdigest(), downloaded, served, content_type


_ZENODO_DOWNLOAD = re.compile(
    r"^(https?://(?:sandbox\.)?zenodo\.org/records/\d+/files/[^?#]+)\?download=1$", re.IGNORECASE
)
_DRIVE_FILE = re.compile(r"^https?://drive\.google\.com/file/d/([^/?#]+)", re.IGNORECASE)
_DRIVE_OPEN = re.compile(
    r"^https?://drive\.google\.com/open\?(?:[^#]*&)?id=([^&#]+)", re.IGNORECASE
)


def normalize_url(url: str) -> str:
    """A share link as the link that serves the file; any other link unchanged.

    Zenodo's copy-link button appends ``?download=1``, which the bare file link
    does not need; it is dropped so the link splits into ``source`` and ``file``
    like the hand-written Zenodo entries.

    The link Drive's share button hands out - ``file/d/<id>/view`` or
    ``open?id=<id>`` - serves the viewer page, not the file. It carries the same
    id as ``uc?export=download&id=<id>``, which serves the bytes, so it is
    rewritten to that rather than refused.
    """
    zenodo = _ZENODO_DOWNLOAD.match(url)
    if zenodo is not None:
        return zenodo.group(1)
    match = _DRIVE_FILE.match(url) or _DRIVE_OPEN.match(url)
    if match is None:
        return url
    return f"https://drive.google.com/uc?export=download&id={match.group(1)}"


def split_url(url: str) -> tuple[str, str, str]:
    """``(source, file, url)`` for a link, with ``url`` empty when unneeded.

    A link ending in the file name splits into the directory it is served from
    and the name, which is how nearly every entry is written. One with a query
    string, or with no extension on its last segment, names nothing: it is kept
    whole as ``url``, ``source`` is the host it points at, and the file name has
    to come from the server. A Google Drive share link is normalised first, so
    what is written out is the link that serves the file.
    """
    url = normalize_url(url)
    parts = urllib.parse.urlsplit(url)
    if not (parts.scheme and parts.netloc):
        return "", "", ""
    last = parts.path.rpartition("/")[2]
    if parts.query or "." not in last:
        return f"{parts.scheme}://{parts.netloc}", "", url
    source, _, filename = url.rpartition("/")
    return source, filename, ""


def default_name(filename: str) -> str:
    """An entry name from a file name: ``pd-nip_glass.zspy`` -> ``PdNipGlass``."""
    stem = Path(filename).name.split(".")[0]
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^0-9A-Za-z]+", stem) if p)


def _ask(prompt: str, default: str = "", assume_yes: bool = False) -> str:
    if assume_yes:
        return default
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def _ask_list(prompt: str, assume_yes: bool, known: Sequence[str] | None = None) -> list[str]:
    """A comma-separated answer as a list, with the blanks dropped.

    ``known`` makes it a closed vocabulary: the options are printed first, and
    an answer holding anything else is asked for again.
    """
    if known is not None and not assume_yes:
        print(f"  one or more of: {', '.join(known)}")
    while True:
        answer = _ask(prompt, assume_yes=assume_yes)
        chosen = [item.strip() for item in answer.split(",") if item.strip()]
        if known is None or assume_yes:
            return chosen
        unknown = [item for item in chosen if item not in known]
        if not unknown:
            return chosen
        print(
            f"  error: {', '.join(repr(item) for item in unknown)} "
            f"not on the list; choose from: {', '.join(known)}"
        )


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
    """``{name: entry}`` in the shipped key order, with the empty fields dropped.

    ``kind`` is always written, ``dataset`` included: the schema defaults it so
    that an old third-party file still loads, but everything generated here says
    which it is.
    """
    entry = {**entry, "kind": entry.get("kind") or "dataset"}
    return {name: {k: entry[k] for k in FIELD_ORDER if entry.get(k) not in (None, "", [], {})}}


def version_date() -> str:
    """Today as ``YYMMDD``, the label a new weights version is filed under."""
    return datetime.date.today().strftime("%y%m%d")


def as_weights_family(entry: dict[str, Any], date: str) -> dict[str, Any]:
    """The entry with its download fields moved into ``latest`` and one version.

    A weights entry is a family: ``latest`` follows the published link, and a
    dated version pins each state that link has served. A new entry is both,
    from the same file. The top-level ``url``, ``checksum`` and ``size_bytes``
    are cleared, so that each of those facts is written in one place.
    """
    pin = {
        "url": entry.get("url") or f"{entry['source']}/{entry['file']}",
        "checksum": entry.get("checksum"),
        "size_bytes": entry.get("size_bytes"),
    }
    pin = {key: value for key, value in pin.items() if value}
    return {
        **entry,
        "url": None,
        "checksum": None,
        "size_bytes": None,
        "latest": pin,
        "versions": {date: dict(pin)},
    }


def _fill_pin(label: str, pin: dict[str, Any], url: str) -> list[str]:
    """Download ``url`` for whichever of the two fields ``pin`` is missing."""
    if pin.get("checksum") and pin.get("size_bytes"):
        return []
    with tempfile.TemporaryDirectory() as directory:
        digest, downloaded, _, content_type = download_md5(
            url, Path(directory) / "download", progressbar=False
        )
    if content_type.startswith("text/html"):
        raise ValueError(
            f"{label}: {url} answered with {content_type}, so it served a page rather than the "
            "file - a Google Drive viewer page, or a 404 dressed up as HTML. Fix the link."
        )
    filled = []
    if not pin.get("checksum"):
        pin["checksum"] = f"md5:{digest}"
        filled.append(f"checksum {pin['checksum']}")
    if not pin.get("size_bytes"):
        pin["size_bytes"] = downloaded
        filled.append(f"size_bytes {downloaded}")
    return [f"{label}: filled in {' and '.join(filled)} from {url}"]


def fill_download_fields(document: dict[str, Any]) -> list[str]:
    """Fill in every missing ``checksum`` and ``size_bytes`` in a parsed document.

    The docs form and the issue form both let those two fields be blank, and
    every entry needs both, so whatever is missing is computed here by
    downloading the file. A weights family carries them per pin rather than at
    the top level, so ``latest`` and each dated version is followed on its own
    link. An entry that already has both is not downloaded.

    The document is filled in place and nothing is written - the caller decides
    where the result goes. The lines returned say what was filled, and are empty
    when nothing was.
    """
    lines: list[str] = []
    for name, entry in document.items():
        if entry.get("kind") == "weights":
            pins = [(f"{name} latest", entry.get("latest"))]
            pins += [
                (f"{name} version {date}", pin)
                for date, pin in (entry.get("versions") or {}).items()
            ]
            for label, pin in pins:
                if pin:
                    lines += _fill_pin(label, pin, pin.get("url", ""))
        else:
            url = entry.get("url") or f"{entry.get('source', '')}/{entry.get('file', '')}"
            lines += _fill_pin(name, entry, url)
    return lines


class _IndexDumper(yaml.SafeDumper):
    """PyYAML output in the house style of the hand-written index files.

    Sequences are indented under their key, a scalar that needs quoting gets
    double quotes, and a long description is a folded block.
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)

    def choose_scalar_style(self) -> str:
        style = super().choose_scalar_style()
        return '"' if style == "'" else style


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = ">" if " " in data and (len(data) > 80 or "\n" in data) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_IndexDumper.add_representer(str, _represent_str)


def write_document(path: Path, document: dict[str, Any]) -> None:
    """Write ``document`` to ``path`` as YAML, with the schema header on top."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# $schema: ./json-schema.json\n")
        yaml.dump(document, handle, Dumper=_IndexDumper, sort_keys=False, width=72)


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
        help="what the entry hands out (default dataset); weights writes a family",
    )
    parser.add_argument(
        "--version-date",
        metavar="YYMMDD",
        default=version_date(),
        help="the date the weights version is filed under (default today)",
    )
    parser.add_argument("--yes", action="store_true", help="take the defaults and do not prompt")
    parser.add_argument("--keep", action="store_true", help="keep the downloaded temporary file")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    return parser


def _entry_target(args: argparse.Namespace, filename: str) -> tuple[str, Path] | None:
    """``(entry name, path to write)``, or ``None`` after printing why not."""
    name = args.name or _ask("entry name", default_name(filename), args.yes)
    if not name:
        print("the entry needs a name")
        return None
    out_path = args.out / f"{name}.yaml"
    if out_path.exists() and not args.force:
        print(f"{out_path} already exists; pass --force to overwrite it")
        return None
    return name, out_path


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d{6}", args.version_date):
        parser.error("--version-date takes a YYMMDD date, e.g. 260902")

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

    url = normalize_url(args.url.rstrip("/"))
    source, filename, link = split_url(url)
    if not source:
        print(f"{args.url!r} is not a link to a file")
        return 1

    # The name is only known up front for a link that ends in it; otherwise the
    # server says, once the download has started.
    target = _entry_target(args, filename) if filename else None
    if filename and target is None:
        return 1

    size_bytes = content_length(url)
    checksum = args.checksum
    if checksum is None:
        temporary = Path(tempfile.gettempdir()) / (filename or "download")
        try:
            digest, downloaded, served, _ = download_md5(url, temporary)
        except OSError as error:
            print(f"could not download {url}: {error}")
            return 1
        checksum = f"md5:{digest}"
        size_bytes = size_bytes if size_bytes is not None else downloaded
        if not filename and served:
            filename = served
            temporary = temporary.rename(temporary.with_name(filename))
        if args.keep:
            print(f"kept {temporary}")
        else:
            temporary.unlink(missing_ok=True)

    if not filename:
        filename = _ask("file name the download should be saved as", assume_yes=args.yes)
        if not filename:
            print(f"{url} does not name a file, and neither did the server")
            return 1
    if target is None:
        target = _entry_target(args, filename)
        if target is None:
            return 1
    name, out_path = target

    description = args.description or _ask("description", assume_yes=args.yes)
    if not description:
        print("a description is required")
        return 1
    vendors = load_vendors()
    entry: dict[str, Any] = {
        "description": description,
        "source": source,
        "url": link,
        "checksum": checksum,
        "file": filename,
        "size_bytes": size_bytes,
        "technique": _ask_list("techniques, comma separated", args.yes, techniques()),
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
        "tags": _ask_list("tags, comma separated", args.yes),
        "authors": _ask_authors(args.yes),
    }
    if args.kind == "weights":
        entry["kind"] = "weights"
        model = {
            "class": _ask("model class, e.g. quantem.ml.inr.INR", assume_yes=args.yes),
            "framework": _ask("framework", "torch", args.yes),
            "quantem": _ask('quantem versions, e.g. ">=0.2,<0.3"', assume_yes=args.yes),
        }
        entry["model"] = {k: v for k, v in model.items() if v}
        entry = as_weights_family(entry, args.version_date)

    document = build_document(name, entry)
    problems = validate_document(document, origin=out_path)
    if problems:
        for problem in problems:
            print(problem)
        return 1

    write_document(out_path, document)
    print(f"wrote {out_path}")
    print("next: open a pull request adding this file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
