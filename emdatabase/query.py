"""Querying the catalogue from Python.

The browser widget has always had a search box; this is that search, callable,
returning dataset objects rather than the dicts the widget draws.

The module is ``query`` and not ``search`` so that it cannot collide with the
:func:`search` function it exports: a submodule and a function of the same name
both live in the ``emdatabase`` namespace, and importing the submodule wins.

:func:`search` matches the same lowercased blob that
:func:`emdatabase.catalogue.entry` builds for the widget, by the same rule -
every whitespace-separated term has to appear somewhere - so a query typed into
the widget and the same query passed here select the same datasets. The widget
keeps matching in the browser rather than calling this, because a round trip to
the kernel on every keystroke would make typing lag; what is shared is the blob
and the rule, which is where the two would otherwise drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from emdatabase import catalogue
from emdatabase.downloadable_dataset import DownloadableDataset

#: Fields :func:`filter` accepts. The first group is the dataset's own metadata;
#: ``downloaded`` and ``location`` describe what is on this machine instead.
FILTER_FIELDS = (
    "technique",
    "detector",
    "detector_manufacturer",
    "microscope_vendor",
    "microscope_model",
    "camera_length",
    "voltage",
    "license",
    "doi",
    "tags",
    "authors",
    "downloaded",
    "location",
)


def list_datasets() -> list[DownloadableDataset]:
    """Every dataset in the index, sorted by name.

    Not ``datasets()``: the YAML index used to be a ``datasets`` subpackage,
    and the import machinery overwrites a same-named attribute on the parent the
    moment anything imports it - which Sphinx does, walking every submodule. The
    directory is ``emdatabase/index/`` now and no longer importable; the name
    stays because it is public API.

    >>> import emdatabase
    >>> len(emdatabase.list_datasets()) > 0
    True
    """
    return [ds for _, ds in catalogue.datasets()]


def search(query: str) -> list[DownloadableDataset]:
    """Datasets whose metadata contains every word of ``query``.

    The text searched is everything the widget searches: name, description,
    technique, detector, microscope, voltage, licence, DOI, file name, tags,
    authors and their affiliations. Matching is case-insensitive, and terms may
    match different fields - ``"jeol eels"`` finds EELS datasets taken on a
    JEOL. An empty query returns everything.
    """
    terms = query.lower().split()
    if not terms:
        return list_datasets()
    found = []
    for name, ds in catalogue.datasets():
        blob = catalogue.entry(name, ds)["search"]
        if all(term in blob for term in terms):
            found.append(ds)
    return found


def filter(**criteria: Any) -> list[DownloadableDataset]:  # noqa: A001
    """Datasets matching every one of ``criteria``.

    Fields are those in :data:`FILTER_FIELDS`. String comparisons are exact but
    case-insensitive; ``tags`` and ``authors`` test membership; passing a list
    matches any of its values::

        emdatabase.filter(technique="4D-STEM")
        emdatabase.filter(technique="4D-STEM", tags="Strain")
        emdatabase.filter(microscope_vendor=["JEOL", "Hitachi"])
        emdatabase.filter(downloaded=True)
        emdatabase.filter(location="shared")

    Several criteria are combined with and. An unknown field raises rather than
    being ignored, so a typo cannot quietly return the whole index.

    The name shadows the builtin ``filter`` inside this module, which is why it
    is reached as ``emdatabase.filter``; nothing here needs the builtin.
    """
    unknown = sorted(set(criteria) - set(FILTER_FIELDS))
    if unknown:
        raise TypeError(
            f"unknown filter field(s) {', '.join(repr(k) for k in unknown)}; "
            f"choose from {', '.join(FILTER_FIELDS)}"
        )
    found = []
    for name, ds in catalogue.datasets():
        row = catalogue.entry(name, ds)
        if all(_matches(_value(ds, row, field), wanted) for field, wanted in criteria.items()):
            found.append(ds)
    return found


def _value(ds: DownloadableDataset, row: dict, field: str) -> Any:
    """The value ``field`` is filtered on for one dataset."""
    if field in ("downloaded", "location"):
        return row[field]
    return getattr(ds.metadata, field)


def _matches(value: Any, wanted: Any) -> bool:
    if wanted is None or isinstance(wanted, bool):
        return value == wanted
    wanted_values = [wanted] if isinstance(wanted, str) else list(wanted)
    if isinstance(value, (tuple, list, Mapping)):
        # tags and authors: a dataset matches if it carries any one of them.
        have = {str(v).casefold() for v in value}
        return any(str(w).casefold() in have for w in wanted_values)
    if value is None:
        return False
    return any(str(value).casefold() == str(w).casefold() for w in wanted_values)
