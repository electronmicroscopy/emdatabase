"""The docs site's app pages, written over Sphinx's output by ``conf.py``.

Every page is self-contained: the widget's CSS and shared JS are inlined, the
catalogue is baked in as JSON at build time, and nothing is loaded from
outside, so search and the list work with no backend.
"""

import json
from html import escape
from importlib import resources
from pathlib import Path

from emdatabase.metadata import acquisition_techniques, versioned_filename

_STATIC = resources.files("emdatabase") / "static"

# The browser on the landing, All Data and Model Weights pages: the widget's
# layout over DATA, with its tab list TABS and what it lists, LABEL, all baked in
# next to it. A static site has no kernel, so instead of Download and Delete the
# details panel offers the load snippet and a direct link to the file.
# common.js is put in front of it.
_DOCS_BROWSER_JS = r"""
(() => {
  const root = document.getElementById("root");
  root.classList.add("emdb");
  const what = LABEL.toLowerCase();
  const state = { tab: "All", search: "", selected: null, hovered: null };
  const view = { versions: {}, redraw: () => drawDetails() };
  const allItems = DATA.groups.flatMap((g) => g.items);

  const header = el("div", "emdb-header");
  const top = el("div", "emdb-header-top", `<div class="emdb-brand">${esc(LABEL)}</div>`);
  top.appendChild(el("div", "emdb-count", `${DATA.n_total} ${what}`));
  const search = el("input", "emdb-search");
  search.type = "text";
  search.placeholder = `Search ${what}…`;
  search.addEventListener("input", () => { state.search = search.value; drawList(); });
  header.append(top, search);
  const tabsEl = el("div", "emdb-tabs");
  const listEl = el("div", "emdb-list");
  const detailsEl = el("div", "emdb-details");
  const body = el("div", "emdb-body");
  body.append(listEl, detailsEl);
  root.append(header, tabsEl, body);

  function drawRow(item) {
    const row = el("div", "emdb-row" + (state.selected === item.name ? " selected" : ""));
    row.append(el("span", "emdb-glyph off", "•"), el("span", "emdb-name", esc(item.name)),
      el("span", "emdb-meta", esc(item.size)));
    row.addEventListener("mouseenter", () => { state.hovered = item.name; drawDetails(); });
    row.addEventListener("click", () => { state.selected = item.name; drawList(); });
    return row;
  }

  function drawList() {
    fillList(listEl, DATA.groups, state, drawRow, `No ${what} match.`);
    state.selected ??= allItems[0]?.name;
    drawDetails();
  }

  // CamelCase class name -> snake_case variable, e.g. AlNanocrystals -> al_nanocrystals.
  function toSnake(name) {
    return name.replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2").toLowerCase();
  }

  function drawDetails() {
    const item = allItems.find((it) => it.name === (state.hovered || state.selected));
    if (!item) {
      detailsEl.innerHTML = `<div class="emdb-details-empty">Hover or select an entry.</div>`;
      return;
    }
    const version = shownVersion(item, view);
    const pin = versionState(item, version);  // its link, checksum and saved file name
    detailsEl.innerHTML = "";
    drawHead(detailsEl, item, version, view);
    if (item.description) detailsEl.appendChild(el("p", "emdb-d-desc", esc(item.description)));
    const md5 = item.kind === "weights" ? (version ? pin.checksum : item.latest_checksum) : "";
    detailsEl.appendChild(drawMeta(item, [["md5", (md5 || "").replace(/^md5:/, "")]]));

    detailsEl.appendChild(el("div", "emdb-load-label", "Load"));
    const call = version ? `().download(version="${version}")` : "().download()";
    detailsEl.appendChild(copyRow(item.kind === "weights"
      ? `import torch\nfrom emdatabase import data\n\npath = data.${item.name}${call}\n`
        + "checkpoint = torch.load(path, weights_only=True)"
      : `${toSnake(item.name)} = emdatabase.data.${item.name}()`));
    const link = el("a", "emdb-dl-anchor");
    link.href = pin.url;
    link.target = "_blank";
    link.rel = "noopener";
    // An archive entry's only link is the zip the file lives inside, so the
    // label names the archive rather than a file the link does not serve.
    link.textContent = item.archive
      ? `⤓ Download ${pin.url.split("/").pop()} (archive holding ${item.archive})`
      : `⤓ Download ${pin.file}`;
    const wrap = el("div", "emdb-dl-link");
    wrap.appendChild(link);
    detailsEl.appendChild(wrap);
  }

  fillTabs(tabsEl, TABS, state, drawList);
  drawList();
})();
"""

