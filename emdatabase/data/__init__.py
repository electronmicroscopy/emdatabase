"""Auto-generated dataset classes from YAML Files for downloading data."""

from emdatabase._create_stubs import build_docstring
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.metadata import index_entries

__all__ = []
for _entry in index_entries():
    _new_class = type(
        _entry.class_name,
        (DownloadableDataset,),
        {
            "_spec": _entry.spec,
            "_origin": _entry.origin,
            "_metadata": _entry.metadata,
            "__doc__": build_docstring(_entry.spec),
        },
    )
    globals()[_entry.class_name] = _new_class
    __all__.append(_entry.class_name)
