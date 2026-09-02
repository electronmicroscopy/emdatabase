emdatabase
----------

This is a simple project for aggregating different Electron Microscopy files which are hosted over different sources.  It uses pooch to download datasets and should be
used as a way to host simple example datasets for method validation.

Downloads go to `~/.cache/emdatabase` by default; shared read-only locations can be added with `emdatabase.add_location`.

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

Data lives in two kinds of place: one **personal** directory, writable, where
downloads go, and any number of named **shared** stores, read-only, searched
first so a copy already on a group drive is used instead of refetched.

`add_location` writes both:

```python
from emdatabase import config

config.add_location("/group/example_data")                 # a shared store
config.add_location("/big/disk/emdatabase", "personal")    # where downloads go
config.locations()
```

```
[Location(name='example_data', path=PosixPath('/group/example_data'), kind='shared'),
 Location(name='personal', path=PosixPath('/big/disk/emdatabase'), kind='personal')]
```

`locations()` is the search order: the stores in the order they were added, then
the personal directory last. A store is named after the last component of its
path unless you pass `name=`, and that name is the provenance — it is what
`catalogue.entry()["location"]`, `emdatabase.filter(location="example_data")` and
the browser widget report for a copy found there. Nothing is written to a store
unless you name it as a download's destination, which is how one is seeded.

Removing one takes either the name or the path; `"personal"` puts downloads back
in the default cache directory:

```python
config.remove_location("example_data")
config.remove_location("/group/example_data")   # the same thing, by path
config.remove_location("personal")
```

Both functions persist to `~/.config/emdatabase/config.yaml`, which is read on
every import. Pass `persist=False` to change this process only, or use
`config.set` as a context manager for a change that lasts for a block:

```python
config.add_location("/scratch/em", "personal", persist=False)   # this process
with config.set({"data_dir": "/scratch/em"}):                   # this block
    ...
```

The path does not have to exist when you add it — a store may be mounted later —
but you get a warning saying so.

### Seeding a store

`destination=` takes a store's name, which is how the copy gets onto the share in
the first place — run it once, from an account with write access:

```python
from emdatabase import data

data.CuZnHAADF().download(destination="example_data")
```

The file is written with your umask, so `chmod` it group-readable afterwards if
your umask is not; emdatabase does not set permissions for you.

### The keys underneath

Configuration is dask-style: shipped defaults, then every `*.yaml` in
`~/.config/emdatabase/` (or wherever `EMDATABASE_CONFIG` points), then
environment variables, then `config.set` — each layer overriding the one before.
There are two keys, and `add_location` is a wrapper over writing them yourself:

```yaml
# ~/.config/emdatabase/config.yaml
data_dir: /big/disk/emdatabase
stores:
  example_data: /group/example_data
  cluster: /cluster/em_data
```

`data_dir: null` means pooch's cache directory (`~/.cache/emdatabase` on Linux).
`emdatabase.get_data_dir()` and `emdatabase.set_data_dir(path)` wrap `data_dir`.

On HPC, where a config file is often the wrong place to put a machine-specific
path, set the same keys from the environment instead — prefix `EMDATABASE_`,
double underscore to nest — which needs no file and no write access:

```bash
export EMDATABASE_DATA_DIR=/scratch/emdatabase
export EMDATABASE_STORES__GROUP=/group/example_data
```

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
