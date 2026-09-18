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

A family whose ``latest`` is a Zenodo record file is handled the other way
round. Those bytes are immutable and permanent, so nothing is downloaded and
nothing is copied to GitHub; retraining publishes a new record under the same
concept record instead, which the file URL cannot show. The script asks the
Zenodo API for the concept's newest record, and a new record serving a file
whose md5 differs becomes a dated version pointing at that record. One serving
the same md5 is not a new state of the weights - a record is versioned whole, so
anything published beside them mints a new id - so only the link moves.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from emdatabase.metadata import (
    INDEX_DIR,
    DatasetMetadata,
    WeightsVersion,
    dataset_files,
    format_size,
    validate_document,
)
from emdatabase.new_dataset import (
    HEADERS,
    build_document,
    download_md5,
    version_date,
    write_document,
)

RELEASE_DOWNLOADS = "https://github.com/electronmicroscopy/emdatabase/releases/download"

# Any host, so a test can serve the API and the file link from localhost.
ZENODO_FILE_PATH = re.compile(r"^/(?:api/)?records/(\d+)/files/([^?]+)")


def asset_url(tag: str, asset: str) -> str:
    """Where an asset uploaded to the archive release is served from."""
    return f"{RELEASE_DOWNLOADS}/{tag}/{asset}"


@dataclass(frozen=True)
class ZenodoLink:
    """A Zenodo record file link, split into the pieces the API needs."""

    base: str
    record_id: str
    key: str

    @property
    def api(self) -> str:
        return f"{self.base}/api/records"

    def file_url(self, record_id: str, key: str) -> str:
        return f"{self.base}/records/{record_id}/files/{urllib.parse.quote(key)}"


def zenodo_link(url: str) -> ZenodoLink | None:
    """The link split up, or ``None`` when it is not a Zenodo record file."""
    parts = urllib.parse.urlsplit(url)
    match = ZENODO_FILE_PATH.match(parts.path)
    if not (parts.scheme and parts.netloc and match):
        return None
    return ZenodoLink(
        base=f"{parts.scheme}://{parts.netloc}",
        record_id=match.group(1),
        key=urllib.parse.unquote(match.group(2)),
    )


def fetch_json(url: str) -> dict[str, Any]:
    """GET one JSON document."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one ``gh`` command; the only place this script shells out."""
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


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
    uploaded: list[str] = field(default_factory=list)
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
        report.uploaded.append(asset)
        upload_asset(options.archive_tag, served.path, asset)


def check_family(
    name: str, entry: dict[str, Any], metadata: DatasetMetadata, options: Options
) -> Report:
    """Download one family's ``latest`` and update ``entry`` in place."""
    report = Report(lines=[f"### {name}"])
    latest = metadata.latest
    assert latest is not None  # the schema requires one of every weights entry

    link = zenodo_link(latest.url)
    if link is not None:
        _check_zenodo(report, entry, metadata, latest, link)
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


def _record_file(record: dict[str, Any], key: str) -> dict[str, Any] | None:
    """The file entry named ``key``, or the only one when the name has changed."""
    files = [item for item in record.get("files") or [] if isinstance(item, dict)]
    for item in files:
        if item.get("key") == key:
            return item
    return files[0] if len(files) == 1 else None


def _date_taken(report: Report, metadata: DatasetMetadata, date: str, checksum: str) -> bool:
    """Whether version ``date`` already holds a different file; a failure if it does."""
    existing = metadata.versions.get(date)
    if existing is None or existing.checksum == checksum:
        return False
    report.ok = False
    report.lines.append(
        f"- **version `{date}` already exists with `{existing.checksum}`**, and the newest file "
        f"is `{checksum}`. Two states of this file share one date; refile the earlier one by "
        "hand under the date it was published."
    )
    return True


