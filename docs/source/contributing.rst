:html_theme.sidebar_secondary.remove:

Contributing a Dataset
======================

A dataset is one YAML file in ``emdatabase/index/``, validated against
``emdatabase/index/json-schema.json``. Adding one means adding that file.

Three routes
------------

Fill in the `new-dataset issue form
<https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml>`_
and an action turns it into the YAML file and opens a pull request for you. Or
fill in the :doc:`Add Dataset <add_dataset>` form, which builds the YAML in the
browser and sends you to GitHub with the file pre-filled. Or run the CLI below,
which writes the file locally and leaves the pull request to you. All three end
in the same place, and all three run the same validator. Neither web route has
to be given the checksum or the size: a pull request carrying an entry that is
missing either one has the file downloaded and the fields filled in for it.

Techniques
----------

``emdatabase/index/techniques.yaml`` is the technique vocabulary, and an entry
declares its techniques from it. It has two lists: ``acquisition``, which is how
the data was taken, and ``ml_task``, which is what a model does.

A dataset ticks acquisition techniques only, one or more, and is listed under
each of them. A ``kind: weights`` entry ticks one acquisition technique - the
data the model was trained on - and every ML task it performs, at least one.

A technique close to a vocabulary entry fails validation as a misspelling; one
that is nothing like any of them warns and asks for it to be added to
``techniques.yaml``. Adding a technique means adding it there, in the list it
belongs to and in alphabetical order, with ``Other`` staying at the end of
``acquisition``.

Using the web form
------------------

The :doc:`Add Dataset <add_dataset>` form carries every field the schema has,
model weights included. It asks for one **Download link**: the direct link to
the file, which it splits into ``source`` and ``file`` the way the CLI does, or
keeps whole as ``url`` when the file is not served at ``source/file``. A Google
Drive share link - the link the share button copies, ``file/d/<id>/view`` or
``open?id=<id>`` - is rewritten to the ``uc?export=download&id=<id>`` link that
serves the file. The file name is only asked for when the link does not end in
one.

The **Local file** picker fills in the file name, size and md5 from the copy on
your machine, so the checksum need not be computed by hand. The file is read in
the browser and nothing is uploaded; a multi-GB file is hashed a chunk at a
time, with progress under the picker. The three fields it fills stay editable.

**Checksum** and **Size (bytes)** may be left blank, in which case the pull
request downloads the file and fills them in. The picker is the quicker route
for a large file, and a pull request from a fork has to use it, because a fork's
branch cannot be pushed to.

Using the CLI
-------------

.. code-block:: bash

   python -m emdatabase.new_dataset https://zenodo.org/records/15490547/files/PdNiP.zspy

It splits the URL into ``source`` and ``file`` - a Google Drive share link is
rewritten to its ``uc?export=download&id=`` form first - asks the server for
the file's size, streams the file to a temporary location to compute its md5 (deleted
afterwards unless you pass ``--keep``), then prompts for the description,
techniques, licence, detector, microscope, voltage, camera length, DOI, tags
and authors. Techniques and tags are comma-separated, so a dataset that is both
in-situ and 4D-STEM is entered as ``In-situ, 4D-STEM`` and is listed under
each. The technique prompt prints the vocabulary and asks again for anything
outside it. Anything left blank is omitted. It writes
``emdatabase/index/<Name>.yaml`` and refuses to overwrite an existing file
unless you pass ``--force``.

``--checksum md5:...`` skips the download, ``--name`` sets the entry name, and
``--out`` writes somewhere other than the installed package. ``--yes`` takes
the defaults and asks nothing, in which case ``--description`` is required.

By hand
-------

Copy ``emdatabase/index/TEMPLATE.yaml``, which carries every field with a note
on its format and whether it is required, and fill it in. Then check it:

.. code-block:: bash

   python -m emdatabase.new_dataset --validate emdatabase/index/MyDataset.yaml

That prints one line per problem and exits non-zero, or prints ``valid``.
:func:`emdatabase.metadata.validate_file` is the same check from Python.

Contributing model weights
--------------------------

A trained model is an entry like any other, with ``kind: weights`` and a
``model:`` block. One entry per model, named without a version
(``TutorialUNet``): the entry is a family holding every state the weights have
been published in, not a single file.

Save one ``.pt`` per model, holding plain primitives and tensors only:

.. code-block:: python

   torch.save({"state_dict": model.state_dict(), "config": {"hidden": 256}}, path)

It has to load with ``torch.load(path, weights_only=True)`` or it is not
accepted - a pickled ``nn.Module`` executes arbitrary code on load and is tied
to the class's import path. ``config`` carries the architecture arguments the
class needs to be rebuilt.

