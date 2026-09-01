"""A browsable catalogue of the datasets, grouped by technique.

This is the data model behind :func:`emdatabase.browse`: it turns the
``emdatabase.data`` classes into rows a UI can draw - grouped by technique,
marked downloaded or not, each carrying the metadata a user hovers to read. It
downloads nothing and opens no files, so it is cheap enough to rebuild on every
render (the one thing that changes underfoot is which files are on disk, which
is a single ``Path.exists`` per dataset).
"""

from __future__ import annotations

import inspect
import warnings
from pathlib import Path

from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.metadata import DatasetMetadata

# Techniques in the order the browser should show them - the modalities the
# collection is built around first, then anything else alphabetically.
TECHNIQUE_ORDER = ("4D-STEM", "EELS", "EDS", "EBSD", "STEM", "In-situ TEM", "Cryo-EM")


def datasets() -> list[tuple[str, DownloadableDataset]]:
    """``(name, dataset)`` for every dataset ``emdatabase.data`` exposes.

    Filtered by ``issubclass`` so the base class and incidental imports in the
    module namespace stay out; sorted by name for a stable order.
    """
    import emdatabase.data as data

    out: list[tuple[str, DownloadableDataset]] = []
    for name in getattr(data, "__all__", None) or dir(data):
        if name.startswith("_"):
            continue
        obj = getattr(data, name, None)
        if (
            not inspect.isclass(obj)
            or obj is DownloadableDataset
            or not issubclass(obj, DownloadableDataset)
        ):
            continue
        try:
            out.append((name, obj()))
        except TypeError as error:
            # from_spec rejects a malformed entry. emdatabase.data validates at
            # import so this should be unreachable, but a dataset silently
            # missing from the browser is the wrong way to find out otherwise.
            warnings.warn(f"skipping dataset {name!r}: {error}", stacklevel=2)
    return sorted(out, key=lambda kv: kv[0].lower())


def resolve(name: str) -> DownloadableDataset | None:
    """The dataset instance for a catalogue name, or ``None``."""
    import emdatabase.data as data

    obj = getattr(data, str(name), None)
    if not inspect.isclass(obj) or not issubclass(obj, DownloadableDataset):
        return None
    return obj()


def _technique(md: DatasetMetadata) -> str:
    return (md.technique or "Other").strip() or "Other"


def _join(*parts) -> str:
    return " ".join(str(p).strip() for p in parts if p and str(p).strip())


def _location(path: Path | None) -> str | None:
    """Which search location a downloaded file came from: the name of the store
    holding it, or "user" for the user's own data directory."""
    if path is None:
        return None
    from emdatabase import config

    parent = path.resolve().parent
    for name, directory in config.stores().items():
        if parent == directory.resolve():
            return name
    return "user"


def entry(name: str, ds: DownloadableDataset) -> dict:
    """One catalogue row - everything the browser draws for a dataset."""
    md = ds.metadata
    try:
        found = ds.filepaths()
    except Exception:
        found = []
    path = found[0] if found else None
    # The copy in the user's own directory, which may sit behind a store's in
    # the search order. It is the only copy delete() will touch, so the widgets
    # need it to know whether there is anything to offer deleting.
    user_path = next((p for p in found if _location(p) == "user"), None)
    row = {
        "name": name,
        "technique": _technique(md),
        "size": md.size,
        "downloaded": path is not None,
        "location": _location(path),
        "path": str(path) if path else "",
        "user_path": str(user_path) if user_path else "",
        "description": md.description,
        "detector": _join(md.detector_manufacturer, md.detector),
        "microscope": _join(md.microscope_vendor, md.microscope_model),
        "voltage": md.voltage or "",
        "tags": list(md.tags),
        "authors": list(md.authors),
        "license": md.license or "",
        "doi": md.doi or "",
        "source": md.source,
        "file": md.file,
    }
    # One lowercased blob the search box matches against, so a query like
    # "Carter Francis" (an author) or "Direct Electron" (an affiliation) finds
    # every dataset it touches - not just the name.
    searchable = [
        name,
        row["technique"],
        row["description"],
        row["detector"],
        row["microscope"],
        row["voltage"],
        row["license"],
        row["doi"],
        row["file"],
        " ".join(row["tags"]),
        " ".join(row["authors"]),
        " ".join(a.affiliation for a in md.authors.values()),
    ]
    row["search"] = " ".join(str(s) for s in searchable if s).lower()
    return row


def _order(technique: str):
    try:
        return (0, TECHNIQUE_ORDER.index(technique))
    except ValueError:
        return (1, technique.lower())


def catalogue() -> dict:
    """The whole browser payload, grouped by technique.

    ``{"data_dir", "stores", "groups": [{"technique", "items"}], "n_downloaded",
    "n_total"}`` - one group per technique in :data:`TECHNIQUE_ORDER`, then any
    others alphabetically.
    """
    from emdatabase import config

    items = [entry(name, ds) for name, ds in datasets()]
    by_tech: dict[str, list[dict]] = {}
    for it in items:
        by_tech.setdefault(it["technique"], []).append(it)
    groups = [{"technique": t, "items": by_tech[t]} for t in sorted(by_tech, key=_order)]
    return {
        "data_dir": str(config.data_dir()),
        "stores": {name: str(path) for name, path in config.stores().items()},
        "groups": groups,
        "n_downloaded": sum(1 for it in items if it["downloaded"]),
        "n_total": len(items),
    }