def _check_zenodo(
    report: Report,
    entry: dict[str, Any],
    metadata: DatasetMetadata,
    latest: WeightsVersion,
    link: ZenodoLink,
) -> None:
    """Ask the Zenodo API whether this concept has a newer record.

    A record's files never change, so there is nothing to download and nothing
    to archive: the API's md5 is what the link serves, and a dated version
    written for it points straight at that record.

    A newer record is not by itself a newer file. Zenodo versions the whole
    record, so a change to anything in it publishes a new id while the file this
    entry names may be byte for byte what it was; only a checksum that differs
    is a new state of the weights worth a date of its own.
    """
    try:
        record = fetch_json(f"{link.api}/{link.record_id}")
        newest = fetch_json(record["links"]["latest"])
        new_id = str(newest["id"])
        published = datetime.date.fromisoformat(newest["metadata"]["publication_date"][:10])
    except (OSError, KeyError, ValueError) as error:
        report.ok = False
        report.lines.append(f"- **could not read the Zenodo API** for {latest.url}: {error}")
        return

    served = _record_file(newest, link.key)
    if served is None:
        report.ok = False
        report.lines.append(
            f"- **Zenodo record {new_id} has no file `{link.key}`**, and holds "
            f"{len(newest.get('files') or [])} files, so which one replaced it is a guess. "
            "Update `latest` by hand."
        )
        return
    checksum = str(served.get("checksum", ""))
    size_bytes = int(served.get("size") or 0)

    if new_id == link.record_id:
        if latest.checksum and checksum != latest.checksum:
            report.ok = False
            report.lines.append(
                f"- **Zenodo record {new_id} serves `{checksum}`**, and the index has "
                f"`{latest.checksum}`. A record's files do not change, so one of the two is "
                "wrong; nothing was written."
            )
            return
        report.lines.append(f"- unchanged; Zenodo record {new_id} is still the latest version")
        return

    url = link.file_url(new_id, str(served.get("key") or link.key))
    if latest.checksum and checksum == latest.checksum:
        # A newer record is not a newer file. Zenodo versions the whole record,
        # so anything else in it changing - a zip published beside the weights -
        # is a new id while this file stays byte for byte what it was. Only the
        # link moves: a dated version would pin a second date to bytes that
        # already have one.
        report.lines.append(
            f"- unchanged; Zenodo record {new_id} is newer than {link.record_id} but serves "
            f"the same `{checksum}`, so the link moved and no version was filed"
        )
        entry["latest"]["url"] = url
        report.changed = True
        return

    date = published.strftime("%y%m%d")
    if _date_taken(report, metadata, date, checksum):
        return
    report.lines.append(
        f"- new Zenodo record {new_id}: the index has `{latest.checksum}` from record "
        f"{link.record_id}, and the new record serves `{checksum}` "
        f"({format_size(size_bytes)}), filed as version `{date}`"
    )
    pin = {"url": url, "checksum": checksum, "size_bytes": size_bytes}
    entry["latest"] = pin
    entry["versions"][date] = dict(pin)  # a copy, or the YAML would use an anchor
    report.changed = True


def _backfill(
    report: Report,
    options: Options,
    name: str,
    entry: dict[str, Any],
    metadata: DatasetMetadata,
    served: Served,
) -> None:
    """Archive the versions holding these bytes that are still on the source link.

    A version already on Zenodo is left where it is: that record is as permanent
    as the archive release.
    """
    unarchived = [
        date
        for date, version in sorted(metadata.versions.items())
        if version.checksum == served.checksum
        and not version.url.startswith(asset_url(options.archive_tag, ""))
        and zenodo_link(version.url) is None
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
    if _date_taken(report, metadata, date, served.checksum):
        return
    report.lines.append(
        f"- the file changed: the index has `{latest.checksum}` and the link now serves "
        f"`{served.checksum}`, filed as version `{date}`"
    )
    asset = f"{name}_{date}{Path(metadata.file).suffix}"
    _archive(report, options, served, asset)
    entry["latest"]["checksum"] = served.checksum
    entry["latest"]["size_bytes"] = served.size_bytes
    entry["versions"][date] = {
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
        report.uploaded += one.uploaded
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
        default=INDEX_DIR,
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
    uploaded: list[str] = []
    ok = True
    for path in dataset_files(args.index):
        report = check_file(path, options)
        ok &= report.ok
        lines += report.lines
        uploaded += report.uploaded

    summary = "\n".join(lines)
    if uploaded:
        # The upload happens during the run, so a pull request that is closed
        # rather than merged leaves the file in the release with no entry
        # pointing at it. Name them where whoever closes it will see them.
        listed = "\n".join(f"- `{asset}`" for asset in uploaded)
        summary += (
            f"\n\n## Uploaded to the `{options.archive_tag}` release\n\n{listed}\n\n"
            "These were uploaded while the run went, not when this pull request is "
            "merged: closing it unmerged leaves them in the release, to delete by hand."
        )
    print(summary)
    if args.summary and not args.dry_run:
        args.summary.write_text(f"{summary}\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
