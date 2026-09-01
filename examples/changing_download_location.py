"""
Settings and the Download Location
==================================

Configuration for ``emdatabase`` lives in a live, matplotlib-``rcParams``-style
object, ``emdatabase.settings``, seeded at import from a YAML file in
``~/.emdatabase/settings.yaml``. This example shows how to read it, change the
data directory for the session or for good, and reset it.
"""

import emdatabase

# %%
# The data directory is where datasets download to. It defaults to
# ``~/emdatabase``.
print("Current download directory:", emdatabase.get_data_dir())

# %%
# Change it for this session only (in memory, not written to disk).
emdatabase.set_data_dir("/path/to/scratch", persist=False)
print("Session directory:", emdatabase.get_data_dir())

# %%
# Change it and remember the choice across sessions (writes
# ``~/.emdatabase/settings.yaml``). ``set_data_dir`` persists by default; the
# equivalent low-level form is ``emdatabase.settings[...] = ...; save()``.
emdatabase.set_data_dir("/big/disk/emdatabase")  # set + persist
# emdatabase.settings["data_dir"] = "/big/disk/emdatabase"  # the same thing
# emdatabase.settings.save()
print("Persisted directory:", emdatabase.get_data_dir())

# %%
# Reset to the default location, forgetting the saved choice.
emdatabase.reset_data_dir()
print("Reset directory:", emdatabase.get_data_dir())

# %%
# Any setting can be stored, not just the data directory.
emdatabase.set_setting("quality", "high")
print("quality:", emdatabase.get_setting("quality"))

# %%
# Datasets can also be installed system-wide and shared by every user. Point
# ``EM_DATABASE_SHARED_DIR`` (or a ``shared_data_dirs`` setting, or a system
# config file) at the shared location, and ``download()`` / ``filepath()`` will
# find a pre-installed copy there before downloading into your own directory.

# %%
# Clean up so running this example leaves no settings behind.
emdatabase.settings.reset()
