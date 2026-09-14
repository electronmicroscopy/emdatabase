"""How ``emdatabase.data`` handles a bad index file.

The classes are built at import, so anything that raises here takes down
``import emdatabase`` for every user. A file that is empty, an entry with no
body and a name declared twice are all problems for validation to report, and
none of them is a reason for the package not to import.
"""

import importlib
import textwrap

import pytest

ENTRY = textwrap.dedent(
    """\
    {name}:
      description: A 4D-STEM dataset of something.
      source: https://zenodo.org/records/0000000/files
      file: {name}.zspy
    """
)


@pytest.fixture
def index(tmp_path, monkeypatch):
    """Rebuild ``emdatabase.data`` from index files given as ``stem=text``."""
    import emdatabase.metadata as metadata

    def build(**files):
        paths = []
        for stem, text in files.items():
            path = tmp_path / f"{stem}.yaml"
            path.write_text(text, encoding="utf-8")
            paths.append(path)
        monkeypatch.setattr(metadata, "dataset_files", lambda: paths)
        return importlib.reload(importlib.import_module("emdatabase.data"))

    yield build
    monkeypatch.undo()
    importlib.reload(importlib.import_module("emdatabase.data"))


def test_an_empty_index_file_warns_and_the_rest_still_loads(index):
    with pytest.warns(UserWarning, match="no dataset entries"):
        data = index(a_empty="# nothing here yet\n", b_real=ENTRY.format(name="Real"))
    assert data.__all__ == ["Real"]


def test_an_entry_with_no_body_is_skipped(index):
    with pytest.warns(UserWarning, match="skipping 'Hollow'"):
        data = index(entries="Hollow:\n" + ENTRY.format(name="Real"))
    assert data.__all__ == ["Real"]


def test_a_name_declared_twice_is_counted_once(index):
    with pytest.warns(UserWarning, match="already declared"):
        data = index(a_first=ENTRY.format(name="Same"), b_second=ENTRY.format(name="Same"))
    assert data.__all__ == ["Same"]
    assert data.Same._origin.name == "a_first.yaml"  # the first file wins
