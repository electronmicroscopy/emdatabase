"""Tests for the model-weights entries.

An entry with ``kind: weights`` is a dataset entry with a checkpoint on the end
of it: the same index, the same download, the same checksum. What is new is the
``model`` block, which the schema requires for weights and forbids for data, and
that the catalogue and the query API can tell the two apart.

There is no weights entry in ``index/`` yet, so everything here builds its own -
a two-tensor checkpoint written to a directory served by ``conftest``'s local
HTTP server, and a class installed into ``emdatabase.data`` for the length of
one test. Nothing touches the network.
"""

import hashlib

import pytest

import emdatabase
from emdatabase import catalogue
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.metadata import DatasetMetadata, ModelInfo, load_schema, validate_document

pytest.importorskip("jsonschema")

MODEL = {
    "class": "quantem.diffractive_imaging.ObjectINR",
    "framework": "torch",
    "quantem": ">=0.2,<0.3",
}
ENTRY = {
    "description": "A peak-detection network for 4D-STEM diffraction patterns.",
    "source": "https://zenodo.org/records/0000000/files",
    "file": "DemoNet_v1.pt",
    "technique": "4D-STEM",
    "license": "CC-BY-4.0",
    "kind": "weights",
    "version": "1",
    "model": MODEL,
}


@pytest.fixture
def checkpoint(http_server):
    """``(spec, path)`` for a real checkpoint served over HTTP."""
    torch = pytest.importorskip("torch")
    base, served = http_server
    path = served / ENTRY["file"]
    torch.save({"state_dict": {"w": torch.zeros(2)}, "config": {"hidden": 2}}, path)
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    return {**ENTRY, "source": base, "checksum": f"md5:{digest}"}, path


@pytest.fixture
def in_the_index(monkeypatch):
    """Install a weights entry into ``emdatabase.data`` for one test."""
    import emdatabase.data as data

    name = "DemoNet_v1"
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
    assert validate_document({"DemoNet_v1": ENTRY}) == []


def test_weights_without_a_model_are_rejected():
    entry = {k: v for k, v in ENTRY.items() if k != "model"}
    problems = validate_document({"DemoNet_v1": entry}, origin="somewhere.yaml")
    assert len(problems) == 1
    assert "'model' is a required property" in problems[0]


@pytest.mark.parametrize("kind", [None, "dataset"])
def test_a_dataset_with_a_model_is_rejected(kind):
    """The block only means anything for weights, so a stray one is a mistake."""
    entry = {**ENTRY, "kind": kind}
    if kind is None:
        del entry["kind"]
    assert len(validate_document({"NotWeights": entry})) == 1


@pytest.mark.parametrize("missing", ["class", "framework"])
def test_the_model_block_needs_a_class_and_a_framework(missing):
    model = {k: v for k, v in MODEL.items() if k != missing}
    problems = validate_document({"DemoNet_v1": {**ENTRY, "model": model}})
    assert len(problems) == 1
    assert f"'{missing}' is a required property" in problems[0]


def test_the_model_schema_and_the_dataclass_agree():
    """``class`` is a keyword, so the field is ``class_``; nothing else differs."""
    model_schema = load_schema()["patternProperties"]["^.+$"]["properties"]["model"]
    assert list(model_schema["properties"]) == ["class", "framework", "quantem"]
    assert model_schema["required"] == ["class", "framework"]


# -- the record -------------------------------------------------------------


def test_from_spec_builds_the_model_info():
    metadata = DatasetMetadata.from_spec(ENTRY)
    assert metadata.kind == "weights"
    assert metadata.version == "1"
    assert metadata.model == ModelInfo(
        class_=MODEL["class"], framework="torch", quantem=">=0.2,<0.3"
    )


def test_a_dataset_has_no_model_and_the_default_kind():
    metadata = DatasetMetadata.from_spec(
        {"description": "d", "source": "https://example.com", "file": "d.zspy"}
    )
    assert metadata.kind == "dataset"
    assert metadata.model is None


def test_str_shows_the_model_but_not_the_default_kind():
    assert "kind: weights" in str(DatasetMetadata.from_spec(ENTRY))
    assert MODEL["class"] in str(DatasetMetadata.from_spec(ENTRY))
    plain = str(DatasetMetadata.from_spec({"description": "d", "source": "s", "file": "f"}))
    assert "kind" not in plain


# -- downloading ------------------------------------------------------------


def test_the_checkpoint_downloads_and_loads(checkpoint, tmp_path):
    """The checksum is the check; ``weights_only=True`` is how it is opened."""
    torch = pytest.importorskip("torch")
    spec, _ = checkpoint
    path = DownloadableDataset(**spec).download(
        destination=tmp_path, progressbar=False, background=False
    )
    loaded = torch.load(path, weights_only=True)
    assert loaded["config"] == {"hidden": 2}
    assert torch.equal(loaded["state_dict"]["w"], torch.zeros(2))


def test_a_replaced_checkpoint_is_refused(checkpoint, tmp_path):
    spec, path = checkpoint
    path.write_bytes(b"not the model you asked for")
    with pytest.raises(Exception):
        DownloadableDataset(**spec).download(
            destination=tmp_path, progressbar=False, background=False
        )


# -- finding them -----------------------------------------------------------


def test_list_weights_and_filter_find_it(in_the_index):
    assert [type(ds).__name__ for ds in emdatabase.list_weights()] == [in_the_index]
    assert [type(ds).__name__ for ds in emdatabase.filter(kind="weights")] == [in_the_index]
    assert [type(ds).__name__ for ds in emdatabase.filter(version="1")] == [in_the_index]


def test_list_datasets_still_returns_everything(in_the_index):
    names = [type(ds).__name__ for ds in emdatabase.list_datasets()]
    assert in_the_index in names
    assert len(names) == len(emdatabase.list_datasets(kind="dataset")) + 1
    assert in_the_index not in [type(ds).__name__ for ds in emdatabase.list_datasets("dataset")]


def test_search_matches_the_model_class(in_the_index):
    assert [type(ds).__name__ for ds in emdatabase.search("ObjectINR")] == [in_the_index]


def test_the_catalogue_groups_weights_on_their_own(in_the_index):
    groups = catalogue.catalogue()["groups"]
    assert groups[-1]["technique"] == catalogue.WEIGHTS_GROUP
    assert [it["name"] for it in groups[-1]["items"]] == [in_the_index]
    # The entry's own technique is still 4D-STEM; it is only grouped elsewhere.
    assert groups[-1]["items"][0]["technique"] == "4D-STEM"
    assert all(g["technique"] != catalogue.WEIGHTS_GROUP for g in groups[:-1])


def test_the_catalogue_can_be_asked_for_one_kind(in_the_index):
    weights = catalogue.catalogue(kind="weights")
    assert weights["n_total"] == 1
    assert [g["technique"] for g in weights["groups"]] == [catalogue.WEIGHTS_GROUP]
    datasets = catalogue.catalogue(kind="dataset")
    assert in_the_index not in [it["name"] for g in datasets["groups"] for it in g["items"]]


def test_the_catalogue_row_carries_the_model(in_the_index):
    ds = catalogue.resolve(in_the_index)
    assert ds is not None
    row = catalogue.entry(in_the_index, ds)
    assert row["kind"] == "weights"
    assert row["version"] == "1"
    assert row["model_class"] == MODEL["class"]
    assert row["model_framework"] == "torch"
    assert row["model_quantem"] == ">=0.2,<0.3"
