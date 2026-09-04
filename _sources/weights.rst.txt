:html_theme.sidebar_secondary.remove:

Model Weights
=============

Trained model checkpoints, one entry per model. Downloading an entry follows
its ``latest`` link, which serves whatever the current weights are; every
earlier state of that link is kept as a dated version, pinned to its checksum
and fetched with ``download(version="260902")``.

.. note::

   This page is rendered as a self-contained, widget-styled browser during the
   build (see ``build-finished`` in ``conf.py``); this text is a fallback that
   only shows if that generation step fails. See :doc:`Contributing a Dataset
   <contributing>` for what a weights entry has to declare.
