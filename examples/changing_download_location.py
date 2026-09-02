"""
Configuration and the Download Location
=======================================

Data lives in named locations. ``personal`` is the one writable location, where
downloads go; every other one is read-only and searched first, so a copy already
on a group drive is used instead of refetched.
:func:`emdatabase.config.add_location`,
:func:`emdatabase.config.locations` and
:func:`emdatabase.config.remove_location` are how you manage them.

Every call here passes ``persist=False``, so this example changes nothing on
disk. Drop it and the location is written to
``~/.config/emdatabase/config.yaml``, which is read on every import.
"""

from emdatabase import config

# %%
# The personal location is where datasets download to. Unset, it is pooch's
# cache directory for emdatabase (``~/.cache/emdatabase`` on Linux).
print("configured    :", config.get("locations.personal"))
print("download dir  :", config.data_dir())

# %%
# Point it somewhere with room on it.
config.add_location("/path/to/scratch", name="personal", persist=False)
print("download dir  :", config.data_dir())

# %%
# A shared location is searched before the personal one, so a colleague's copy
# is found instead of downloaded again. Downloads go to the personal location
# unless you name the shared one as the destination.
config.add_location("/group/example_data", persist=False)

# %%
# A location is named after the last component of its path unless you pass
# ``name=``. The name is the provenance: it is what the widgets and
# ``emdatabase.filter(location=...)`` report for a copy found there.
config.add_location("/cluster/em_data", name="cluster", persist=False)

# %%
# That name is also what seeds the share - ``destination=`` takes it, and the
# copy lands where everyone configured with it will find it. Run it once, from
# an account with write access, and ``chmod`` the file group-readable afterwards
# if your umask does not; emdatabase does not set permissions for you::
#
#     from emdatabase import data
#
#     seeded = data.CuZnHAADF().download(destination="example_data")
#     os.chmod(seeded, 0o664)

# %%
# :func:`~emdatabase.config.locations` is the search order — the shared
# locations in the order they were added, then ``personal`` last.
for location in config.locations():
    print(f"{location.kind:9} {location.name:13} {location.path}")

# %%
# Remove one by name or by path. ``"personal"`` is not deleted but reset,
# putting downloads back in the default cache directory.
config.remove_location("cluster", persist=False)
config.remove_location("/group/example_data", persist=False)
print("locations     :", config.locations())

# %%
# For a change that lasts only for a block, use :class:`emdatabase.config.set`
# as a context manager.
with config.set({"locations.personal": "/somewhere/else"}):
    print("inside        :", config.data_dir())
print("outside       :", config.data_dir())

# %%
# On HPC, where a config file is often the wrong place for a machine-specific
# path, set the key from the environment instead — no file and no write access
# needed::
#
#     export EMDATABASE_LOCATIONS__PERSONAL=/scratch/emdatabase
#     export EMDATABASE_LOCATIONS__GROUP=/group/example_data

# %%
config.refresh()  # drop the changes this example made
