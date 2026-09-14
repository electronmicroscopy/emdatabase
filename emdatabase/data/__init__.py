"""Auto-generated dataset classes from YAML Files for downloading data."""

import warnings

import yaml

from emdatabase._create_stubs import build_docstring
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.metadata import DatasetMetadata, dataset_files

__all__ = []
_declared_in = {}
for dataset_path in dataset_files():
    data_dict_yaml = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if not data_dict_yaml:
        # An empty or comment-only index file is a problem for validation to
        # report, not a reason for `import emdatabase` to fail.
        warnings.warn(f"no dataset entries in {dataset_path}", stacklevel=2)
        continue
    for name in data_dict_yaml:
        class_name = name.replace(" ", "_").replace("-", "_")
        data_dict = data_dict_yaml[name] or {}
        if class_name in _declared_in:
            warnings.warn(
                f"skipping {name!r} in {dataset_path}: already declared in "
                f"{_declared_in[class_name]}",
                stacklevel=2,
            )
            continue
        try:
            _metadata = DatasetMetadata.from_spec(data_dict, dataset_path)
        except TypeError as error:
            # A malformed entry is for validation to report; it should not make
            # the package unimportable for everyone else.
            warnings.warn(f"skipping {name!r} in {dataset_path}: {error}", stacklevel=2)
            continue
        _new_class = type(
            class_name,
            (DownloadableDataset,),
            {
                "_spec": data_dict,
                "_origin": dataset_path,
                "_metadata": _metadata,
                "__doc__": build_docstring(data_dict),
            },
        )
        globals()[class_name] = _new_class
        _declared_in[class_name] = dataset_path
        __all__.append(class_name)
