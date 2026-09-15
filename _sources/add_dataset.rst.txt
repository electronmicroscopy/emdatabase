:html_theme.sidebar_secondary.remove:

Add Dataset
===========

Submissions go through an issue. Fill in the `new-dataset issue form
<https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml>`_
and an action turns it into your dataset's YAML file and opens the pull request.
``python -m emdatabase.new_dataset <url>`` does the same thing from a terminal,
computing the checksum locally; see :doc:`Contributing a Dataset <contributing>`.

.. note::

   This page is rendered as a self-contained page during the build (see
   ``build-finished`` in ``conf.py``); this text is a fallback that only shows if
   that generation step fails.
