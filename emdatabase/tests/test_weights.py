"""Tests for the model-weights entries.

An entry with ``kind: weights`` is a dataset entry with a checkpoint on the end
of it: the same index, the same download, the same checksum. What is new is the
``model`` block, which the schema requires for weights and forbids for data, and
that one entry is a family - a ``latest`` link that serves whatever the current
file is, and a dated version for each state that link has served.

Everything here builds its own entry - two checkpoints written to a directory
served by ``conftest``'s local HTTP server, and a class installed into
``emdatabase.data`` for the length of one test - and asserts that it is found,
rather than that it is the only one: ``index/`` ships weights entries of its own.
Nothing touches the network: the index on ``main`` that a download asks about
newer weights is served by the same local server, with ``UPSTREAM_INDEX``
pointed at it.
"""

import hashlib
import warnings
from pathlib import Path

import pytest
import yaml

import emdatabase
from emdatabase import catalogue, config, downloadable_dataset
from emdatabase.downloadable_dataset import (
    DownloadableDataset,
    StaleIndexWarning,
    _clear_upstream_cache,
)
from emdatabase.metadata import (
    DatasetMetadata,
    ModelInfo,
    WeightsVersion,
    format_size,
    load_schema,
    validate_document,
    versioned_filename,
)

pytest.importorskip("jsonschema")

MODEL = {
    "class": "quantem.diffractive_imaging.ObjectINR",
    "framework": "torch",
    "quantem": ">=0.2,<0.3",
}
VERSION = "260902"
ENTRY = {
    "description": "A peak-detection network for 4D-STEM diffraction patterns.",
    "source": "https://zenodo.org/records/0000000/files",
    "file": "DemoNet.pt",
    "technique": "4D-STEM",
    "license": "CC-BY-4.0",
    "kind": "weights",
    "model": MODEL,
    "latest": {
        "url": "https://zenodo.org/records/0000000/files/DemoNet.pt",
        "checksum": "md5:" + "a" * 32,
        "size_bytes": 128,
    },
    "versions": {
        VERSION: {
            "url": "https://zenodo.org/records/0000000/files/DemoNet_260902.pt",
            "checksum": "md5:" + "b" * 32,
            "size_bytes": 128,
        }
    },
}
DATASET = {
    "description": "A 4D-STEM dataset of something.",
    "source": "https://zenodo.org/records/0000000/files",
    "file": "MyData.zspy",
    "kind": "dataset",
}


def _pin(path, url):
    """The ``{url, checksum, size_bytes}`` block describing a served file."""
    return {
        "url": url,
        "checksum": f"md5:{hashlib.md5(path.read_bytes()).hexdigest()}",
        "size_bytes": path.stat().st_size,
    }


@pytest.fixture
def family(http_server):
    """``(spec, served)`` for a weights family whose two files are really served.

    ``latest`` is the plain file and the dated version is a different
    checkpoint behind a redirect, which is the shape Zenodo and GitHub both
    serve, so a test can tell which of the two it was given.
    """
    torch = pytest.importorskip("torch")
    base, served = http_server
    latest = served / ENTRY["file"]
    torch.save({"state_dict": {"w": torch.zeros(2)}, "config": {"hidden": 2}}, latest)
    dated = served / versioned_filename(ENTRY["file"], VERSION)
    torch.save({"state_dict": {"w": torch.ones(2)}, "config": {"hidden": 2}}, dated)
    spec = {
        **ENTRY,
        "source": base,
        "latest": _pin(latest, f"{base}/{latest.name}"),
        "versions": {VERSION: _pin(dated, f"{base}/moved/{dated.name}")},
    }
    return spec, served


@pytest.fixture
def in_the_index(monkeypatch):
    """Install a weights entry into ``emdatabase.data`` for one test."""
    import emdatabase.data as data

    name = "DemoNet"
    cls = type(
        name,
        (DownloadableDataset,),
        {"_spec": ENTRY, "_metadata": DatasetMetadata.from_spec(ENTRY)},
    )
    monkeypatch.setattr(data, name, cls, raising=False)
    monkeypatch.setattr(data, "__all__", [*data.__all__, name])
    return name