# Palette + top-nav + hero, keyed to the same Catppuccin tokens browser.css
# defines on .emdb (mirrored here on :root so the nav and hero get them too).
_APP_CSS = """
:root {
  --emdb-base: #1e1e2e; --emdb-mantle: #181825; --emdb-crust: #11111b;
  --emdb-surface0: #313244; --emdb-surface1: #45475a; --emdb-surface2: #585b70;
  --emdb-overlay: #2a2a3c; --emdb-text: #cdd6f4; --emdb-subtext: #a6adc8;
  --emdb-muted: #7f849c; --emdb-blue: #89b4fa; --emdb-mauve: #cba6f7;
  --emdb-green: #a6e3a1; --emdb-red: #f38ba8;
  --emdb-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --emdb-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--emdb-base); color: var(--emdb-text);
  font-family: var(--emdb-font); font-size: 16px; line-height: 1.55; min-height: 100vh;
}
a { color: var(--emdb-blue); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Top navigation ----------------------------------------------------- */
.app-nav {
  position: sticky; top: 0; z-index: 50;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 10px 22px; background: linear-gradient(#1c1c2b, var(--emdb-mantle));
  border-bottom: 1px solid var(--emdb-surface0); box-shadow: 0 2px 16px rgba(0, 0, 0, 0.35);
}
.app-brand {
  font-size: 16px; font-weight: 800; letter-spacing: 0.2px; margin-right: auto;
  display: flex; align-items: center; gap: 8px; color: var(--emdb-text);
}
.app-brand:hover { text-decoration: none; }
.app-navlink {
  font-size: 14px; font-weight: 600; color: var(--emdb-subtext);
  padding: 7px 15px; border-radius: 999px; border: 1px solid transparent;
}
.app-navlink:hover { color: var(--emdb-text); background: var(--emdb-overlay); text-decoration: none; }
.app-navlink.active {
  color: var(--emdb-blue); background: rgba(137, 180, 250, 0.14);
  border-color: rgba(137, 180, 250, 0.4);
}

.app-main { max-width: 100%; margin: 0; padding: 20px 40px 60px; }

/* Hero: large on the landing page, smaller (.page) on the others ------ */
.app-hero { text-align: center; padding: 30px 0 14px; }
.app-hero h1 {
  margin: 0; font-size: 40px; font-weight: 800; letter-spacing: -0.5px; line-height: 1.1;
  background: linear-gradient(135deg, #89b4fa, #cba6f7);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.app-hero.page { padding: 18px 0 4px; }
.app-hero.page h1 { font-size: 30px; }
.app-hero p { margin: 12px auto 0; max-width: 720px; color: var(--emdb-subtext); font-size: 16px; }
.app-hero code {
  font-family: var(--emdb-mono); background: var(--emdb-crust);
  border: 1px solid var(--emdb-surface0); border-radius: 5px; padding: 1px 6px; color: var(--emdb-text);
}
"""

# Overrides so the embedded browser fills the docs width (browser.css caps
# .emdb at 75% for the notebook) and styles the static download link.
_BROWSER_OVERRIDES = """
.emdb { max-width: 100%; margin: 8px 0 0; font-size: 14px; }
.emdb-body { height: 620px; }
.emdb-list { min-width: 360px; max-width: 50%; }
.emdb-dl-link { margin-top: 14px; }
.emdb-dl-anchor { color: var(--emdb-blue); text-decoration: none; font-size: 14px; font-weight: 600; }
.emdb-dl-anchor:hover { text-decoration: underline; }
/* Bigger, more legible text on the website (the notebook widget stays compact) */
.emdb-search { font-size: 15px; padding: 10px 13px; }
.emdb-tab { font-size: 13.5px; padding: 5px 13px; }
.emdb-count { font-size: 13px; }
.emdb-group-head { font-size: 11.5px; }
.emdb-name { font-size: 14.5px; }
.emdb-meta { font-size: 13px; }
.emdb-glyph { font-size: 12px; }
.emdb-d-title { font-size: 20px; }
.emdb-d-sub { font-size: 13.5px; }
.emdb-d-desc { font-size: 14.5px; line-height: 1.6; max-width: 760px; }
.emdb-kv { font-size: 13.5px; }
.emdb-k { flex-basis: 92px; }
.emdb-code { font-size: 13px; }
.emdb-load-label { font-size: 12px; }
.emdb-copy-btn { font-size: 13px; }
/* Keep the metadata a tidy two-column block instead of sprawling edge to edge */
.emdb-d-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); max-width: 820px; gap: 6px 30px; }
"""