The entry declares ``model.class`` (the dotted import path),
``model.framework``, ``model.quantem`` (the versions the checkpoint loads
under), ``license``, and its techniques: the acquisition technique of the data
it was trained on, plus every ``ML -`` task it performs. Set the licence from the model's own terms: a model
trained on a dataset does not inherit that dataset's licence.

Point the tooling at the link the weights are published at:

.. code-block:: bash

   python -m emdatabase.new_dataset --kind weights <url>

It asks for the rest and writes two things from that one link: ``latest``,
which follows the link wherever it leads, and ``versions``, holding one dated
snapshot pinned to the md5 the link serves now. ``--version-date YYMMDD`` files
that snapshot under a date other than today; the :doc:`Add Dataset
<add_dataset>` form and the issue form ask for the same date, and take today
when it is left blank.

Retraining a model means re-uploading the file to the same link, or publishing
a new version of the Zenodo record. Nothing in the entry needs editing by hand:
the weekly job below sees the new md5, or the new record, and opens a pull
request adding the new dated version.

``download()`` returns whatever the ``latest`` link serves now. It warns with a
``StaleIndexWarning`` when that md5 is not the one in the index, which happens
whenever the link has moved on since the installed release.
``download(version="260902")`` returns the dated snapshot instead, pinned to its
checksum and failing on a mismatch the way a dataset does.

``download()`` also reads the family's index file from the ``main`` branch,
which the weekly job keeps current, and warns when newer weights are published
there than the installed release knows about; ``download(refresh=True)``
fetches them, pinned to that entry's checksum. The ``check_updates`` config key
turns the check off.

What CI checks
--------------

Every pull request runs the test suite, which validates each YAML file in
``index/`` (the template included) against the schema, and checks the vendor
names in ``vendors.yaml`` and the techniques in ``techniques.yaml``: a name
close to one already on the list fails as a misspelling, while a genuinely new
one warns and asks for it to be added. A weights entry without an ML task, and
a dataset with one, fail as well.

``fill_download_fields.yml`` runs on every pull request that touches
``emdatabase/index/``. It downloads the file behind each changed entry that is
missing its ``checksum`` or ``size_bytes`` - a weights family's ``latest`` and
each dated version on their own links - fills the fields in and pushes the
result back to the branch, which is how an entry from the web form or the issue
form ends up complete. A fork's branch cannot be pushed to, so a pull request
from one fails instead and prints the values to paste in.

``check_sources.yml`` runs weekly and asks each source server whether the file
is still there and still the size the entry claims.

``check_weights.yml`` runs weekly as well, and what it does depends on where
the family is hosted.

For a link that moves in place, such as Google Drive, it downloads the
``latest`` link and compares the md5 with the index. An unchanged file is
archived on the first run that finds it unarchived, so a newly contributed
entry stops depending on the contributor's link. A changed file becomes a new
dated version, added in a pull request together with the new ``latest``
checksum. The archive is the ``weights-archive`` release on this repository; a
file over 500 MB goes to the workflow run as an artifact instead, and a
maintainer uploads it to the release by hand. A link that answers with
``text/html`` - a Google Drive virus-scan page rather than the file - is
reported and nothing is archived.

For a Zenodo record file, nothing is downloaded and nothing is copied to
GitHub. The job asks the Zenodo API for the newest record of the concept the
current record belongs to. If that is still the record the entry points at, the
run reports it unchanged, and reports an error if the API's md5 is not the one
in the index. If a newer record has been published, the job adds a dated
version - dated by the new record's publication date - pointing at the file in
that record, and moves ``latest`` to it. The file it looks for in the new
record is the one whose name matches the current link; if the name has changed
and the record holds more than one file, the run fails rather than guess.

Hosting
-------

Zenodo is preferred: it gives a DOI, a stable URL and a record that is not
going to be rewritten. A GitHub URL is acceptable if it is pinned to a commit
SHA. A URL on a moving branch is not, because the file behind it can change
without the checksum changing with it.

A weights entry's ``latest`` is the one exception: it is meant to move, because
it follows the model's published link, and every state that link has served is
kept as a dated version pinned to its own checksum. A dataset, and a weights
entry's dated versions, stay pinned.

For weights on Zenodo, give the current record's file link,
``https://zenodo.org/records/<id>/files/<name>``. A concept DOI has no static
file URL, so the link names one record; the weekly job follows that record's
concept through the API and, when a new record is published, adds a dated
version pointing at it and moves ``latest`` there. Nothing is copied to GitHub:
a Zenodo record's files are immutable, so the record is already the archive.
GitHub archival is only for links that move in place, Google Drive among them.

Google Drive works for a small file, as a
``https://drive.google.com/uc?export=download&id=<id>`` link written to the
entry's ``url``; above about 100 MB Drive answers with a virus-scan page
instead of the file, and the entry will not download. All three routes take the
share link as well and rewrite it to that form, and fill in ``url``, ``source``
and ``file`` themselves.
