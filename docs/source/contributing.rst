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
run the CLI below, which writes the file locally and leaves the pull request to
you. Both end in the same place, and both run the same validator. The
:doc:`Add Dataset <add_dataset>` form and the issue form carry every field the
schema has, including model weights and a ``url`` for a download link that is
not ``source/file``.

Using the CLI
-------------

.. code-block:: bash

   python -m emdatabase.new_dataset https://zenodo.org/records/15490547/files/PdNiP.zspy

It splits the URL into ``source`` and ``file``, asks the server for the file's
size, streams the file to a temporary location to compute its md5 (deleted
afterwards unless you pass ``--keep``), then prompts for the description,
technique, licence, detector, microscope, voltage, camera length, DOI, tags and
authors. Anything left blank is omitted. It writes
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
``model:`` block. One entry per released version, named with the version on the
end (``DemoNet_v3``), because the entry pins one file and one checksum.

Save one ``.pt`` per model, holding plain primitives and tensors only:

.. code-block:: python

   torch.save({"state_dict": model.state_dict(), "config": {"hidden": 256}}, path)

It has to load with ``torch.load(path, weights_only=True)`` or it is not
accepted - a pickled ``nn.Module`` executes arbitrary code on load and is tied
to the class's import path. ``config`` carries the architecture arguments the
class needs to be rebuilt.

The entry declares ``version``, ``model.class`` (the dotted import path),
``model.framework``, ``model.quantem`` (the versions the checkpoint loads
under) and ``license``. Set the licence from the model's own terms: a model
trained on a dataset does not inherit that dataset's licence.

``python -m emdatabase.new_dataset --kind weights <url>`` asks for all of it.

What CI checks
--------------

Every pull request runs the test suite, which validates each YAML file in
``index/`` (the template included) against the schema, and checks the vendor
names in ``vendors.yaml``: a name close to one already on the list fails as a
misspelling, while a genuinely new one warns and asks for it to be added. A
weekly job asks each source server whether the file is still there and still
the size the entry claims.

Hosting
-------

Zenodo is preferred: it gives a DOI, a stable URL and a record that is not
going to be rewritten. A GitHub URL is acceptable if it is pinned to a commit
SHA. A URL on a moving branch is not, because the file behind it can change
without the checksum changing with it.

Google Drive works for a small file, as a
``https://drive.google.com/uc?export=download&id=<id>`` link written to the
entry's ``url``; above about 100 MB Drive answers with a virus-scan page
instead of the file, and the entry will not download. The CLI recognises a link
like that and fills in ``url``, ``source`` and ``file`` itself.
