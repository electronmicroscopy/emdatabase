"""The dataset record, typed.

``index/json-schema.json`` closes the dataset entry with
``additionalProperties: false``, so an entry is a fixed set of fields rather
than an open bag. :class:`DatasetMetadata` is that set, and
:meth:`DatasetMetadata.from_spec` is the only way one is built: it turns a
parsed YAML mapping into the record and refuses anything the schema would.

This module also owns the small amount of shared knowledge about where the
dataset files live - :func:`dataset_files`, :func:`load_schema`,
:func:`load_vendors` - so the loader, the stub generator, the docs form and the
tests all read the same directory the same way, and the one check a candidate
file has to pass - :func:`validate_document`, :func:`validate_file` - so the
test suite, the issue-form workflow and ``emdatabase.new_dataset`` accept and
reject exactly the same files.
"""

from __future__ import annotations

import difflib
import textwrap
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

INDEX_DIR = Path(__file__).parent / "index"
SCHEMA_PATH = INDEX_DIR / "json-schema.json"
VENDORS_PATH = INDEX_DIR / "vendors.yaml"
TEMPLATE_PATH = INDEX_DIR / "TEMPLATE.yaml"

# Files in index/ that are not dataset collections.
NON_DATASET_FILES = frozenset({VENDORS_PATH.name, TEMPLATE_PATH.name})

REQUIRED_FIELDS = ("description", "source", "file")

# Wrap width for __str__; narrow enough to stay readable in a notebook cell.
_STR_WIDTH = 88


def dataset_files() -> list[Path]:
    """Every dataset collection YAML, sorted by name."""
    return sorted(p for p in INDEX_DIR.rglob("*.y*ml") if p.name not in NON_DATASET_FILES)


def load_schema() -> dict[str, Any]:
    """The JSON schema the dataset YAML is validated against."""
    import json

    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_vendors() -> dict[str, list[str]]:
    """The canonical vendor and detector-manufacturer names.

    Suggestions, not a closed list - see :func:`check_vendor`.
    """
    return yaml.safe_load(VENDORS_PATH.read_text(encoding="utf-8"))


def check_vendor(value: str, known: Iterable[str], cutoff: float = 0.8) -> tuple[str, str] | None:
    """``(level, message)`` for a vendor string, or ``None`` if it is known.

    A name close to a known one is a spelling mistake and is an ``"error"``;
    one that is nothing like any of them is a genuinely new vendor and is a
    ``"warning"`` asking for it to be added to ``vendors.yaml``. A hard list
    would fail the new vendor and block a contributor who has done nothing
    wrong, so only the case that is always a mistake fails.

    Similarity is the check's weak point on short names - ``"JOEL"`` for
    ``"JEOL"`` scores too low to be called a typo and comes back as a warning.
    """
    known = list(known)
    if not value or value in known:
        return None
    folded = {_fold(k): k for k in known}
    if _fold(value) in folded:
        return ("error", f"{value!r} should be spelled {folded[_fold(value)]!r}")
    close = difflib.get_close_matches(value, known, n=1, cutoff=cutoff)
    if close:
        return ("error", f"{value!r} looks like a misspelling of {close[0]!r}")
    return ("warning", f"{value!r} is not in vendors.yaml; add it there if it is a new vendor")


def _fold(value: str) -> str:
    return "".join(value.split()).casefold()


