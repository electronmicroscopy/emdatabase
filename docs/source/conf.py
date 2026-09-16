# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

# Sphinx no longer puts the config directory on sys.path, and the script that
# generates the app pages is a sibling of this file.
sys.path.insert(0, str(Path(__file__).parent))

from _build_docs import PAGES  # noqa: E402

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "emdatabase"
copyright = "2026, Carter Francis"
author = "Carter Francis"
release = "0.4.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_gallery.gen_gallery",
    "sphinx_design",
]

templates_path = ["_templates"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
master_doc = "index"

# Dark Catppuccin-Mocha by default, to match the generated app pages.
html_context = {"default_mode": "dark"}

# Top navigation: Examples / API / All Data / Model Weights / Add Dataset.
# Examples and API are Sphinx-generated (sphinx-gallery + autodoc); the rest are
# the generated app pages, in the toctree so pydata builds correct relative links
# to them from every page (their HTML output is then overwritten with the app
# page in the build-finished hook below).
html_theme_options = {
    "logo": {"text": "◆ EM-Database"},
    "navbar_start": ["navbar-logo"],
    "navbar_center": ["navbar-nav"],
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
    "navbar_persistent": [],
    "show_prev_next": False,
    # Simple: no left sidebar, no right ("Show Source"/on-this-page) sidebar,
    # no breadcrumbs; a minimal footer.
    "secondary_sidebar_items": {"**": []},
    "footer_start": ["copyright"],
    "footer_center": [],
    "footer_end": [],
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/electronmicroscopy/emdatabase",
            "icon": "fa-brands fa-github",
        },
    ],
}

# No left sidebar anywhere - keep every page a single, full-width column.
html_sidebars = {"**": []}


def write_app_pages(app, exception):
    """Write the generated app pages over the Sphinx pages of the same name.

    A page that fails to generate fails the build, rather than publishing the
    placeholder text Sphinx rendered in its place.
    """
    if exception is None:
        for filename, generate in PAGES.items():
            (Path(app.outdir) / filename).write_text(generate(), encoding="utf-8")


def setup(app):
    app.connect("build-finished", write_app_pages)


# sphinx_gallery
# --------------
# https://sphinx-gallery.github.io/stable/configuration.html

sphinx_gallery_conf = {
    "examples_dirs": "../../examples",
    "gallery_dirs": "examples",
    "filename_pattern": "^((?!sgskip).)*$",
    "ignore_pattern": "_sgskip.py",
    "backreferences_dir": "api",
    "doc_module": ("deapi",),
    "reference_url": {
        "deapi": None,
    },
    # The examples download from Zenodo, which has outages; a failed example
    # then costs its output, not the whole site.
    "only_warn_on_example_error": True,
}