# Styling for the Add Dataset explainer page.
_EXPLAINER_CSS = """
.explainer { max-width: 780px; margin: 0 auto; }
.explainer h2 {
  font-size: 13px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--emdb-subtext); margin: 34px 0 12px; padding-top: 18px;
  border-top: 1px solid var(--emdb-surface0);
}
.explainer code {
  font-family: var(--emdb-mono); font-size: 13.5px; color: var(--emdb-text);
  background: var(--emdb-crust); border: 1px solid var(--emdb-surface0);
  border-radius: 5px; padding: 1px 6px;
}
.explainer pre {
  margin: 0 0 14px; padding: 14px; overflow-x: auto;
  background: var(--emdb-crust); border: 1px solid var(--emdb-surface0); border-radius: 10px;
  font-family: var(--emdb-mono); font-size: 13px;
}
.explainer pre code { background: none; border: 0; padding: 0; }
.note { font-size: 14px; color: var(--emdb-subtext); }
.submit-row { display: flex; justify-content: center; margin: 28px 0 4px; }
.btn-primary {
  display: inline-block; font-weight: 700; font-size: 15px; text-align: center;
  color: var(--emdb-crust); background: linear-gradient(135deg, var(--emdb-blue), var(--emdb-mauve));
  border: 0; border-radius: 9px; padding: 13px 26px;
}
.btn-primary:hover { filter: brightness(1.06); text-decoration: none; }
"""

# Top-nav destinations. Examples and API are Sphinx-generated (sphinx-gallery +
# autodoc); the rest are the generated app pages. Every page sits at the site
# root, so these relative links resolve the same from each of them.
_NAV_LINKS = (
    ("Examples", "examples/index.html"),
    ("API", "reference/index.html"),
    ("All Data", "all_data.html"),
    ("Model Weights", "weights.html"),
    ("Add Dataset", "add_dataset.html"),
)


def _app_page(
    title: str, body: str, active: str = "", extra_css: str = "", scripts: str = ""
) -> str:
    """Wrap page ``body`` in the self-contained Catppuccin app shell.

    Built by concatenation (not ``str.format``/``%``) so CSS/JS braces need no
    escaping.
    """
    nav = '<nav class="app-nav"><a class="app-brand" href="index.html">EM-Database</a>'
    for name, url in _NAV_LINKS:
        cls = "app-navlink active" if name == active else "app-navlink"
        nav += f'<a class="{cls}" href="{url}">{name}</a>'
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>" + escape(title) + "</title>\n"
        "<style>\n"
        + (_STATIC / "browser.css").read_text(encoding="utf-8")
        + _APP_CSS
        + extra_css
        + "</style>\n</head>\n<body>\n"
        + nav
        + "</nav>\n"
        + body
        + "\n"
        + scripts
        + "\n</body></html>\n"
    )


def _catalogue_payload(kind: str):
    """``(payload, tabs)`` - the catalogue to bake into a page, and its tab list.

    Tabs are every acquisition technique, so one with no dataset in it yet
    still shows, plus anything else present, in the browser's group order; the
    weights page has its one group. What is on the build machine's disk is no
    concern of a reader's, so it is left out, and each version is given the
    name it is saved under.
    """
    from emdatabase import catalogue

    cat = catalogue.catalogue(kind=kind)
    for group in cat["groups"]:
        for item in group["items"]:
            item.update(downloaded=False, location=None, path="", user_path="")
            for row in item["versions"]:
                row.update(downloaded=False, location=None, path="")
                row["file"] = versioned_filename(item["file"], row["version"])
    payload = {"groups": cat["groups"], "n_total": cat["n_total"]}
    present = [group["technique"] for group in cat["groups"]]
    if kind == "weights":
        return payload, present
    return payload, catalogue.ordered_groups([*acquisition_techniques(), *present])


def _browser_page(
    title: str, hero: str, active: str = "", kind: str = "dataset", label: str = "Datasets"
) -> str:
    """A page with ``hero`` above the browser over entries of ``kind``."""
    payload, tabs = _catalogue_payload(kind)
    script = (
        "<script>\n"
        f"const DATA = {json.dumps(payload)};\n"
        f"const TABS = {json.dumps(tabs)};\n"
        f"const LABEL = {json.dumps(label)};\n"
        + (_STATIC / "common.js").read_text(encoding="utf-8")
        + _DOCS_BROWSER_JS
        + "</script>"
    )
    body = '<main class="app-main">' + hero + '<div id="root"></div></main>'
    return _app_page(title, body, active, _BROWSER_OVERRIDES, script)


