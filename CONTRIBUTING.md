# Contributing

A dataset is one YAML file in `emdatabase/index/`. To add one, either fill in the
[new-dataset issue form](https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml),
which opens the pull request for you, or run

```bash
python -m emdatabase.new_dataset https://zenodo.org/records/<record>/files/<file>
```

which fetches the checksum and size, prompts for the rest and writes the file.
Model weights live in the same index: add `--kind weights`.

Full instructions, including what to do by hand and what CI checks: <https://electronmicroscopy.github.io/emdatabase/contributing.html>.