def validate_document(
    document: Mapping[str, Any], *, origin: Path | str | None = None
) -> list[str]:
    """Everything wrong with a parsed dataset YAML document, as readable lines.

    An empty list means the document is valid. The schema is the first check
    and the vendor names are the second: a name close to a known one is a
    misspelling and is listed as a problem, while one that is nothing like any
    of them is a new vendor and goes out through :mod:`warnings` instead.

    Nothing is printed and nothing is raised for a bad document - the caller
    decides whether a problem is a failed test, a comment on an issue or a
    non-zero exit.
    """
    try:
        from jsonschema.validators import validator_for
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError(
            "validating a dataset YAML needs jsonschema: pip install emdatabase[dev]"
        ) from error

    schema = load_schema()
    validator = validator_for(schema)(schema)
    problems = [
        f"{_where(origin)}: {'.'.join(str(p) for p in error.absolute_path) or 'document'}: "
        f"{error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]

    vendors = load_vendors()
    for name, spec in document.items():
        if not isinstance(spec, Mapping):
            continue
        for name_field, known in (
            ("detector_manufacturer", vendors["detector_manufacturer"]),
            ("microscope_vendor", vendors["microscope_vendor"]),
        ):
            result = check_vendor(spec.get(name_field) or "", known)
            if result is None:
                continue
            level, message = result
            line = f"{_where(origin)}: {name}: {name_field}: {message}"
            if level == "error":
                problems.append(line)
            else:
                warnings.warn(line, stacklevel=2)
    return problems


def validate_file(path: Path | str) -> list[str]:
    """Everything wrong with a dataset YAML file; empty if there is nothing."""
    path = Path(path)
    return validate_document(yaml.safe_load(path.read_text(encoding="utf-8")), origin=path)


_SIZE_UNITS = ("B", "kB", "MB", "GB", "TB", "PB")


def format_size(size_bytes: int | None) -> str:
    """A byte count as SI units for display: ``1104287335`` -> ``"1.10 GB"``."""
    if size_bytes is None:
        return ""
    value = float(size_bytes)
    unit = _SIZE_UNITS[0]
    for unit in _SIZE_UNITS:
        if value < 1000 or unit == _SIZE_UNITS[-1]:
            break
        value /= 1000
    if unit == "B":
        return f"{int(value)} B"
    # Enough decimals for three significant figures, so a size stays readable
    # whether it is 42.0 kB or 1.10 GB.
    return f"{value:.{max(1, 3 - len(str(int(value))))}f} {unit}"


def _where(origin: Path | str | None) -> str:
    return str(origin) if origin else "dataset entry"


@dataclass(frozen=True)
class Author:
    """One author of a dataset."""

    affiliation: str
    orcid: str | None = None

    @classmethod
    def from_spec(
        cls, name: str, spec: Mapping[str, Any], origin: Path | str | None = None
    ) -> Author:
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(spec) - allowed)
        if unknown:
            raise TypeError(
                f"{_where(origin)}: author {name!r} has unknown field(s) "
                f"{', '.join(repr(k) for k in unknown)}; allowed: {', '.join(sorted(allowed))}"
            )
        if "affiliation" not in spec:
            raise TypeError(f"{_where(origin)}: author {name!r} is missing 'affiliation'")
        return cls(affiliation=str(spec["affiliation"]), orcid=spec.get("orcid"))


@dataclass(frozen=True)
class ModelInfo:
    """The model a ``kind: weights`` entry is a checkpoint for.

    ``class_`` carries the YAML's ``class`` key, which is a Python keyword and
    so cannot be a field name; :meth:`from_spec` is where the two are tied
    together.
    """

    class_: str
    framework: str
    quantem: str | None = None

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any], origin: Path | str | None = None) -> ModelInfo:
        allowed = ("class", "framework", "quantem")
        unknown = sorted(set(spec) - set(allowed))
        if unknown:
            raise TypeError(
                f"{_where(origin)}: model has unknown field(s) "
                f"{', '.join(repr(k) for k in unknown)}; allowed: {', '.join(allowed)}"
            )
        missing = [name for name in ("class", "framework") if not spec.get(name)]
        if missing:
            raise TypeError(
                f"{_where(origin)}: model is missing {', '.join(repr(k) for k in missing)}"
            )
        return cls(
            class_=str(spec["class"]),
            framework=str(spec["framework"]),
            quantem=spec.get("quantem"),
        )