# -- the schema -------------------------------------------------------------


def test_a_weights_entry_validates():
    assert validate_document({"DemoNet": ENTRY}) == []


@pytest.mark.parametrize("missing", ["model", "latest", "versions"])
def test_weights_without_the_blocks_they_need_are_rejected(missing):
    entry = {k: v for k, v in ENTRY.items() if k != missing}
    problems = validate_document({"DemoNet": entry}, origin="somewhere.yaml")
    assert len(problems) == 1
    assert f"'{missing}' is a required property" in problems[0]


@pytest.mark.parametrize("field", ["url", "checksum", "size_bytes"])
def test_a_weights_entry_declares_its_download_only_inside_latest(field):
    """One place per fact: a top-level ``checksum`` would be a second answer to
    the question ``latest.checksum`` already answers."""
    entry = {**ENTRY, field: ENTRY["latest"][field]}
    assert validate_document({"DemoNet": entry}) != []


@pytest.mark.parametrize("kind", [None, "dataset"])
@pytest.mark.parametrize("field", ["model", "latest", "versions"])
def test_a_dataset_with_a_weights_block_is_rejected(field, kind):
    """The blocks only mean anything for weights, so a stray one is a mistake."""
    entry = {**DATASET, field: ENTRY[field]}
    if kind is None:
        del entry["kind"]
    assert len(validate_document({"NotWeights": entry})) == 1


@pytest.mark.parametrize("missing", ["class", "framework"])
def test_the_model_block_needs_a_class_and_a_framework(missing):
    model = {k: v for k, v in MODEL.items() if k != missing}
    problems = validate_document({"DemoNet": {**ENTRY, "model": model}})
    assert len(problems) == 1
    assert f"'{missing}' is a required property" in problems[0]


def test_a_version_is_keyed_by_a_date():
    entry = {**ENTRY, "versions": {"v1": ENTRY["versions"][VERSION]}}
    assert validate_document({"DemoNet": entry}) != []


def test_a_version_needs_a_size_as_well_as_a_url_and_a_checksum():
    """``latest`` may leave the size out; a dated snapshot is a full pin."""
    pin = {k: v for k, v in ENTRY["versions"][VERSION].items() if k != "size_bytes"}
    entry = {**ENTRY, "versions": {VERSION: pin}}
    assert validate_document({"DemoNet": entry}) != []
    assert validate_document({"DemoNet": {**ENTRY, "latest": pin}}) == []


def test_an_unquoted_version_key_is_reported():
    """jsonschema's propertyNames never sees the int an unquoted 260902 parses
    to, so the check for it is ours."""
    entry = {**ENTRY, "versions": {260902: ENTRY["versions"][VERSION]}}
    problems = validate_document({"DemoNet": entry}, origin="somewhere.yaml")
    assert any("must be quoted" in problem for problem in problems)


def test_the_model_schema_and_the_dataclass_agree():
    """``class`` is a keyword, so the field is ``class_``; nothing else differs."""
    model_schema = load_schema()["patternProperties"]["^.+$"]["properties"]["model"]
    assert list(model_schema["properties"]) == ["class", "framework", "quantem"]
    assert model_schema["required"] == ["class", "framework"]


# -- the record -------------------------------------------------------------


def test_from_spec_builds_the_model_info_and_the_family():
    metadata = DatasetMetadata.from_spec(ENTRY)
    assert metadata.kind == "weights"
    assert metadata.model == ModelInfo(
        class_=MODEL["class"], framework="torch", quantem=">=0.2,<0.3"
    )
    assert metadata.latest == WeightsVersion(**ENTRY["latest"])
    assert metadata.versions == {VERSION: WeightsVersion(**ENTRY["versions"][VERSION])}


def test_the_plain_fields_describe_latest():
    ds = DownloadableDataset(**ENTRY)
    assert ds.versions == (VERSION,)
    assert ds.download_url == ENTRY["latest"]["url"]
    assert ds.checksum == ENTRY["latest"]["checksum"] == ds.latest_checksum
    assert ds.size_bytes == ENTRY["latest"]["size_bytes"]


