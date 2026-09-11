# Contributing

A dataset is one YAML file in `emdatabase/index/`. To add one, fill in the
[new-dataset issue form](https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml)
and an action turns it into that file and opens the pull request for you. The
[Add Dataset form](https://electronmicroscopy.github.io/emdatabase/add_dataset.html)
is the easier way in: it takes one download link - a Google Drive share link included -
fills in the file name, size and md5 from your local copy of the file, checks
everything, and opens the issue form with all of it already filled in.

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
