:html_theme.sidebar_secondary.remove:

Add Dataset
===========

A submission form that opens a pre-filled GitHub pull request adding your
dataset's YAML file. ``python -m emdatabase.new_dataset <url>`` does the same
thing from a terminal, and fills in the checksum and size for you; see
:doc:`Contributing a Dataset <contributing>`.

.. note::

   This page is rendered as a self-contained form during the build (see
   ``build-finished`` in ``conf.py``); this text is a fallback that only shows if
   that generation step fails. You can also submit a dataset via the
   `new-dataset issue form
   <https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml>`_.