def test_a_dated_copy_is_named_after_its_date():
    ds = DownloadableDataset(**ENTRY)
    assert ds.filename() == "DemoNet.pt"
    assert ds.filename(VERSION) == "DemoNet_260902.pt"


def test_an_unknown_version_says_which_ones_there_are():
    with pytest.raises(ValueError, match=f"no version '250101'.*{VERSION}"):
        DownloadableDataset(**ENTRY).filename("250101")


def test_str_shows_the_model_the_latest_link_and_the_versions():
    text = str(DatasetMetadata.from_spec(ENTRY))
    assert "kind: weights" in text
    assert MODEL["class"] in text
    assert ENTRY["latest"]["checksum"] in text
    assert ENTRY["latest"]["url"] in text
    assert f"versions: {VERSION}" in text
    plain = str(DatasetMetadata.from_spec({"description": "d", "source": "s", "file": "f"}))
    assert "kind" not in plain


# -- downloading ------------------------------------------------------------


def test_the_latest_checkpoint_downloads_and_loads(family, tmp_path):
    """The checksum is the check; ``weights_only=True`` is how it is opened."""
    torch = pytest.importorskip("torch")
    spec, _ = family
    path = DownloadableDataset(**spec).download(
        destination=tmp_path, progressbar=False, background=False
    )
    assert path.name == "DemoNet.pt"
    loaded = torch.load(path, weights_only=True)
    assert loaded["config"] == {"hidden": 2}
    assert torch.equal(loaded["state_dict"]["w"], torch.zeros(2))


def test_a_dated_version_downloads_under_its_own_name(family, tmp_path):
    """The dated link redirects, and the file it lands as carries the date, so
    it sits next to latest rather than replacing it."""
    torch = pytest.importorskip("torch")
    spec, _ = family
    path = DownloadableDataset(**spec).download(
        destination=tmp_path, progressbar=False, background=False, version=VERSION
    )
    assert path.name == "DemoNet_260902.pt"
    loaded = torch.load(path, weights_only=True)
    assert torch.equal(loaded["state_dict"]["w"], torch.ones(2))


def test_a_replaced_latest_is_kept_and_warned_about(family, tmp_path):
    """A retrained model behind the same link is what latest is for: the new
    bytes are handed over, with a warning that the index is behind."""
    spec, served = family
    (served / spec["file"]).write_bytes(b"the retrained weights")
    with pytest.warns(StaleIndexWarning, match=VERSION):
        path = DownloadableDataset(**spec).download(
            destination=tmp_path, progressbar=False, background=False
        )
    assert path.read_bytes() == b"the retrained weights"


def test_a_replaced_dated_version_is_refused(family, tmp_path):
    """A dated version is a pin, so different bytes are a substitution."""
    spec, served = family
    (served / versioned_filename(spec["file"], VERSION)).write_bytes(
        b"not the model you asked for"
    )
    with pytest.raises(Exception):
        DownloadableDataset(**spec).download(
            destination=tmp_path, progressbar=False, background=False, version=VERSION
        )


def test_a_local_latest_is_used_as_it_is(family, tmp_path):
    """A copy already on disk is not re-fetched or re-hashed: its bytes cannot
    be told apart from a newer or an older publication of the same link."""
    spec, served = family
    ds = DownloadableDataset(**spec)
    first = ds.download(destination=tmp_path, progressbar=False, background=False)
    (served / spec["file"]).write_bytes(b"the retrained weights")
    with warnings.catch_warnings():
        warnings.simplefilter("error", StaleIndexWarning)
        second = ds.download(destination=tmp_path, progressbar=False, background=False)
    assert first == second
    assert second.read_bytes() != b"the retrained weights"


