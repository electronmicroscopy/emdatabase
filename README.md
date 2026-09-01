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

## Configuration

Configuration is dask-style: shipped defaults, then every `*.yaml` in
`~/.config/emdatabase/` (or wherever `EMDATABASE_CONFIG` points), then
environment variables, then `config.set` — each layer overriding the one before.

```python
from emdatabase import config

config.get("data_dir")                                # None -> the pooch cache dir
config.set({"data_dir": "/big/disk/emdatabase"})      # for this process
config.write()                                        # -> ~/.config/emdatabase/config.yaml
```

`emdatabase.get_data_dir()` and `emdatabase.set_data_dir(path)` wrap the
`data_dir` key. Downloads go to `data_dir`, which defaults to pooch's cache
directory (`~/.cache/emdatabase` on Linux).

From the environment, keys are prefixed `EMDATABASE_` and nest on a double
underscore:

```bash
export EMDATABASE_DATA_DIR=/scratch/emdatabase
export EMDATABASE_STORES__GROUP=/group/example_data
```

### Stores: data installed once for everyone

A store is a named, read-only directory searched **before** your own data
directory, so a copy that is already on a group drive is used instead of
refetched. Downloads always go to `data_dir`; nothing is ever written to a store
by emdatabase.

```yaml
# ~/.config/emdatabase/config.yaml
data_dir: /big/disk/emdatabase
stores:
  group: /group/example_data
  cluster: /cluster/em_data
```

Stores are searched in declaration order. The name is the provenance: it is what
`catalogue.entry()["location"]`, `emdatabase.filter(location="group")` and the
widgets report for a copy found there — `"user"` for your own.

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

Open an issue with the [new dataset template](https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml),
or run `python -m emdatabase.new_dataset <url>`, which fetches the checksum and size,
prompts for the rest and writes the file for you to open a pull request with.  See
[CONTRIBUTING.md](CONTRIBUTING.md).
