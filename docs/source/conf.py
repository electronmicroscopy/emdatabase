# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

# Sphinx no longer puts the config directory on sys.path, and the script that
# generates the app pages is a sibling of this file.
sys.path.insert(0, str(Path(__file__).parent))
# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from _build_docs import (  # noqa: E402
    generate_add_dataset_html,
    generate_all_data_html,
    generate_browser_html,
    generate_html_table,
    generate_landing_html,
    generate_weights_html,
    parse_datasets,
)

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "emdatabase"
copyright = "2026, Carter Francis"
author = "Carter Francis"
release = "0.5.0.dev0"

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
# intro.rst / datasets.rst are superseded by the generated landing + All Data
# app pages; keep the files but leave them out of the build so they don't warn
# about being orphaned.
exclude_patterns = ["intro.rst", "datasets.rst"]


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
_unused_sidebars = {
    "index": [],
    "all_data": [],
    "add_dataset": [],
    "weights": [],
    "datasets": [],
}


def build_datasets_html(app, exception):
    """Generate datasets.html during Sphinx build"""
    if exception is not None:
        print(f"Build exception: {exception}")
    datasets_path = Path(__file__).parent.parent.parent / "emdatabase" / "index"
    print(f"Looking for datasets at: {datasets_path.absolute()}")
    print(f"Path exists: {datasets_path.exists()}")
    if datasets_path.exists():
        print(f"Contents: {list(datasets_path.iterdir())}")
    datasets = parse_datasets(datasets_path)
    print(f"Found {len(datasets)} datasets for documentation.")
    print(datasets)
    html_output = generate_html_table(datasets)

    output_path = Path(app.outdir) / "datasets_db.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(html_output)

    # Generated, self-contained Catppuccin "app" pages. Each is written into the
    # build output (overwriting the Sphinx-rendered page where names collide:
    # index.html, all_data.html, weights.html, add_dataset.html) so the site looks like
    # emdatabase.browse(). Each is guarded so a failure never kills the build.
    outdir = Path(app.outdir)
    pages = {
        "index.html": generate_landing_html,
        "all_data.html": generate_all_data_html,
        "add_dataset.html": generate_add_dataset_html,
        "weights.html": generate_weights_html,
        "datasets_browser.html": generate_browser_html,
    }
    for filename, generator in pages.items():
        try:
            (outdir / filename).write_text(generator(), encoding="utf-8")
            print(f"Wrote {filename}")
        except Exception as e:  # pragma: no cover - keep the build alive
            print(f"Could not build {filename}: {e}")


def setup(app):
    app.connect("build-finished", build_datasets_html)


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
}