def test_the_dated_copy_is_not_offered_as_latest(family, tmp_path):
    """Handing back pinned old bytes as latest is the substitution the
    checksums are there to prevent, so filepath() asks about one version."""
    spec, _ = family
    config.set({"locations": {"personal": str(tmp_path)}})
    ds = DownloadableDataset(**spec)
    ds.download(destination=tmp_path, progressbar=False, background=False, version=VERSION)
    assert ds.filepath() is None
    assert ds.filepath(VERSION) == tmp_path / "DemoNet_260902.pt"
    assert ds.filepaths(VERSION) == [tmp_path / "DemoNet_260902.pt"]
    assert ds.filepaths() == []


def test_delete_takes_a_version(family, tmp_path):
    spec, _ = family
    config.set({"locations": {"personal": str(tmp_path)}})
    ds = DownloadableDataset(**spec)
    ds.download(destination=tmp_path, progressbar=False, background=False)
    ds.download(destination=tmp_path, progressbar=False, background=False, version=VERSION)

    assert ds.delete(version=VERSION) is True
    assert ds.filepath(VERSION) is None
    assert ds.filepath() is not None
    assert ds.delete() is True
    assert ds.delete(version=VERSION) is False


def test_a_dated_download_in_the_background(family, tmp_path):
    spec, _ = family
    handle = DownloadableDataset(**spec).download(
        destination=tmp_path, progressbar=False, version=VERSION
    )
    assert handle == tmp_path / "DemoNet_260902.pt"
    assert handle.wait().is_file()


# -- finding them -----------------------------------------------------------


def test_list_weights_and_filter_find_it(in_the_index):
    assert in_the_index in [type(ds).__name__ for ds in emdatabase.list_weights()]
    assert in_the_index in [type(ds).__name__ for ds in emdatabase.filter(kind="weights")]
    assert in_the_index in [type(ds).__name__ for ds in emdatabase.filter(version=VERSION)]


def test_list_datasets_still_returns_everything(in_the_index):
    names = [type(ds).__name__ for ds in emdatabase.list_datasets()]
    assert in_the_index in names
    assert len(names) == len(emdatabase.list_datasets(kind="dataset")) + len(
        emdatabase.list_datasets(kind="weights")
    )
    assert in_the_index not in [type(ds).__name__ for ds in emdatabase.list_datasets("dataset")]


def test_search_matches_the_model_class(in_the_index):
    assert [type(ds).__name__ for ds in emdatabase.search("ObjectINR")] == [in_the_index]


def test_the_catalogue_groups_weights_on_their_own(in_the_index):
    groups = catalogue.catalogue()["groups"]
    assert groups[-1]["technique"] == catalogue.WEIGHTS_GROUP
    items = {it["name"]: it for it in groups[-1]["items"]}
    assert in_the_index in items
    # The entry's own technique is still 4D-STEM; it is only grouped elsewhere.
    assert items[in_the_index]["technique"] == "4D-STEM"
    assert all(g["technique"] != catalogue.WEIGHTS_GROUP for g in groups[:-1])


def test_the_catalogue_can_be_asked_for_one_kind(in_the_index):
    weights = catalogue.catalogue(kind="weights")
    assert weights["n_total"] == len(emdatabase.list_weights())
    assert [g["technique"] for g in weights["groups"]] == [catalogue.WEIGHTS_GROUP]
    datasets = catalogue.catalogue(kind="dataset")
    assert in_the_index not in [it["name"] for g in datasets["groups"] for it in g["items"]]


def test_the_catalogue_row_carries_the_model(in_the_index):
    ds = catalogue.resolve(in_the_index)
    assert ds is not None
    row = catalogue.entry(in_the_index, ds)
    assert row["kind"] == "weights"
    assert row["model_class"] == MODEL["class"]
    assert row["model_framework"] == "torch"
    assert row["model_quantem"] == ">=0.2,<0.3"


def test_the_catalogue_row_carries_the_whole_family(in_the_index):
    """The top-level link and checksum are latest; every dated version is a row
    of its own, because they are downloaded and deleted one at a time."""
    ds = catalogue.resolve(in_the_index)
    assert ds is not None
    row = catalogue.entry(in_the_index, ds)
    assert row["url"] == ENTRY["latest"]["url"]
    assert row["latest_checksum"] == ENTRY["latest"]["checksum"]
    pin = ENTRY["versions"][VERSION]
    assert row["versions"] == [
        {
            "version": VERSION,
            "url": pin["url"],
            "checksum": pin["checksum"],
            "size": format_size(pin["size_bytes"]),
            "downloaded": False,
            "path": "",
            "location": None,
        }
    ]


