"""Auto-generated dataset classes from YAML Files for downloading data."""

import yaml

from emdatabase._create_stubs import build_docstring
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.metadata import DatasetMetadata, dataset_files

__all__ = []
for dataset_path in dataset_files():
    data_dict_yaml = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    for name in data_dict_yaml:
        class_name = name.replace(" ", "_").replace("-", "_")
        data_dict = data_dict_yaml[name]
        _new_class = type(
            class_name,
            (DownloadableDataset,),
            {
                "_spec": data_dict,
                "_origin": dataset_path,
                "_metadata": DatasetMetadata.from_spec(data_dict, dataset_path),
                "__doc__": build_docstring(data_dict),
            },
        )
        globals()[class_name] = _new_class
        __all__.append(class_name)
