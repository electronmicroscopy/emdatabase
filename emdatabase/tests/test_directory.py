"""Tests for the data directory handling.

These exercise where files land, not what is in them, so they use the smallest
dataset in the index rather than a large one.
"""

from pathlib import Path

import pooch

import emdatabase
from emdatabase import data
from emdatabase.tests.test_load_data import TINY_DATASET

DEFAULT_DIR = Path(pooch.os_cache("emdatabase"))


def test_get_data_dir():
    assert emdatabase.get_data_dir() == DEFAULT_DIR


def test_set_data_dir(tmp_path):
    emdatabase.set_data_dir(str(tmp_path))
    assert emdatabase.get_data_dir() == tmp_path


def test_saving_to_configured_dir(tmp_path):
    """A dataset downloads into whatever data dir is configured."""
    emdatabase.set_data_dir(str(tmp_path))
    dataset = getattr(data, TINY_DATASET)()
    dest = dataset.download(progressbar=False, background=False)
    assert (tmp_path / dataset.file).exists()
    # a second download must reuse the file rather than refetch it
    assert dataset.download(progressbar=False, background=False) == dest


def test_saving_to_explicit_dir(tmp_path):
    """An explicit destination overrides the configured data dir."""
    other = tmp_path / "elsewhere"
    emdatabase.set_data_dir(str(tmp_path / "configured"))
    dataset = getattr(data, TINY_DATASET)()
    dest = dataset.download(destination=str(other), progressbar=False, background=False)
    assert "elsewhere" in str(dest)
    assert (other / dataset.file).exists()


def test_filepath_reports_missing_and_present(tmp_path):
    """filepath() is None until the file is there, then returns the path."""
    emdatabase.set_data_dir(str(tmp_path))
    dataset = getattr(data, TINY_DATASET)()
    assert dataset.filepath() is None
    dataset.download(progressbar=False, background=False)
    assert dataset.filepath() == tmp_path / dataset.file
