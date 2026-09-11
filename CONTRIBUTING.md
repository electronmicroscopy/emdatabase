# Contributing

A dataset is one YAML file in `emdatabase/index/`. To add one, fill in the
[new-dataset issue form](https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml)
and an action turns it into that file and opens the pull request for you. The
[Add Dataset page](https://electronmicroscopy.github.io/emdatabase/add_dataset.html)
says what to have ready: one download link - a Google Drive share link included - a
description, the licence, the technique, and the authors as `Name; Affiliation; ORCID`,
one per line.

If you would rather stay in a terminal, run

```bash
python -m emdatabase.new_dataset https://zenodo.org/records/<record>/files/<file>
```

which fetches the checksum and size, prompts for the rest and writes the file.
Model weights live in the same index: add `--kind weights`.

Neither route needs the checksum or the size: an entry missing either one has the file
downloaded on GitHub and the fields filled in for it, unless the pull request comes from
a fork, whose branch cannot be pushed to.

Full instructions, including what to do by hand and what CI checks: <https://electronmicroscopy.github.io/emdatabase/contributing.html>.
