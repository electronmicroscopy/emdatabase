emdatabase
----------

This is a simple project for aggregating different Electron Microscopy files which are hosted over different sources.  It uses pooch to download datasets and should be
used as a way to host simple example datasets for method validation.

Data is stored in a file "User/emdatabase" but this can be also set to a custom location.

List of datasets https://electronmicroscopy.github.io/emdatabase/datasets.html

## Installation

```bash
pip install emdatabase
```

## Usage

Every dataset is a class under `emdatabase.data`.  Calling `download()` fetches the
file to the data directory, verifies its checksum, and returns a path handle.  Files
that are already present are not downloaded again.

```python
import emdatabase.data as data
import hyperspy.api as hs

path = data.LayeredCuNb4DSTEM().download()
s = hs.load(path, lazy=True)
```

By default the download runs on a background thread so a notebook cell returns
immediately.  The handle it returns *is* the file path — a `pathlib.Path` subclass
pointing at the file's final location — so you can hand it straight to a loader as
above; it only blocks at the moment the file is actually opened.  Read `path.done`
to check progress without blocking, or call `path.result()` to wait explicitly.
`download(background=False)` blocks instead, and returns the same type.

Any path pointing at the same file waits, however it was built, so a derived path
(`handle.parent / handle.name`, `handle.with_suffix(...)`) behaves too.  The
exceptions are `str(handle)` and `Path(handle)`: both hand back an ordinary value
with no download attached, so `hs.load(str(handle))` will *not* wait.  Keeping
`str()` non-blocking is deliberate — `repr()` needs it — so pass the handle itself.

## Finding a dataset

`search()` is the browser widget's search box, callable from Python; `filter()`
matches named fields.  Both return dataset objects, so a result can be downloaded
directly.

```python
import emdatabase

emdatabase.list_datasets()                                     # everything
emdatabase.search("amorphous")                            # any field
emdatabase.search("jeol eels")                            # all terms, any field
emdatabase.filter(technique="4D-STEM", tags="Strain")     # exact, case-insensitive
emdatabase.filter(microscope_vendor=["JEOL", "Hitachi"])  # a list means any of
emdatabase.filter(downloaded=True)                        # what is already here
```

An unknown field raises rather than being ignored, so a typo cannot quietly return
the whole index.

## Settings

Configuration lives in a live, matplotlib-`rcParams`-style object,
`emdatabase.settings`, seeded at import from `~/.emdatabase/settings.yaml`.
Change it in memory for an immediate effect, and persist it to remember the
choice across sessions:

```python
import emdatabase

emdatabase.settings["data_dir"] = "/big/disk/emdatabase"  # takes effect now
emdatabase.settings.save()                             # remember it next time
```

In Jupyter you can also edit them interactively — `display(emdatabase.settings)`
renders a panel to set (and save) the data directory directly.

The data directory defaults to `~/emdatabase`. Convenience helpers wrap the
common case — `set_data_dir` persists by default:

```python
emdatabase.get_data_dir()                       # current location
emdatabase.set_data_dir("/big/disk/emdatabase")    # set + persist
emdatabase.set_data_dir("/scratch", persist=False)  # one-off, in-memory only
emdatabase.reset_data_dir()                     # back to the default, forget the choice
```

No environment variable is needed. Only values you explicitly set are written to
the file, so the default is never frozen in — it keeps being obeyed even if it
changes. For a one-off override (e.g. CI) the legacy `EM_DATABASE_DATA_DIR` is
still honored, and `EM_DATABASE_CONFIG` relocates the settings file.

### Shared, system-wide data

Datasets can be installed once for every user. `download()` and `filepath()`
look in the shared/system locations **first**, then your own data directory, and
only download (into your directory) if the file is nowhere to be found — so a
shared copy is reused instead of refetched. Shared locations come from the
`EM_DATABASE_SHARED_DIR` environment variable (an `os.pathsep`-separated list), a
`shared_data_dirs` list in your settings, or a system config file
(`/etc/emdatabase/settings.yaml`, or `%PROGRAMDATA%\emdatabase\settings.yaml`
on Windows).

## Adding a dataset

Datasets are described by a YAML file in `emdatabase/index/`, one entry per file,
validated against `emdatabase/index/json-schema.json`.  The class name is generated
from the top-level key:

```yaml
MyDataset:
  description: What the data is, how it was acquired and how it is calibrated.
  source: https://zenodo.org/records/<record>/files
  file: MyDataset.zspy
  checksum: md5:<hash>
  size_bytes: 1200000000
  technique: 4D-STEM
  license: CC-BY-4.0
```

`size_bytes` is the file's `Content-Length` in bytes; the test suite checks it against
the server on every run. `emdatabase/index/vendors.yaml` lists the microscope
vendors and detector manufacturers already in use - a new one is fine, but a name close
to one already on the list fails CI as a misspelling.

Open an issue with the new dataset template, or add the YAML file directly.