def test_a_dataset_row_has_no_versions():
    ds = catalogue.resolve("CuZnHAADF")
    assert ds is not None
    row = catalogue.entry("CuZnHAADF", ds)
    assert row["versions"] == []
    assert row["latest_checksum"] == ds.checksum


def test_the_catalogue_row_tracks_each_version_on_disk(in_the_index, tmp_path):
    config.set({"locations": {"personal": str(tmp_path)}})
    ds = catalogue.resolve(in_the_index)
    assert ds is not None
    (tmp_path / versioned_filename(ENTRY["file"], VERSION)).write_bytes(b"x")

    row = catalogue.entry(in_the_index, ds)
    # A dated copy is not latest, so only the version row turns on.
    assert row["downloaded"] is False
    assert row["versions"][0]["downloaded"] is True
    assert row["versions"][0]["path"] == str(tmp_path / "DemoNet_260902.pt")
    assert row["versions"][0]["location"] == "personal"


def test_search_matches_a_version_date(in_the_index):
    assert in_the_index in [type(ds).__name__ for ds in emdatabase.search(VERSION)]


# -- newer weights upstream -------------------------------------------------

NEW_VERSION = "260910"


@pytest.fixture(autouse=True)
def _forget_upstream():
    """The fetched index and the warned-once set both live for the process."""
    _clear_upstream_cache()
    yield
    _clear_upstream_cache()


@pytest.fixture
def upstream(family, monkeypatch):
    """``(class, write, spec, served)`` for a family whose index on main is local.

    ``write(entry)`` publishes one entry as the served ``index/DemoNet.yaml``,
    which is where :data:`UPSTREAM_INDEX` is pointed. Not calling it leaves the
    path 404ing, which is what an unreachable index looks like.
    """
    spec, served = family
    index = served / "index"
    index.mkdir()
    monkeypatch.setattr(downloadable_dataset, "UPSTREAM_INDEX", f"{spec['source']}/index/")
    cls = type("DemoNet", (DownloadableDataset,), {"_spec": spec, "_origin": Path("DemoNet.yaml")})

    def write(entry):
        (index / "DemoNet.yaml").write_text(yaml.safe_dump({"DemoNet": entry}), encoding="utf-8")

    return cls, write, spec, served


@pytest.fixture
def asked(monkeypatch):
    """Every upstream lookup that happens, so a test can assert none did."""
    calls = []

    def record(name, origin_filename):
        calls.append((name, origin_filename))
        return None

    monkeypatch.setattr(downloadable_dataset, "upstream_metadata", record)
    return calls


def _retrained(spec, checksum="md5:" + "c" * 32):
    """``spec`` as the index on main would hold it after a retrain."""
    return {
        **spec,
        "latest": {**spec["latest"], "checksum": checksum},
        "versions": {
            **spec["versions"],
            NEW_VERSION: {**spec["latest"], "checksum": checksum},
        },
    }


def test_an_index_that_agrees_says_nothing(upstream, tmp_path):
    cls, write, spec, _ = upstream
    write(spec)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        path = cls().download(destination=tmp_path, progressbar=False, background=False)
    assert path.is_file()


def test_newer_weights_upstream_warn(upstream, tmp_path):
    cls, write, spec, _ = upstream
    write(_retrained(spec))
    ds = cls()
    with pytest.warns(StaleIndexWarning, match="refresh=True") as record:
        ds.download(destination=tmp_path, progressbar=False, background=False)
    assert NEW_VERSION in str(record[0].message)
    # The question is about the index, not the disk, so a copy already
    # downloaded is no reason not to ask it.
    _clear_upstream_cache()
    with pytest.warns(StaleIndexWarning):
        ds.download(destination=tmp_path, progressbar=False, background=False)


