"""
Configuration and the Download Location
=======================================

``emdatabase.config`` is a dask-style configuration: shipped defaults, then the
yaml files in ``~/.config/emdatabase/``, then ``EMDATABASE_*`` environment
variables, then :class:`emdatabase.config.set`. This example shows how to read a
value, change where downloads go, and declare a shared store.
"""

import emdatabase
from emdatabase import config

# %%
# The data directory is where datasets download to. Unset, it is pooch's cache
# directory for emdatabase (``~/.cache/emdatabase`` on Linux).
print("configured    :", config.get("data_dir"))
print("download dir  :", emdatabase.get_data_dir())

# %%
# Change it for this process.
emdatabase.set_data_dir("/path/to/scratch")
print("download dir  :", emdatabase.get_data_dir())

# %%
# Or for a block, after which the previous value is restored.
with config.set({"data_dir": "/somewhere/else"}):
    print("inside        :", emdatabase.get_data_dir())
print("outside       :", emdatabase.get_data_dir())

# %%
# ``config.write()`` persists the whole configuration to
# ``~/.config/emdatabase/config.yaml``, which is read on every import. The same
# keys can come from the environment instead::
#
#     export EMDATABASE_DATA_DIR=/scratch/emdatabase
#     export EMDATABASE_STORES__GROUP=/group/example_data

# %%
# A store is a named read-only directory searched before your data directory, so
# a copy already on a group drive is used instead of downloaded again. Downloads
# still go to ``data_dir``.
config.set({"stores": {"group": "/group/example_data"}})
print("stores        :", config.stores())
print("search order  :", config.data_search_dirs())

# %%
# The name is the provenance: it is what the widgets and
# ``emdatabase.filter(location=...)`` report for a copy found there.
config.refresh()  # drop the changes this example made
