:html_theme.sidebar_secondary.remove:

Contributing a Dataset
======================

A dataset is one YAML file in ``emdatabase/index/``, validated against
``emdatabase/index/json-schema.json``. Adding one means adding that file.

Two routes
----------

Fill in the `new-dataset issue form
<https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml>`_
and an action turns it into the YAML file and opens a pull request for you. The
:doc:`Add Dataset <add_dataset>` page says what to have ready before you start
and links to the form.

Or run the CLI below, which asks the same questions in a terminal and writes the
file locally, leaving the pull request to you. Both routes end in the same file
and both run the same validator. Neither has to be given the checksum or the
size: an entry missing either one has the file downloaded and the fields filled
in for it.

The issue form takes one **URL**: the direct link to the file, which is split
into ``source`` and ``file`` the way the CLI splits it, or kept whole as ``url``
when the file is not served at ``source/file``. A Google Drive share link - the
link the share button copies, ``file/d/<id>/view`` or ``open?id=<id>`` - is
rewritten to the ``uc?export=download&id=<id>`` link that serves the file. The
file name is only asked for when the link does not end in one. **Authors** is
one author per line, as ``Name; Affiliation; ORCID``, with the ORCID optional.

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

A file inside an archive
------------------------

Some data worth shipping is one file inside a multi-gigabyte ``.zip`` or ``.7z``
on a record nobody can re-publish, where downloading all of it to get one file is
not reasonable. Such an entry adds an ``archive`` block naming the archive and
every file taken out of it:

.. code-block:: yaml

   archive:
     url: https://zenodo.org/records/0000000/files/Figures.zip
     members:
       - member: Figure_01/Panel_a/scan_x128_y128.raw
         file: MyDatasetName/scan_x128_y128.raw
         checksum: md5:0123456789abcdef0123456789abcdef
         size_bytes: 1000000

``download()`` then fetches only those members, over HTTP range requests: a few
requests read the archive's directory, and only the member's own bytes follow.
What comes back is a path, as for any other entry. The format is taken from the
link's file name, so no field declares it.

What that costs differs by format. A zip compresses each member on its own, so
one member is read and streamed directly. A 7z compresses files together in
solid blocks, so reaching a member means decompressing its block from the start:
cheap for a file at the front of a small block, expensive for one at the back of
a large one. It is worth measuring before adding a 7z entry - in the archive
behind ``MOSS6Fig3`` the same 15.3 GB file holds members costing
anywhere from 2 MB to 2.6 GB to reach. Note also that 7z is extracted rather
than streamed, so its progress bar fills in one step at the end and a cancel
cannot interrupt it.

An archive entry leaves out the top-level ``file``, ``checksum`` and
``size_bytes``. The first two are the first member's, stated there instead so
that no fact about a file appears at two levels; the entry's ``size_bytes`` is
every member's added up, which is the one number ``size`` shows. ``checksum`` and
``size_bytes`` directly under ``archive`` describe the archive itself, and are
optional. Give ``member`` as the complete path inside the archive - one file name
can appear in several of its directories, so a basename alone is ambiguous.

Data that is more than one file lists them all under ``members``. The first is
what ``download()`` returns; the rest arrive beside it. Give them a directory of
their own when a reader expects to find them together - an EMPAD ``.xml`` names
its ``.raw`` by bare file name and opens it next to itself, so
``MyDataset/acquisition_12.xml`` and ``MyDataset/scan_x256_y256.raw`` both keeps
the pairing and keeps it clear of identically named members elsewhere.
``delete()`` removes them all, and the size shown in the catalogue counts them.

These entries are written by hand. The two fields CI otherwise fills in would be
taken from the archive rather than from the member, so a pull request leaving any
member's blank is refused rather than guessed at. ``download_url``, and the download
link on the docs site, point at the archive: the member has no link of its own.

A host that ignores ``Range`` and answers with the whole archive fails loudly,
naming the host, rather than quietly pulling gigabytes.

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
that snapshot under a date other than today; the issue form asks for the same
date, and takes today when it is left blank.

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
``emdatabase/index/``, which is to say on hand-edited and CLI-written index
files. It downloads the file behind each changed entry that is missing its
``checksum`` or ``size_bytes`` - a weights family's ``latest`` and each dated
version on their own links - fills the fields in and pushes the result back to
the branch. An entry naming an ``archive`` is refused instead: each member's
``checksum`` and ``size_bytes`` describe that file inside the zip, and the only
thing there is to download is the whole archive, so they are filled in by hand. A
fork's branch cannot be pushed to, so a pull request from one
fails instead and prints the values to paste in. An entry coming in through the
issue form is filled in the same way before its pull request is opened, so it
arrives complete.

``check_sources.yml`` runs weekly and asks each source server whether the file
is still there and still the size the entry claims. For an entry fetched out of
an archive it reads the archive's directory too, over a few range requests, and
checks the member is still there at the size the entry declares.

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

Removing an entry
-----------------

Delete the entry's file from ``emdatabase/index/``, run
``python -m emdatabase._create_stubs`` so ``emdatabase/data/__init__.pyi`` no
longer lists it, and open a pull request. Copies people have already downloaded
are not touched. If the weekly weights job archived versions of a weights family
to the ``weights-archive`` release, delete those assets too::

    gh release delete-asset weights-archive <Family>_<date>.pt

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
instead of the file, and the entry will not download. Both routes take the
share link as well and rewrite it to that form, and fill in ``url``, ``source``
and ``file`` themselves.