def test_the_warning_is_once_per_family(upstream, tmp_path):
    """A notebook loop asks about the same weights over and over."""
    cls, write, spec, _ = upstream
    write(_retrained(spec))
    ds = cls()
    with pytest.warns(StaleIndexWarning):
        ds.download(destination=tmp_path, progressbar=False, background=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error", StaleIndexWarning)
        ds.download(destination=tmp_path, progressbar=False, background=False)


def test_refresh_fetches_the_weights_the_index_on_main_names(upstream, tmp_path):
    cls, write, spec, served = upstream
    retrained = served / "DemoNet_new.pt"
    retrained.write_bytes(b"the retrained weights")
    write({**spec, "latest": _pin(retrained, f"{spec['source']}/{retrained.name}")})

    ds = cls()
    with pytest.warns(StaleIndexWarning):
        first = ds.download(destination=tmp_path, progressbar=False, background=False)
    assert first.read_bytes() != b"the retrained weights"

    second = ds.download(destination=tmp_path, progressbar=False, background=False, refresh=True)
    assert second == first
    assert second.read_bytes() == b"the retrained weights"


def test_refresh_verifies_the_upstream_checksum(upstream, tmp_path):
    """The upstream entry is a pin, so it is downloaded like one."""
    cls, write, spec, served = upstream
    retrained = served / "DemoNet_new.pt"
    retrained.write_bytes(b"the retrained weights")
    write(
        {
            **spec,
            "latest": {"url": f"{spec['source']}/{retrained.name}", "checksum": "md5:" + "c" * 32},
        }
    )
    with pytest.raises(Exception):
        cls().download(destination=tmp_path, progressbar=False, background=False, refresh=True)


def test_refresh_without_an_index_upstream_refetches_the_shipped_link(upstream, tmp_path):
    """Nothing is written to the served index, so the lookup 404s."""
    cls, _, spec, served = upstream
    ds = cls()
    first = ds.download(destination=tmp_path, progressbar=False, background=False)
    (served / spec["file"]).write_bytes(b"the retrained weights")
    with pytest.warns(StaleIndexWarning):
        second = ds.download(
            destination=tmp_path, progressbar=False, background=False, refresh=True
        )
    assert second == first
    assert second.read_bytes() == b"the retrained weights"


def test_check_updates_off_asks_nothing(upstream, asked, tmp_path):
    cls, write, spec, _ = upstream
    write(_retrained(spec))
    with config.set({"check_updates": False}):
        with warnings.catch_warnings():
            warnings.simplefilter("error", StaleIndexWarning)
            cls().download(destination=tmp_path, progressbar=False, background=False)
    assert asked == []


def test_a_pinned_version_asks_nothing(upstream, asked, tmp_path):
    cls, write, spec, _ = upstream
    write(_retrained(spec))
    cls().download(destination=tmp_path, progressbar=False, background=False, version=VERSION)
    assert asked == []


def test_refresh_refetches_a_dated_version(upstream, asked, tmp_path):
    cls, _, spec, _ = upstream
    ds = cls()
    path = ds.download(destination=tmp_path, progressbar=False, background=False, version=VERSION)
    path.write_bytes(b"a corrupted copy")
    again = ds.download(
        destination=tmp_path, progressbar=False, background=False, version=VERSION, refresh=True
    )
    assert again == path
    assert again.read_bytes() != b"a corrupted copy"
    assert asked == []


def test_a_dataset_asks_nothing(family, asked, tmp_path):
    """There is no family for a newer index to say anything about."""
    spec, served = family
    served_file = served / "MyData.bin"
    served_file.write_bytes(b"some data")
    entry = {
        **DATASET,
        "source": spec["source"],
        "file": served_file.name,
        **_pin(served_file, f"{spec['source']}/{served_file.name}"),
    }
    cls = type(
        "DemoData", (DownloadableDataset,), {"_spec": entry, "_origin": Path("DemoData.yaml")}
    )
    ds = cls()
    ds.download(destination=tmp_path, progressbar=False, background=False)
    path = ds.download(destination=tmp_path, progressbar=False, background=False, refresh=True)
    assert path.read_bytes() == b"some data"
    assert asked == []
