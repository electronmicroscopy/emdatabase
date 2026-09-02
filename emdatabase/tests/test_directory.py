"""Tests for the personal directory handling.

These exercise where files land, not what is in them, so they use the smallest
dataset in the index rather than a large one.
"""

from pathlib import Path

import pooch

from emdatabase import config, data
from emdatabase.tests.test_load_data import TINY_DATASET

DEFAULT_DIR = Path(pooch.os_cache("emdatabase"))


def test_data_dir_defaults_to_the_cache():
    assert config.data_dir() == DEFAULT_DIR


def test_add_location_personal_sets_the_data_dir(tmp_path):
    config.add_location(tmp_path, name="personal", persist=False)
    assert config.data_dir() == tmp_path


def test_saving_to_configured_dir(tmp_path):
    """A dataset downloads into whatever personal directory is configured."""
    config.add_location(tmp_path, name="personal", persist=False)
    dataset = getattr(data, TINY_DATASET)()
    dest = dataset.download(progressbar=False, background=False)
    assert (tmp_path / dataset.file).exists()
    # a second download must reuse the file rather than refetch it
    assert dataset.download(progressbar=False, background=False) == dest


def test_saving_to_explicit_dir(tmp_path):
    """An explicit destination overrides the configured personal directory."""
    other = tmp_path / "elsewhere"
    configured = tmp_path / "configured"
    configured.mkdir()
    config.add_location(configured, name="personal", persist=False)
    dataset = getattr(data, TINY_DATASET)()
    dest = dataset.download(destination=str(other), progressbar=False, background=False)
    assert "elsewhere" in str(dest)
    assert (other / dataset.file).exists()


def test_filepath_reports_missing_and_present(tmp_path):
    """filepath() is None until the file is there, then returns the path."""
    config.add_location(tmp_path, name="personal", persist=False)
    dataset = getattr(data, TINY_DATASET)()
    assert dataset.filepath() is None
    dataset.download(progressbar=False, background=False)
    assert dataset.filepath() == tmp_path / dataset.file
