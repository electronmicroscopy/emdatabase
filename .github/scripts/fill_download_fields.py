"""Fill in the ``checksum`` and ``size_bytes`` an index entry is missing.

Run by ``.github/workflows/fill_download_fields.yml`` on a pull request that
touches ``emdatabase/index/``. The docs form and the issue form both let those
two fields be blank - a contributor cannot be asked to md5 a 100 GB file by hand
- while every entry needs both, so the file is downloaded here and whatever is
missing is computed from it by
:func:`~emdatabase.new_dataset.fill_download_fields`.

A file is only written when something was filled in, and only after it passes
:func:`~emdatabase.metadata.validate_document` - the same check the test suite
and ``emdatabase.new_dataset`` run. A link that answers with ``text/html``
served a page rather than the file; nothing is written for it and the run exits
non-zero.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from emdatabase.metadata import (
    INDEX_DIR,
    NON_DATASET_FILES,
    dataset_files,
    validate_document,
)
from emdatabase.new_dataset import build_document, fill_download_fields, write_document


def index_files(index_dir: Path | None, paths: list[Path]) -> list[Path]:
    """Every dataset YAML to fill in: the ones named, or a whole directory.

    ``vendors.yaml`` and the rest of ``index/`` are not dataset collections, so
    they are dropped however they arrived - the workflow passes whichever files
    the pull request changed.
    """
    if paths:
        # A pull request that removes an entry names a file that is gone.
        return [path for path in paths if path.name not in NON_DATASET_FILES and path.exists()]
    if index_dir is None:
        return dataset_files()
    return sorted(p for p in index_dir.rglob("*.y*ml") if p.name not in NON_DATASET_FILES)


def fill_file(path: Path) -> tuple[list[str], bool]:
    """Fill one index file in; ``(summary lines, whether it went cleanly)``.

    The entries are rebuilt through
    :func:`~emdatabase.new_dataset.build_document` before they are written, so a
    field that was missing altogether lands in the shipped key order rather than
    at the end of the entry.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        lines = fill_download_fields(document)
    except (OSError, ValueError) as error:
        return [f"- **{path}**: {error}"], False
    if not lines:
        return [], True

    rewritten = {name: build_document(name, entry)[name] for name, entry in document.items()}
    problems = validate_document(rewritten, origin=path)
    if problems:
        return [f"- **{problem}**" for problem in problems], False
    write_document(path, rewritten)
    return [f"- {line}" for line in lines] + [f"- wrote `{path}`"], True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fill_download_fields.py",
        description="Download each index entry that is missing its checksum or size.",
    )
    parser.add_argument(
        "paths", nargs="*", type=Path, help="dataset YAML to fill in; default is every file"
    )
    parser.add_argument(
        "--index",
        type=Path,
        help=f"directory of dataset YAML to fill in (default {INDEX_DIR})",
    )
    parser.add_argument("--summary", type=Path, help="write a markdown report of the run here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    lines: list[str] = []
    ok = True
    for path in index_files(args.index, args.paths):
        one, one_ok = fill_file(path)
        lines += one
        ok &= one_ok
    if not lines:
        lines = ["Every entry already has its checksum and size."]

    summary = "\n".join(lines)
    print(summary)
    if args.summary:
        args.summary.write_text(f"{summary}\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
