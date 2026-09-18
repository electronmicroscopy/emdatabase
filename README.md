emdatabase
----------

This is a project for aggregating different Electron Microscopy files which are hosted over different sources. It is intended to simplify downloading example datasets and trained machine learning model weights for tutorials and method validation.

A list of all datasets and model weights can be found in our [docs](https://electronmicroscopy.github.io/emdatabase/datasets.html).

## Installation

```bash
pip install em-database
```
You can install `em-database` via pip or as a local install in the usual way. The distribution is named `em-database` on PyPI; the import name is `emdatabase`. 

## Usage

Examples of how to download data and configure storage locations can be found in our [docs](https://electronmicroscopy.github.io/emdatabase/examples/index.html), as well as in the [quantem-tutorials](https://github.com/electronmicroscopy/quantem-tutorials/tree/main/tutorials/core) repository. 

## Adding a dataset

We welcome contributions of new or existing data! 

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
  technique:
    - 4D-STEM
  license: CC-BY-4.0
```

A dataset may list more than one technique - in-situ 4D-STEM, cryo EELS - and is
then listed under each of them. `emdatabase/index/techniques.yaml` is the
vocabulary they come from: `acquisition` (how the data was taken) and `ml_task`
(what a model does). A dataset declares acquisition techniques only; a
`kind: weights` entry declares one of those plus the ML tasks it performs.

Submissions go through an issue.  Fill in the
[new dataset issue form](https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml)
and an action writes the file and opens the pull request. For very large datasets it might be easier to use the CLI
as described on the [Add Dataset page](https://electronmicroscopy.github.io/emdatabase/add_dataset.html).
See [CONTRIBUTING.md](CONTRIBUTING.md).

