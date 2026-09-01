"""Tests for the Python query API.

The conftest fixture isolates the settings and clears the shared/data env vars,
so ``downloaded`` / ``location`` here describe a tmp dir rather than whatever the
developer happens to have downloaded.
"""

import types

import pytest

import emdatabase
from emdatabase import catalogue
from emdatabase.data import BilayerWS2
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.query import FILTER_FIELDS


def names(found):
    return sorted(type(ds).__name__ for ds in found)


def test_datasets_returns_objects_not_rows():
    found = emdatabase.list_datasets()
    assert found
    assert all(isinstance(ds, DownloadableDataset) for ds in found)
    assert names(found) == sorted(n for n, _ in catalogue.datasets())


def test_search_matches_every_term_across_fields():
    """The widget's rule: all terms must appear, but not in one field."""
    found = names(emdatabase.search("jeol eels"))
    assert found
    for name in found:
        dataset = catalogue.resolve(name)
        assert dataset is not None
        blob = catalogue.entry(name, dataset)["search"]
        assert "jeol" in blob and "eels" in blob


def test_search_is_case_insensitive():
    assert names(emdatabase.search("AMORPHOUS")) == names(emdatabase.search("amorphous"))


def test_search_finds_a_dataset_by_author():
    """Proof the blob reaches past the name - authors are not in the class name."""
    ds = BilayerWS2()
    author = next(iter(ds.metadata.authors))
    assert type(ds).__name__ in names(emdatabase.search(author))


def test_search_uses_the_same_blob_and_rule_as_the_widget():
    query = "direct electron"
    terms = query.lower().split()
    expected = sorted(
        name
        for name, dataset in catalogue.datasets()
        if all(t in catalogue.entry(name, dataset)["search"] for t in terms)
    )
    assert names(emdatabase.search(query)) == expected


def test_empty_search_returns_everything():
    assert names(emdatabase.search("   ")) == names(emdatabase.list_datasets())


def test_search_with_no_hits_is_empty():
    assert emdatabase.search("definitelynotadataset") == []


def test_filter_is_exact_but_case_insensitive():
    exact = names(emdatabase.filter(technique="4D-STEM"))
    assert exact
    assert names(emdatabase.filter(technique="4d-stem")) == exact
    # exact, not substring: "4D" must not match "4D-STEM"
    assert emdatabase.filter(technique="4D") == []


def test_filter_combines_criteria_with_and():
    both = names(emdatabase.filter(technique="4D-STEM", tags="Strain"))
    technique_only = names(emdatabase.filter(technique="4D-STEM"))
    assert both
    assert set(both) < set(technique_only)


def test_filter_accepts_a_list_as_any_of():
    jeol = set(names(emdatabase.filter(microscope_vendor="JEOL")))
    tfs = set(names(emdatabase.filter(microscope_vendor="Thermo Fisher Scientific")))
    either = set(names(emdatabase.filter(microscope_vendor=["JEOL", "Thermo Fisher Scientific"])))
    assert either == jeol | tfs
    assert jeol and tfs


def test_filter_on_tags_tests_membership():
    for ds in emdatabase.filter(tags="Strain"):
        assert "Strain" in ds.metadata.tags


def test_filter_on_authors_tests_membership():
    ds = BilayerWS2()
    author = next(iter(ds.metadata.authors))
    assert type(ds).__name__ in names(emdatabase.filter(authors=author))


def test_filter_rejects_an_unknown_field():
    with pytest.raises(TypeError, match="techniqu"):
        emdatabase.filter(techniqu="4D-STEM")


def test_filter_fields_are_all_actually_filterable():
    """Every advertised field has to work, not just be listed."""
    for field in FILTER_FIELDS:
        emdatabase.filter(**{field: None if field == "location" else "nothing-matches-this"})


def test_filter_on_downloaded_and_location(tmp_path, monkeypatch):
    shared, user = tmp_path / "shared", tmp_path / "user"
    shared.mkdir()
    user.mkdir()
    monkeypatch.setenv("EM_DATABASE_SHARED_DIR", str(shared))
    emdatabase.set_data_dir(str(user), persist=False)

    assert emdatabase.filter(downloaded=True) == []
    assert names(emdatabase.filter(downloaded=False)) == names(emdatabase.list_datasets())

    ds = BilayerWS2()
    (user / ds.file).write_bytes(b"mine")
    assert names(emdatabase.filter(downloaded=True)) == [type(ds).__name__]
    assert names(emdatabase.filter(location="user")) == [type(ds).__name__]
    assert emdatabase.filter(location="shared") == []

    (shared / ds.file).write_bytes(b"theirs")
    assert names(emdatabase.filter(location="shared")) == [type(ds).__name__]
    assert emdatabase.filter(location="user") == []


def test_the_query_api_is_on_the_top_level_namespace():
    for name in ("list_datasets", "search", "filter"):
        assert name in emdatabase.__all__
        assert callable(getattr(emdatabase, name))


def test_public_names_survive_a_submodule_walk():
    """A submodule and a top-level function cannot share a name.

    Importing ``emdatabase.<name>`` makes the import machinery bind that
    submodule onto the parent package, replacing any function of the same name.
    Sphinx's autosummary walks every submodule, so this is not hypothetical - it
    is what took the docs build down when the function was called ``datasets()``
    next to what was then the ``emdatabase/datasets/`` subpackage.
    """
    import importlib
    import pkgutil

    for found in pkgutil.walk_packages(emdatabase.__path__, "emdatabase."):
        try:
            importlib.import_module(found.name)
        except ImportError:
            continue  # an optional dependency, not a name clash

    for name in emdatabase.__all__:
        exported = getattr(emdatabase, name)
        assert not isinstance(exported, types.ModuleType) or name in ("data", "settings"), (
            f"emdatabase.{name} was replaced by a submodule of the same name"
        )
