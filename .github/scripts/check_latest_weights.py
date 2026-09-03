"""Follow each weights family's ``latest`` link and archive what it serves.

Run weekly by ``.github/workflows/check_weights.yml``. A weights entry's
``latest`` is the model's published link, which is meant to move: the file
behind it is replaced when the model is retrained, and the old bytes are gone.
This script downloads each one, compares the md5 with the index and keeps
whatever it finds:

* unchanged, but the dated version with that checksum still points at the
  contributor's link - upload the file to the archive release and rewrite that
  version's ``url``. This is what archives a newly contributed entry.
* changed - upload the file under today's date, add ``versions[<today>]`` and
  update ``latest``'s checksum and size.

Both write the family YAML back through
``emdatabase.new_dataset.write_document``, so the workflow can open a pull
request with the result. A file over ``--threshold-mb`` is not uploaded: it goes
to ``--keep-dir`` for the workflow to publish as a run artifact, the version is
still written pointing at the asset URL, and the summary carries the ``gh``
command a maintainer runs by hand.

A link that answers with ``text/html`` served a page - a Google Drive
virus-scan interstitial, or a 404 dressed up as HTML - not the file. Nothing is
archived for it and the run exits non-zero.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from emdatabase.metadata import (
    INDEX_DIR,
    NON_DATASET_FILES,
    DatasetMetadata,
    WeightsVersion,
    dataset_files,
    format_size,
    validate_document,
)
from emdatabase.new_dataset import build_document, download_md5, version_date, write_document

RELEASE_DOWNLOADS = "https://github.com/electronmicroscopy/emdatabase/releases/download"


def asset_url(tag: str, asset: str) -> str:
    """Where an asset uploaded to the archive release is served from."""
    return f"{RELEASE_DOWNLOADS}/{tag}/{asset}"


def is_archived(url: str, tag: str) -> bool:
    """Whether a version's link already points into the archive release."""
    return url.startswith(f"{RELEASE_DOWNLOADS}/{tag}/")


def index_files(index_dir: Path | None) -> list[Path]:
    """Every dataset YAML to check, sorted by name."""
    if index_dir is None:
        return dataset_files()
    return sorted(p for p in index_dir.rglob("*.y*ml") if p.name not in NON_DATASET_FILES)


def run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one ``gh`` command; the only place this script shells out.

    ``gh`` reads ``GH_TOKEN``, while a workflow hands the job ``GITHUB_TOKEN``.
    """
    env = os.environ.copy()
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    if token:
        env["GH_TOKEN"] = token
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True, env=env)


def upload_asset(tag: str, path: Path, asset: str) -> None:
    """Upload ``path`` to the archive release as ``asset``, creating the release."""
    if run_gh(["release", "view", tag], check=False).returncode != 0:
        run_gh(
            [
                "release",
                "create",
                tag,
                "--title",
                "Weights archive",
                "--notes",
                "Dated copies of every weights family's latest file.",
            ]
        )
    # gh names the asset after the file; "path#name" only sets the display label.
    with tempfile.TemporaryDirectory() as staging:
        named = Path(staging) / asset
        shutil.copyfile(path, named)
        run_gh(["release", "upload", tag, str(named), "--clobber"])


@dataclass
class Options:
    """One run's settings, as the per-family work needs them."""

    archive_tag: str
    threshold_bytes: int
    keep_dir: Path
    dry_run: bool


@dataclass
class Served:
    """What the ``latest`` link actually handed over on this run."""

    path: Path
    checksum: str
    size_bytes: int


@dataclass
class Report:
    """What happened to one family: summary lines, and whether it needs writing."""

    lines: list[str] = field(default_factory=list)
    changed: bool = False
    ok: bool = True


def _archive(report: Report, options: Options, served: Served, asset: str) -> None:
    """Put one file in the archive release, or in ``--keep-dir`` if it is too big."""
    if served.size_bytes > options.threshold_bytes:
        kept = options.keep_dir / asset
        command = f"gh release upload {options.archive_tag} {kept} --clobber"
        report.lines.append(
            f"- `{asset}` is {format_size(served.size_bytes)}, over the "
            f"{format_size(options.threshold_bytes)} threshold: it is attached to the workflow "
            f"run instead. Download it and upload it by hand:\n\n      {command}\n"
        )
        if not options.dry_run:
            options.keep_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(served.path, kept)
        return
    verb = "would upload" if options.dry_run else "uploaded"
    report.lines.append(f"- {verb} `{asset}` to the `{options.archive_tag}` release")
    if not options.dry_run:
        upload_asset(options.archive_tag, served.path, asset)