def generate_landing_html() -> str:
    """The landing page: hero + the widget-style search / tabs / list browser."""
    return _browser_page(
        "EM-Database",
        '<div class="app-hero">'
        "<h1>EM-Database</h1>"
        "<p>A curated, citable collection of electron microscopy datasets &mdash; "
        "a couple of lines of Python from your analysis. Search below, then copy the "
        "snippet to load one with <code>emdatabase.data.&lt;Name&gt;()</code>.</p>"
        "</div>",
    )


def generate_all_data_html() -> str:
    """The All Data page: the full widget-style dataset browser with nav."""
    return _browser_page(
        "All Data · EM-Database",
        '<div class="app-hero page">'
        "<h1>All Data</h1>"
        "<p>Every dataset in the collection. Search across names, techniques, "
        "authors, detectors and tags; filter by technique with the tabs.</p>"
        "</div>",
        active="All Data",
    )


def generate_weights_html() -> str:
    """The Model Weights page: the same browser, over the weights entries.

    Each entry is one model, with a ``latest`` link and a dated version for
    every state that link has served. emdatabase downloads the checkpoint and
    nothing else, so the load snippet is where the page says how to open it -
    ``weights_only=True``, which is the condition of a checkpoint being
    accepted in the first place.
    """
    return _browser_page(
        "Model Weights · EM-Database",
        '<div class="app-hero page">'
        "<h1>Model Weights</h1>"
        "<p>Trained model checkpoints, one entry per model. Downloading an entry "
        "follows its <code>latest</code> link, which serves whatever the current "
        "weights are; every earlier state of that link is kept as a dated version, "
        "pinned to its checksum. Pick one with the selector; the load snippet "
        "opens it with <code>weights_only=True</code>.</p>"
        "<p><code>download()</code> warns when the index on the project's "
        "<code>main</code> branch has newer weights than your installed release, "
        "and <code>download(refresh=True)</code> fetches them; the "
        "<code>check_updates</code> config key turns that check off.</p>"
        "</div>",
        active="Model Weights",
        kind="weights",
        label="Model weights",
    )


# The new-dataset issue form: the one submission route the page points at.
_ISSUE_URL = (
    "https://github.com/electronmicroscopy/emdatabase/issues/new?template=new_dataset.yaml"
)

_CLI_COMMAND = (
    "python -m emdatabase.new_dataset https://zenodo.org/records/15490547/files/PdNiP.zspy"
)


def generate_add_dataset_html() -> str:
    """The Add Dataset page: the issue form, and the CLI as the terminal route."""
    body = (
        '<main class="app-main"><div class="explainer">'
        '<div class="app-hero page">'
        "<h1>Add a Dataset</h1>"
        "<p>Submissions go through an issue. Fill in the new-dataset issue form and "
        "an action turns it into the entry’s YAML file, fills in whatever it can "
        "work out for itself, and opens the pull request.</p>"
        "</div>"
        '<p class="note">The checksum and the size are filled in automatically by '
        "downloading the file, so both can be left blank.</p>"
        '<div class="submit-row">'
        '<a class="btn-primary" target="_blank" rel="noopener" href="'
        + _ISSUE_URL
        + '">Open the issue form &#8599;</a>'
        "</div>"
        "<h2>From a terminal</h2>"
        "<pre><code>" + escape(_CLI_COMMAND) + "</code></pre>"
        "<p>It asks the same questions at the prompt and writes the YAML file, leaving "
        "the pull request to you. A trained model checkpoint takes "
        "<code>--kind weights</code> as well.</p>"
        "<p>It computes the checksum from the file on your own machine rather than on "
        "GitHub, which is the route to take for a very large file.</p>"
        '<p class="note">Full instructions, including writing the entry by hand and '
        'what CI checks: <a href="contributing.html">Contributing a Dataset</a>.</p>'
        "</div></main>"
    )
    return _app_page("Add Dataset · EM-Database", body, "Add Dataset", _EXPLAINER_CSS)


# What conf.py writes over the Sphinx page of the same name.
PAGES = {
    "index.html": generate_landing_html,
    "all_data.html": generate_all_data_html,
    "weights.html": generate_weights_html,
    "add_dataset.html": generate_add_dataset_html,
}


if __name__ == "__main__":
    # Write every page to ./_docs_preview, to open in a browser without a Sphinx build.
    out = Path("_docs_preview")
    out.mkdir(exist_ok=True)
    for filename, generate in PAGES.items():
        (out / filename).write_text(generate(), encoding="utf-8")
    print("Wrote preview pages to", out.resolve())
