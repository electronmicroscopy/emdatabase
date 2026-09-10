# Contributing

A dataset is one YAML file in `emdatabase/index/`. To add one, either fill in the
[new-dataset issue form](https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml),
which opens the pull request for you, or the
[Add Dataset form](https://electronmicroscopy.github.io/emdatabase/add_dataset.html),
which takes one download link - a Google Drive share link included - and fills in the
file name, size and md5 from your local copy of the file. Or run

```bash
python -m emdatabase.new_dataset https://zenodo.org/records/<record>/files/<file>
```

which fetches the checksum and size, prompts for the rest and writes the file.
Model weights live in the same index: add `--kind weights`.

Neither form needs the checksum or the size: a pull request carrying an entry that is
missing either one has the file downloaded on GitHub and the fields filled in for it,
unless it comes from a fork, whose branch cannot be pushed to.

Full instructions, including what to do by hand and what CI checks: <https://electronmicroscopy.github.io/emdatabase/contributing.html>.
