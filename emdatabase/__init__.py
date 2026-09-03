### Example datasets ###
from emdatabase import config, data
from emdatabase.config import LocationName, add_location, locations, remove_location
from emdatabase.downloadable_dataset import DownloadableDataset
from emdatabase.query import filter, list_datasets, list_weights, search  # noqa: A004

__all__ = []


def browse(**kwargs):
    """
    Open the interactive dataset browser in Jupyter.

    Returns an `anywidget` widget listing every dataset grouped by technique,
    showing which are downloaded, revealing full metadata on hover, and
    downloading on click with a live progress toast. Requires the optional
    `anywidget` dependency (`pip install emdatabase[widget]`).

    ``display(emdatabase)`` renders the same browser.
    """
    from emdatabase.widget import browse as _browse

    return _browse(**kwargs)


__all__ = [
    "list_datasets",
    "list_weights",
    "search",
    "filter",
    "add_location",
    "remove_location",
    "locations",
    "LocationName",
    "browse",
    "config",
    "data",
    "DownloadableDataset",
]


# Let ``display(emdatabase)`` render the browser. Reassigning the module's
# __class__ to a ModuleType subclass is a supported pattern (see PEP 562) and is
# what lets the package itself carry a rich Jupyter repr.
import sys as _sys  # noqa: E402
from types import ModuleType as _ModuleType  # noqa: E402


class _EmDatabaseModule(_ModuleType):
    def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
        try:
            widget = browse()
        except Exception:
            return {
                "text/plain": (
                    "emdatabase — install the interactive browser with "
                    "`pip install emdatabase[widget]`, then call "
                    "emdatabase.browse()."
                )
            }
        return widget._repr_mimebundle_(**kwargs)


_sys.modules[__name__].__class__ = _EmDatabaseModule