def check_family(
    name: str, entry: dict[str, Any], metadata: DatasetMetadata, options: Options
) -> Report:
    """Download one family's ``latest`` and update ``entry`` in place."""
    report = Report(lines=[f"### {name}"])
    latest = metadata.latest
    if latest is None:
        report.lines.append("- no `latest` link, so there is nothing to follow")
        return report

    with tempfile.TemporaryDirectory() as directory:
        downloaded = Path(directory) / metadata.file
        try:
            digest, size_bytes, _, content_type = download_md5(
                latest.url, downloaded, progressbar=False
            )
        except OSError as error:
            report.ok = False
            report.lines.append(f"- **could not download** {latest.url}: {error}")
            return report
        if content_type.startswith("text/html"):
            report.ok = False
            report.lines.append(
                f"- **{latest.url} answered with `{content_type}`**, so it served a page rather "
                "than the file. Nothing was archived; fix the link."
            )
            return report

        served = Served(downloaded, f"md5:{digest}", size_bytes)
        report.lines.append(
            f"- `latest` serves `{served.checksum}` ({format_size(size_bytes)}) from {latest.url}"
        )
        if served.checksum == latest.checksum:
            _backfill(report, options, name, entry, metadata, served)
        else:
            _new_version(report, options, name, entry, metadata, latest, served)
    return report


def _backfill(
    report: Report,
    options: Options,
    name: str,
    entry: dict[str, Any],
    metadata: DatasetMetadata,
    served: Served,
) -> None:
    """Archive the versions holding these bytes that are still on the source link."""
    unarchived = [
        date
        for date, version in sorted(metadata.versions.items())
        if version.checksum == served.checksum
        and not is_archived(version.url, options.archive_tag)
    ]
    if not unarchived:
        report.lines.append("- unchanged, and already archived")
        return
    for date in unarchived:
        asset = f"{name}_{date}{Path(metadata.file).suffix}"
        report.lines.append(f"- unchanged; version `{date}` was still on the source link")
        _archive(report, options, served, asset)
        entry["versions"][date]["url"] = asset_url(options.archive_tag, asset)
        report.changed = True


def _new_version(
    report: Report,
    options: Options,
    name: str,
    entry: dict[str, Any],
    metadata: DatasetMetadata,
    latest: WeightsVersion,
    served: Served,
) -> None:
    """Record what the link serves now as a version dated today."""
    date = version_date()
    existing = metadata.versions.get(date)
    if existing is not None and existing.checksum != served.checksum:
        report.ok = False
        report.lines.append(
            f"- **version `{date}` already exists with `{existing.checksum}`**, and the link now "
            f"serves `{served.checksum}`. Two states of this file share one date; archive the "
            "earlier one by hand and file it under the date it was published."
        )
        return
    report.lines.append(
        f"- the file changed: the index has `{latest.checksum}` and the link now serves "
        f"`{served.checksum}`, filed as version `{date}`"
    )
    asset = f"{name}_{date}{Path(metadata.file).suffix}"
    _archive(report, options, served, asset)
    entry["latest"]["checksum"] = served.checksum
    entry["latest"]["size_bytes"] = served.size_bytes
    entry.setdefault("versions", {})[date] = {
        "url": asset_url(options.archive_tag, asset),
        "checksum": served.checksum,
        "size_bytes": served.size_bytes,
    }
    report.changed = True


def check_file(path: Path, options: Options) -> Report:
    """Check every weights family in one index file, rewriting it if any moved."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    report = Report()
    for name, entry in document.items():
        metadata = DatasetMetadata.from_spec(entry, origin=path)
        if metadata.kind != "weights":
            continue
        one = check_family(name, entry, metadata, options)
        report.lines += one.lines
        report.changed |= one.changed
        report.ok &= one.ok
    if not report.changed:
        return report

    rewritten = {name: build_document(name, entry)[name] for name, entry in document.items()}
    problems = validate_document(rewritten, origin=path)
    if problems:
        report.ok = False
        report.lines += [f"- **{problem}**" for problem in problems]
        return report
    if not options.dry_run:
        write_document(path, rewritten)
    report.lines.append(f"- {'would rewrite' if options.dry_run else 'wrote'} `{path}`")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_latest_weights.py",
        description="Archive what each weights family's latest link serves now.",
    )
    parser.add_argument(
        "--archive-tag",
        default="weights-archive",
        help="the release dated copies are uploaded to (default weights-archive)",
    )
    parser.add_argument(
        "--threshold-mb",
        type=float,
        default=500,
        help="above this a file is kept for a maintainer instead of uploaded (default 500)",
    )
    parser.add_argument(
        "--index",
        type=Path,
        help=f"directory of dataset YAML to check (default {INDEX_DIR})",
    )
    parser.add_argument("--summary", type=Path, help="write a markdown report of the run here")
    parser.add_argument(
        "--keep-dir",
        type=Path,
        default=Path("oversize"),
        help="where a file too big to upload is left (default oversize/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would happen; write and upload nothing"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    options = Options(
        archive_tag=args.archive_tag,
        threshold_bytes=int(args.threshold_mb * 1000 * 1000),
        keep_dir=args.keep_dir,
        dry_run=args.dry_run,
    )

    lines: list[str] = []
    ok = True
    for path in index_files(args.index):
        report = check_file(path, options)
        ok &= report.ok
        lines += report.lines
    if not lines:
        lines = ["No weights families in the index."]

    summary = "\n".join(lines)
    print(summary)
    if args.summary and not args.dry_run:
        args.summary.write_text(f"{summary}\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