@dataclass(frozen=True, repr=False)
class DatasetMetadata:
    """Everything a dataset YAML entry declares.

    Field order matches ``json-schema.json``; a test asserts the two stay in
    step.

    ``repr=False`` because the generated one runs to about a thousand
    characters - nearly all of it the description - which is no use as the
    output of a bare ``ds.metadata`` in a notebook. :meth:`__repr__` identifies
    the record in one line; ``print(ds.metadata)`` gives the readable form.
    """

    description: str
    source: str
    file: str
    url: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    detector_manufacturer: str | None = None
    detector: str | None = None
    microscope_vendor: str | None = None
    microscope_model: str | None = None
    camera_length: str | None = None
    voltage: str | None = None
    license: str | None = None
    technique: str | None = None
    doi: str | None = None
    tags: tuple[str, ...] = ()
    authors: Mapping[str, Author] = field(default_factory=dict)
    kind: str = "dataset"
    version: str | None = None
    model: ModelInfo | None = None

    @classmethod
    def from_spec(
        cls, spec: Mapping[str, Any], origin: Path | str | None = None
    ) -> DatasetMetadata:
        """Build a record from a parsed YAML entry.

        ``origin`` is the file the entry came from; it only appears in error
        messages, where it is the difference between a useful complaint and a
        ``TypeError`` from somewhere inside an import.
        """
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(spec) - allowed)
        if unknown:
            raise TypeError(
                f"{_where(origin)}: unknown field(s) {', '.join(repr(k) for k in unknown)}; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
        missing = [name for name in REQUIRED_FIELDS if spec.get(name) is None]
        if missing:
            raise TypeError(
                f"{_where(origin)}: missing required field(s) "
                f"{', '.join(repr(k) for k in missing)}"
            )
        values = dict(spec)
        size_bytes = values.get("size_bytes")
        values["size_bytes"] = None if size_bytes is None else int(size_bytes)
        values["tags"] = tuple(str(t) for t in values.get("tags") or ())
        values["authors"] = {
            str(name): Author.from_spec(str(name), entry or {}, origin)
            for name, entry in (values.get("authors") or {}).items()
        }
        values["kind"] = str(values.get("kind") or "dataset")
        version = values.get("version")
        values["version"] = None if version is None else str(version)
        model = values.get("model")
        values["model"] = None if model is None else ModelInfo.from_spec(model, origin)
        return cls(**values)

    @property
    def size(self) -> str:
        """:attr:`size_bytes` formatted for display, or ``""`` if unknown."""
        return format_size(self.size_bytes)

    def __repr__(self) -> str:
        """One line naming the file, what it is and how big: enough to tell two
        records apart in a list without printing a paragraph of description."""
        headline = " · ".join(p for p in (self.file, self.technique, self.size) if p)
        return f"<{type(self).__name__} {headline}>"

    def __str__(self) -> str:
        """The whole record, wrapped, with the empty fields left out."""
        headline = " · ".join(p for p in (self.file, self.technique, self.size) if p)
        head = [headline]
        if self.description:
            head.append(textwrap.fill(self.description, width=_STR_WIDTH))

        rows: list[tuple[str, str]] = []
        for entry in fields(self):
            if entry.name in ("description", "file", "technique", "size_bytes"):
                continue  # in the headline already, or shown as size_bytes below
            value = getattr(self, entry.name)
            if not value:
                continue
            if entry.name == "kind" and value == "dataset":
                continue  # the default, and true of all but the weights entries
            if entry.name == "authors":
                value = "; ".join(f"{n} ({a.affiliation})" for n, a in value.items())
            elif entry.name == "tags":
                value = ", ".join(value)
            elif entry.name == "model":
                value = " · ".join(p for p in (value.class_, value.framework, value.quantem) if p)
            rows.append((entry.name, str(value)))
        if self.size_bytes is not None:
            rows.append(("size_bytes", f"{self.size_bytes} ({self.size})"))

        label_width = max((len(name) for name, _ in rows), default=0)
        body = [
            textwrap.fill(
                value,
                width=_STR_WIDTH,
                initial_indent=f"{name:>{label_width}}: ",
                subsequent_indent=" " * (label_width + 2),
                # A URL or a checksum is one long token: overrun the width
                # rather than split it, so it can still be copied.
                break_long_words=False,
                break_on_hyphens=False,
            )
            for name, value in rows
        ]
        return "\n\n".join(part for part in ("\n".join(head), "\n".join(body)) if part)
