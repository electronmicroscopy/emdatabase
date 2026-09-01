import json
from collections import defaultdict
from importlib import resources
from pathlib import Path

import yaml

from emdatabase.metadata import NON_DATASET_FILES, load_vendors


def parse_datasets(yaml_dir):
    """Parse all YAML files and organize by technique."""
    datasets_by_technique = defaultdict(list)

    for yaml_file in sorted(Path(yaml_dir).glob("*.yaml")):
        if yaml_file.name in NON_DATASET_FILES:
            continue
        with open(yaml_file, "r") as f:
            data = yaml.safe_load(f)

        for name, info in data.items():
            if info.get("kind") == "weights":
                continue  # the Model Weights page, not this one
            technique = info.get("technique", "Unknown")
            datasets_by_technique[technique].append(
                {
                    "name": name,
                    "description": info.get("description", ""),
                    "tags": info.get("tags", []),
                    "source": info.get("source", ""),
                    "file": info.get("file", ""),
                    "license": info.get("license", ""),
                    "detector": info.get("detector", "Unknown"),
                    "detector_manufacturer": info.get("detector_manufacturer", "Unknown"),
                }
            )

    return dict(datasets_by_technique)


def generate_html_table(datasets_by_technique):
    """Generate HTML with filterable table and technique tabs."""
    all_tags = set()
    all_detectors = {}  # Changed to dict: {manufacturer: [detectors]}
    technique_tags = {}
    technique_detectors = {}

    for technique, datasets in datasets_by_technique.items():
        tags = set()
        detectors = {}
        for dataset in datasets:
            tags.update(dataset["tags"])
            all_tags.update(dataset["tags"])
            manufacturer = dataset.get("detector_manufacturer", "Unknown")
            detector = dataset.get("detector", "Unknown")

            if manufacturer not in detectors:
                detectors[manufacturer] = set()
            detectors[manufacturer].add(detector)

            if manufacturer not in all_detectors:
                all_detectors[manufacturer] = set()
            all_detectors[manufacturer].add(detector)

        technique_tags[technique] = sorted(tags)
        technique_detectors[technique] = {m: sorted(d) for m, d in detectors.items()}

    all_detectors = {m: sorted(d) for m, d in all_detectors.items()}

    technique_tags_json = __import__("json").dumps(technique_tags)
    technique_detectors_json = __import__("json").dumps(technique_detectors)
    all_tags_sorted = sorted(all_tags)
    all_detectors_json = __import__("json").dumps(all_detectors)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            :root {
                color-scheme: light dark;
            }
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; 
                margin: 0; 
                padding: 20px; 
                background: transparent; 
                color: inherit; 
            }
            table { 
                border-collapse: collapse; 
                width: 100%; 
                border: 1px solid light-dark(#ddd, #444); 
            }
            th, td { 
                border: 1px solid light-dark(#ddd, #444); 
                padding: 12px 8px; 
                text-align: left; 
            }
            th { 
                background-color: light-dark(#f5f5f5, #2d2d2d); 
                font-weight: 600; 
                position: relative; 
            }
            tr:nth-child(even) { 
                background-color: light-dark(#f9f9f9, #252525); 
            }
            tr:hover { 
                background-color: light-dark(#f0f0f0, #333); 
            }
            a { 
                color: light-dark(#2980b9, #3091d1); 
                text-decoration: none; 
            }
            a:hover { text-decoration: underline; }
            .tabs { 
                margin: 15px 0; 
                border-bottom: 1px solid light-dark(#ddd, #444); 
            }
            .tab-button { 
                padding: 10px 16px; 
                margin-right: 4px; 
                cursor: pointer; 
                border: none; 
                background: transparent; 
                color: inherit; 
                font-size: 14px; 
                border-bottom: 3px solid transparent; 
            }
            .tab-button:hover { 
                background: light-dark(#f5f5f5, #2d2d2d); 
            }
            .tab-button.active { 
                border-bottom-color: light-dark(#2980b9, #3091d1); 
                font-weight: 600; 
            }
            .filter-dropdown { position: relative; display: inline-block; }
            .filter-button { 
                cursor: pointer; 
                padding: 4px 8px; 
                background: light-dark(#f5f5f5, #2d2d2d); 
                border: 1px solid light-dark(#ddd, #444); 
                color: inherit; 
                border-radius: 3px; 
                margin-left: 8px; 
                font-size: 12px; 
            }
            .filter-button:hover { 
                background: light-dark(#e8e8e8, #333); 
            }
            .filter-content { 
                display: none; 
                position: absolute; 
                background: light-dark(white, #1e1e1e); 
                border: 1px solid light-dark(#ddd, #444); 
                padding: 10px; 
                z-index: 1000; 
                min-width: 250px; 
                max-height: 300px; 
                overflow-y: auto; 
                box-shadow: 0 4px 6px light-dark(rgba(0,0,0,0.1), rgba(0,0,0,0.5)); 
                border-radius: 4px; 
            }
            .filter-dropdown.active .filter-content { display: block; }
            .filter-checkbox { display: block; margin: 5px 0; cursor: pointer; }
            .manufacturer-group { margin: 10px 0; padding-left: 10px; }
            .manufacturer-label { font-weight: 600; margin: 8px 0 4px 0; }
            .detector-checkbox { display: block; margin: 3px 0; padding-left: 20px; }
            th:nth-child(5), td:nth-child(5) { min-width: 200px; }
            h1 { 
                border-bottom: 1px solid light-dark(#ddd, #444); 
                padding-bottom: 10px; 
            }
        </style>
    </head>
    <body>
        <h1>EM Datasets</h1>

        <div class="tabs" id="techTabs">
            <!-- Tabs will be injected here -->
        </div>

        <table id="datasetsTable">
            <thead>
                <tr>
                    <th>Technique</th>
                    <th>Dataset</th>
                    <th>Description</th>
                    <th>
                        Tags
                        <div class="filter-dropdown" id="tagsFilter">
                            <span class="filter-button">▼</span>
                            <div class="filter-content" id="tagsContent"></div>
                        </div>
                    </th>
                    <th>
                        Detector
                        <div class="filter-dropdown" id="detectorFilter">
                            <span class="filter-button">▼</span>
                            <div class="filter-content" id="detectorContent"></div>
                        </div>
                    </th>
                    <th>File</th>
                    <th>License</th>
                </tr>
            </thead>
            <tbody>
    """

    for technique in sorted(datasets_by_technique.keys()):
        for dataset in datasets_by_technique[technique]:
            tags_str = ", ".join(dataset["tags"])
            manufacturer = dataset.get("detector_manufacturer", "Unknown")
            detector = dataset.get("detector", "Unknown")
            detector_full = f"{manufacturer} - {detector}"
            html += f"""            <tr data-tags="{tags_str}" data-technique="{technique}" data-detector="{detector}" data-manufacturer="{manufacturer}">
                <td>{technique}</td>
                <td><strong>{dataset["name"]}</strong></td>
                <td>{dataset["description"]}</td>
                <td>{tags_str}</td>
                <td>{detector_full}</td>
                <td><a href="{dataset["source"]}">{dataset["file"]}</a></td>
                <td>{dataset["license"]}</td>
            </tr>
    """

    html += f"""        </tbody>
        </table>
        <script>
            const techniqueTags = {technique_tags_json};
            const techniqueDetectors = {technique_detectors_json};
            const allTags = {__import__("json").dumps(all_tags_sorted)};
            const allDetectors = {all_detectors_json};
            let currentTechnique = 'All';

            function createTabs() {{
                const tabs = document.getElementById('techTabs');
                const allButton = document.createElement('button');
                allButton.textContent = 'All';
                allButton.className = 'tab-button active';
                allButton.onclick = () => filterTechnique('All');
                tabs.appendChild(allButton);

                Object.keys(techniqueTags).sort().forEach(tech => {{
                    const btn = document.createElement('button');
                    btn.textContent = tech;
                    btn.className = 'tab-button';
                    btn.onclick = () => filterTechnique(tech);
                    tabs.appendChild(btn);
                }});
            }}

            function renderFilterCheckboxes(containerId, items) {{
                const container = document.getElementById(containerId);
                container.innerHTML = '';
                items.forEach(item => {{
                    const label = document.createElement('label');
                    label.className = 'filter-checkbox';
                    const input = document.createElement('input');
                    input.type = 'checkbox';
                    input.value = item;
                    input.onchange = filterTable;
                    label.appendChild(input);
                    label.appendChild(document.createTextNode(' ' + item));
                    container.appendChild(label);
                }});
            }}

            function renderDetectorCheckboxes(detectors) {{
                const container = document.getElementById('detectorContent');
                container.innerHTML = '';

                Object.keys(detectors).sort().forEach(manufacturer => {{
                    const group = document.createElement('div');
                    group.className = 'manufacturer-group';

                    const mfrLabel = document.createElement('label');
                    mfrLabel.className = 'manufacturer-label filter-checkbox';
                    const mfrInput = document.createElement('input');
                    mfrInput.type = 'checkbox';
                    mfrInput.value = manufacturer;
                    mfrInput.dataset.type = 'manufacturer';
                    mfrInput.onchange = (e) => {{
                        const detectorInputs = group.querySelectorAll('input[data-manufacturer="' + manufacturer + '"]');
                        detectorInputs.forEach(input => input.checked = e.target.checked);
                        filterTable();
                    }};
                    mfrLabel.appendChild(mfrInput);
                    mfrLabel.appendChild(document.createTextNode(' ' + manufacturer));
                    group.appendChild(mfrLabel);

                    detectors[manufacturer].forEach(detector => {{
                        const label = document.createElement('label');
                        label.className = 'detector-checkbox';
                        const input = document.createElement('input');
                        input.type = 'checkbox';
                        input.value = detector;
                        input.dataset.manufacturer = manufacturer;
                        input.onchange = filterTable;
                        label.appendChild(input);
                        label.appendChild(document.createTextNode(' ' + detector));
                        group.appendChild(label);
                    }});

                    container.appendChild(group);
                }});
            }}

            function updateFilters(technique) {{
                const tags = technique === 'All' ? allTags : (techniqueTags[technique] || []);
                const detectors = technique === 'All' ? allDetectors : (techniqueDetectors[technique] || {{}});
                renderFilterCheckboxes('tagsContent', tags);
                renderDetectorCheckboxes(detectors);
            }}

            function setActiveTab(name) {{
                const buttons = document.querySelectorAll('.tab-button');
                buttons.forEach(b => {{
                    b.classList.toggle('active', b.textContent === name);
                }});
            }}

            function filterTechnique(technique) {{
                currentTechnique = technique;
                setActiveTab(technique);
                updateFilters(technique);
                filterTable();
            }}

            function filterTable() {{
                const selectedTags = Array.from(document.querySelectorAll('#tagsContent input:checked')).map(cb => cb.value);
                const selectedDetectors = Array.from(document.querySelectorAll('#detectorContent input:checked:not([data-type="manufacturer"])')).map(cb => cb.value);
                const rows = document.querySelectorAll('#datasetsTable tbody tr');

                rows.forEach(row => {{
                    const rowTechnique = row.dataset.technique;
                    if (currentTechnique !== 'All' && rowTechnique !== currentTechnique) {{
                        row.style.display = 'none';
                        return;
                    }}

                    const rowTags = row.dataset.tags ? row.dataset.tags.split(', ').filter(t => t) : [];
                    const rowDetector = row.dataset.detector;

                    const tagsMatch = selectedTags.length === 0 || selectedTags.every(tag => rowTags.includes(tag));
                    const detectorMatch = selectedDetectors.length === 0 || selectedDetectors.includes(rowDetector);

                    row.style.display = (tagsMatch && detectorMatch) ? '' : 'none';
                }});
            }}

            // Toggle dropdown visibility
            document.querySelectorAll('.filter-dropdown .filter-button').forEach(btn => {{
                btn.onclick = (e) => {{
                    e.stopPropagation();
                    const dropdown = btn.parentElement;
                    document.querySelectorAll('.filter-dropdown').forEach(d => {{
                        if (d !== dropdown) d.classList.remove('active');
                    }});
                    dropdown.classList.toggle('active');
                }};
            }});

            // Close dropdowns when clicking outside
            document.addEventListener('click', () => {{
                document.querySelectorAll('.filter-dropdown').forEach(d => d.classList.remove('active'));
            }});

            // Prevent dropdown from closing when clicking inside
            document.querySelectorAll('.filter-content').forEach(content => {{
                content.onclick = (e) => e.stopPropagation();
            }});

            // Initialize UI
            createTabs();
            updateFilters('All');
        </script>
    </body>
    </html>
    """
    return html


# ---------------------------------------------------------------------------
# Widget-styled browser for the docs landing page
# ---------------------------------------------------------------------------
#
# Reuses the Jupyter widget's CSS (emdatabase/static/browser.css) and the
# emdatabase.catalogue data model so the docs page looks and browses exactly
# like emdatabase.browse(). A static site has no kernel, so instead of live
# downloads the details panel offers the copy-to-load snippet and a direct link
# to the source file.

_DOCS_BROWSER_JS = r"""
(function () {
  var root = document.getElementById("root");
  root.classList.add("emdb");
  var TAB_LABEL = { "In-situ TEM": "In-situ", "Cryo-EM": "Cryo" };
  // What this page is browsing; baked in next to DATA so one script serves the
  // dataset pages and the weights page.
  var WHAT = (typeof LABEL !== "undefined" && LABEL) ? LABEL : "Datasets";
  var state = { tab: "All", search: "", selected: null, hovered: null };

  function esc(v) {
    return String(v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function toSnake(name) {
    return name.replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2").toLowerCase();
  }
  function copyText(text, btn) {
    var done = function () {
      var old = btn.textContent; btn.textContent = "Copied!"; btn.classList.add("copied");
      setTimeout(function () { btn.textContent = old; btn.classList.remove("copied"); }, 1100);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text, done); });
    } else { fallbackCopy(text, done); }
  }
  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    ta.remove();
  }

  var header = el("div", "emdb-header");
  var tabsEl = el("div", "emdb-tabs");
  var body = el("div", "emdb-body");
  var listEl = el("div", "emdb-list");
  var detailsEl = el("div", "emdb-details");
  body.appendChild(listEl); body.appendChild(detailsEl);
  root.appendChild(header); root.appendChild(tabsEl); root.appendChild(body);

  function allItems() {
    return (DATA.groups || []).reduce(function (a, g) { return a.concat(g.items); }, []);
  }
  function techniques() { return (DATA.groups || []).map(function (g) { return g.technique; }); }
  function matchesSearch(it) {
    if (!state.search) return true;
    var blob = it.search || it.name.toLowerCase();
    return state.search.toLowerCase().split(/\s+/).every(function (t) { return blob.indexOf(t) !== -1; });
  }
  function findItem(n) { return allItems().filter(function (i) { return i.name === n; })[0] || null; }

  function drawHeader() {
    header.innerHTML = "";
    var top = el("div", "emdb-header-top");
    top.appendChild(el("div", "emdb-brand",
      '<span class="emdb-diamond">◆</span> ' + esc(WHAT)));
    top.appendChild(el("div", "emdb-count", DATA.n_total + " " + WHAT.toLowerCase()));
    header.appendChild(top);
    var search = el("input", "emdb-search");
    search.type = "text"; search.value = state.search;
    search.placeholder = "Search " + WHAT.toLowerCase() + "…";
    search.addEventListener("input", function () { state.search = search.value; drawList(); });
    header.appendChild(search);
  }
  function drawTabs() {
    tabsEl.innerHTML = "";
    var tabList = (typeof TABS !== "undefined" && TABS) ? TABS : techniques();
    ["All"].concat(tabList).forEach(function (tab) {
      var label = tab === "All" ? "All" : (TAB_LABEL[tab] || tab);
      var b = el("button", "emdb-tab" + (state.tab === tab ? " active" : ""), esc(label));
      b.addEventListener("click", function () { state.tab = tab; drawTabs(); drawList(); });
      tabsEl.appendChild(b);
    });
  }
  function drawList() {
    listEl.innerHTML = "";
    var shown = 0;
    (DATA.groups || []).forEach(function (g) {
      if (state.tab !== "All" && g.technique !== state.tab) return;
      var items = g.items.filter(matchesSearch);
      if (!items.length) return;
      if (state.tab === "All") listEl.appendChild(el("div", "emdb-group-head", esc(g.technique)));
      items.forEach(function (it) { listEl.appendChild(drawRow(it)); shown++; });
    });
    if (!shown) listEl.appendChild(
      el("div", "emdb-empty", "No " + WHAT.toLowerCase() + " match."));
    if (!state.selected && allItems().length) state.selected = allItems()[0].name;
    drawDetails();
  }
  function drawRow(it) {
    var row = el("div", "emdb-row" + (state.selected === it.name ? " selected" : ""));
    row.appendChild(el("span", "emdb-glyph off", "•"));
    row.appendChild(el("span", "emdb-name", esc(it.name)));
    var meta = [it.size, it.shape].filter(Boolean).join("  ·  ");
    row.appendChild(el("span", "emdb-meta", esc(meta)));
    row.addEventListener("mouseenter", function () { state.hovered = it.name; drawDetails(); });
    row.addEventListener("click", function () { state.selected = it.name; drawList(); });
    return row;
  }
  function copyRow(shown, val) {
    var row = el("div", "emdb-copy");
    row.appendChild(el("code", "emdb-code", esc(shown)));
    var btn = el("button", "emdb-copy-btn", "Copy");
    btn.addEventListener("click", function () { copyText(val, btn); });
    row.appendChild(btn);
    return row;
  }
  function drawDetails() {
    var it = findItem(state.hovered || state.selected);
    detailsEl.innerHTML = "";
    if (!it) { detailsEl.appendChild(el("div", "emdb-details-empty", "Hover or select an entry.")); return; }
    var title = el("div", "emdb-d-title", esc(it.name));
    if (it.kind === "weights") title.appendChild(el("span", "emdb-kind", "weights"));
    detailsEl.appendChild(title);
    detailsEl.appendChild(el("div", "emdb-d-sub",
      esc([it.technique, it.size, it.shape].filter(Boolean).join("  ·  "))));
    if (it.description) detailsEl.appendChild(el("p", "emdb-d-desc", esc(it.description)));
    var pairs = [["Detector", it.detector], ["Microscope", it.microscope], ["Voltage", it.voltage],
      ["Tags", (it.tags || []).join(", ")], ["Authors", (it.authors || []).join(", ")],
      ["License", it.license], ["DOI", it.doi], ["Version", it.version],
      ["Model", it.model_class], ["Framework", it.model_framework],
      ["quantem", it.model_quantem]];
    var meta = el("div", "emdb-d-meta");
    pairs.forEach(function (kv) {
      if (!kv[1]) return;
      var row = el("div", "emdb-kv");
      row.appendChild(el("span", "emdb-k", kv[0]));
      row.appendChild(el("span", "emdb-v", esc(kv[1])));
      meta.appendChild(row);
    });
    detailsEl.appendChild(meta);
    detailsEl.appendChild(el("div", "emdb-load-label", "Load"));
    var snippet = it.kind === "weights"
      ? "import torch\nfrom emdatabase import data\n\npath = data." + it.name
        + "().download()\ncheckpoint = torch.load(path, weights_only=True)"
      : toSnake(it.name) + " = emdatabase.data." + it.name + "()";
    detailsEl.appendChild(copyRow(snippet, snippet));
    if (it.url) {
      var wrap = el("div", "emdb-dl-link");
      var a = document.createElement("a");
      a.href = it.url; a.target = "_blank"; a.rel = "noopener";
      a.className = "emdb-dl-anchor"; a.textContent = "⤓ Download " + it.file;
      wrap.appendChild(a);
      detailsEl.appendChild(wrap);
    }
  }

  drawHeader(); drawTabs(); drawList();
})();
"""

# ---------------------------------------------------------------------------
# Shared "app" chrome: a Catppuccin-Mocha shell that makes the whole docs site
# look like emdatabase.browse(). Every generated page (landing / all-data /
# add-dataset) is a self-contained file: the widget CSS is inlined, the palette
# and top-nav live in _APP_CSS, and the catalogue JSON is baked in at build
# time so search and the list work with no backend and no external requests.
# ---------------------------------------------------------------------------

# Palette + top-nav + hero, keyed to the same Catppuccin tokens browser.css
# defines on .emdb (mirrored here on :root so the nav/hero/form get them too).
_APP_CSS = """
:root {
  --emdb-base: #1e1e2e; --emdb-mantle: #181825; --emdb-crust: #11111b;
  --emdb-surface0: #313244; --emdb-surface1: #45475a; --emdb-surface2: #585b70;
  --emdb-overlay: #2a2a3c; --emdb-text: #cdd6f4; --emdb-subtext: #a6adc8;
  --emdb-muted: #7f849c; --emdb-blue: #89b4fa; --emdb-mauve: #cba6f7;
  --emdb-green: #a6e3a1; --emdb-red: #f38ba8; --emdb-yellow: #f9e2af;
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
.app-brand .diamond {
  background: linear-gradient(135deg, var(--emdb-blue), var(--emdb-mauve));
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
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

/* Hero --------------------------------------------------------------- */
.app-hero { text-align: center; padding: 30px 0 14px; }
.app-hero h1 {
  margin: 0; font-size: 40px; font-weight: 800; letter-spacing: -0.5px; line-height: 1.1;
  background: linear-gradient(135deg, #89b4fa, #cba6f7);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
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
.emdb-diamond { display: none; }
.emdb-body { height: 600px; }
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
.emdb-load-label, .emdb-d-status { font-size: 12px; }
.emdb-copy-btn, .emdb-dl { font-size: 13px; }
/* Keep the metadata a tidy two-column block instead of sprawling edge to edge */
.emdb-d-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); max-width: 820px; gap: 6px 30px; }
"""

# Form styling for the Add Dataset page.
_FORM_CSS = """
.form-wrap { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 430px); gap: 26px; align-items: start; }
@media (max-width: 900px) { .form-wrap { grid-template-columns: 1fr; } .yaml-side { position: static; } }
.ds-form { display: flex; flex-direction: column; gap: 14px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 560px) { .grid2 { grid-template-columns: 1fr; } }
.field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.field label { font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--emdb-muted); }
.field .req { color: var(--emdb-red); }
.field-hint { font-size: 11px; color: var(--emdb-subtext); }
.field input, .field textarea, .field select {
  width: 100%; box-sizing: border-box;
  background: var(--emdb-crust); color: var(--emdb-text);
  border: 1px solid var(--emdb-surface0); border-radius: 7px; padding: 8px 10px;
  font-size: 13px; font-family: var(--emdb-font); outline: none;
}
.field textarea { min-height: 84px; resize: vertical; line-height: 1.5; }
.field input:focus, .field textarea:focus, .field select:focus { border-color: var(--emdb-blue); }
.field input.invalid, .field textarea.invalid, .field select.invalid { border-color: var(--emdb-red); }
.field-err { font-size: 11px; color: var(--emdb-red); min-height: 13px; }
.section-title {
  font-size: 12px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--emdb-subtext); margin-top: 8px; padding-top: 16px; border-top: 1px solid var(--emdb-surface0);
}
#authors { display: flex; flex-direction: column; gap: 12px; }
.author-row {
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;
  background: var(--emdb-mantle); border: 1px solid var(--emdb-surface0); border-radius: 9px; padding: 12px;
}
@media (max-width: 620px) { .author-row { grid-template-columns: 1fr; } }
.btn-ghost {
  align-self: flex-start; cursor: pointer; font-weight: 600; font-size: 12px;
  background: var(--emdb-surface0); color: var(--emdb-text);
  border: 1px solid var(--emdb-surface1); border-radius: 7px; padding: 6px 12px;
}
.btn-ghost:hover { border-color: var(--emdb-blue); color: var(--emdb-blue); }

.yaml-side { position: sticky; top: 72px; display: flex; flex-direction: column; gap: 12px; }
.yaml-head {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--emdb-muted);
}
.yaml-pre {
  margin: 0; background: var(--emdb-crust); border: 1px solid var(--emdb-surface0);
  border-radius: 10px; padding: 14px; max-height: 440px; overflow: auto;
  font-family: var(--emdb-mono); font-size: 12px; color: var(--emdb-text); white-space: pre;
}
.submit-row { display: flex; flex-direction: column; gap: 10px; }
.btn-primary {
  cursor: pointer; font-weight: 700; font-size: 14px; text-align: center;
  color: var(--emdb-crust); background: linear-gradient(135deg, var(--emdb-blue), var(--emdb-mauve));
  border: 0; border-radius: 9px; padding: 12px 16px;
}
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; filter: grayscale(0.3); }
.btn-primary:not(:disabled):hover { filter: brightness(1.06); }
.btn-secondary {
  text-align: center; font-size: 12px; font-weight: 600; color: var(--emdb-subtext);
  border: 1px solid var(--emdb-surface1); border-radius: 8px; padding: 9px 14px;
}
.btn-secondary:hover { color: var(--emdb-text); border-color: var(--emdb-blue); text-decoration: none; }
.copy-mini {
  cursor: pointer; font-size: 11px; font-weight: 600; color: var(--emdb-blue);
  background: transparent; border: 1px solid var(--emdb-surface1); border-radius: 6px; padding: 2px 9px;
}
.copy-mini:hover { border-color: var(--emdb-blue); background: rgba(137, 180, 250, 0.1); }
.copy-mini.copied { color: var(--emdb-green); border-color: var(--emdb-green); }
.form-note { font-size: 11.5px; color: var(--emdb-subtext); line-height: 1.55; }
.form-note code { font-family: var(--emdb-mono); color: var(--emdb-text); }
"""


def _esc(value) -> str:
    """Minimal HTML escaping for text baked into a page at build time."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# Top-nav destinations. Examples and API are Sphinx-generated (sphinx-gallery +
# autodoc); All Data and Add Dataset are the generated app pages. All the
# generated pages sit at the site root, so these relative links resolve the
# same from each of them.
_NAV_LINKS = (
    ("Examples", "examples/index.html"),
    ("API", "reference/index.html"),
    ("All Data", "all_data.html"),
    ("Model Weights", "weights.html"),
    ("Add Dataset", "add_dataset.html"),
)


def _top_nav(active: str = "") -> str:
    items = "".join(
        '<a class="app-navlink{cls}" href="{url}">{name}</a>'.format(
            cls=" active" if name == active else "", url=url, name=_esc(name)
        )
        for name, url in _NAV_LINKS
    )
    return (
        '<nav class="app-nav">'
        '<a class="app-brand" href="index.html">EM-Database</a>' + items + "</nav>"
    )


def _load_css() -> str:
    return (resources.files("emdatabase") / "static" / "browser.css").read_text(encoding="utf-8")


def _app_page(
    title: str, body: str, active: str = "", extra_css: str = "", scripts: str = ""
) -> str:
    """Wrap page ``body`` in the self-contained Catppuccin app shell.

    Built by concatenation (not ``str.format``/``%``) so CSS/JS braces need no
    escaping. The result references no external hosts - all CSS/JS is inline.
    """
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>" + _esc(title) + "</title>\n"
        "<style>\n" + _load_css() + "\n" + _APP_CSS + "\n" + extra_css + "\n</style>\n"
        "</head>\n<body>\n" + _top_nav(active) + "\n" + body + "\n" + scripts + "\n"
        "</body></html>\n"
    )


def _catalogue_payload(kind: str = "dataset"):
    """``(payload, tabs)`` - the baked catalogue and the ordered tab list.

    Tabs are the canonical techniques (so 4D-STEM / EELS / EDS / EBSD / STEM /
    In-situ / Cryo always show, even if a technique currently has no dataset),
    followed by any other technique that happens to be present. For the weights
    page there is one group, so the tabs are whatever is there.
    """
    from emdatabase import catalogue

    payload = catalogue.catalogue(kind=kind)
    present = [g["technique"] for g in payload.get("groups", [])]
    if kind == "weights":
        return payload, present
    order = list(catalogue.TECHNIQUE_ORDER)
    return payload, order + [t for t in present if t not in order]


def _browser_script(payload, tabs, label: str = "Datasets") -> str:
    """The <script> block that boots the widget-style browser into ``#root``."""
    return (
        "<script>\n"
        "const DATA = " + json.dumps(payload) + ";\n"
        "const TABS = " + json.dumps(tabs) + ";\n"
        "const LABEL = " + json.dumps(label) + ";\n" + _DOCS_BROWSER_JS + "\n</script>"
    )


def generate_browser_html() -> str:
    """Self-contained, widget-styled dataset browser (no nav chrome).

    Kept for backward compatibility (it can be embedded in an ``<iframe>``): a
    bare page with a transparent background and just the ``.emdb`` widget.
    """
    payload, tabs = _catalogue_payload()
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>EM Datasets</title>\n<style>\n" + _load_css() + "\n"
        "html, body { margin: 0; padding: 0; background: transparent; }\n"
        + _BROWSER_OVERRIDES
        + "\n</style></head>\n<body>\n"
        '<div id="root"></div>\n' + _browser_script(payload, tabs) + "\n</body></html>\n"
    )


def generate_landing_html() -> str:
    """The landing page: hero + the widget-style search / tabs / list browser."""
    payload, tabs = _catalogue_payload()
    body = (
        '<main class="app-main">'
        '<div class="app-hero">'
        "<h1>EM-Database</h1>"
        "<p>A curated, citable collection of electron microscopy datasets &mdash; "
        "a couple of lines of Python from your analysis. Search below, then copy the "
        "snippet to load one with <code>emdatabase.data.&lt;Name&gt;()</code>.</p>"
        "</div>"
        '<div id="root"></div>'
        "</main>"
    )
    return _app_page(
        "EM-Database",
        body,
        active="",
        extra_css=_BROWSER_OVERRIDES,
        scripts=_browser_script(payload, tabs),
    )


def generate_all_data_html() -> str:
    """The All Data page: the full widget-style dataset browser with nav."""
    payload, tabs = _catalogue_payload()
    body = (
        '<main class="app-main">'
        '<div class="app-hero" style="padding:18px 0 4px">'
        '<h1 style="font-size:30px">All Data</h1>'
        "<p>Every dataset in the collection. Search across names, techniques, "
        "authors, detectors and tags; filter by technique with the tabs.</p>"
        "</div>"
        '<div id="root"></div>'
        "</main>"
    )
    return _app_page(
        "All Data &middot; EM-Database",
        body,
        active="All Data",
        extra_css=_BROWSER_OVERRIDES + "\n.emdb-body { height: 620px; }\n",
        scripts=_browser_script(payload, tabs),
    )


def generate_weights_html() -> str:
    """The Model Weights page: the same browser, over the weights entries.

    Each entry is one released version of one model. emdatabase downloads the
    checkpoint and nothing else, so the load snippet is where the page says how
    to open it - ``weights_only=True``, which is the condition of a checkpoint
    being accepted in the first place.
    """
    payload, tabs = _catalogue_payload(kind="weights")
    note = "" if payload.get("groups") else "<p>No model weights are published yet.</p>"
    body = (
        '<main class="app-main">'
        '<div class="app-hero" style="padding:18px 0 4px">'
        '<h1 style="font-size:30px">Model Weights</h1>'
        "<p>Trained model checkpoints, one entry per released version. Each is a "
        "single file with a checksum, downloaded the same way a dataset is; the "
        "load snippet opens it with <code>weights_only=True</code>.</p>" + note + "</div>"
        '<div id="root"></div>'
        "</main>"
    )
    return _app_page(
        "Model Weights &middot; EM-Database",
        body,
        active="Model Weights",
        extra_css=_BROWSER_OVERRIDES + "\n.emdb-body { height: 620px; }\n",
        scripts=_browser_script(payload, tabs, label="Model weights"),
    )


# -- Add Dataset page --------------------------------------------------------

_VENDOR_LISTS = load_vendors()
_MANUFACTURERS = tuple(_VENDOR_LISTS["detector_manufacturer"])
_VENDORS = tuple(_VENDOR_LISTS["microscope_vendor"])
_TECHNIQUES = ("4D-STEM", "EELS", "EDS", "EBSD", "STEM", "In-situ TEM", "Cryo-EM", "Other")

# Owner/repo the prefilled "create new file" PR link targets.
_REPO = "electronmicroscopy/emdatabase"
_BRANCH = "main"


def _text_field(fid, label, required=False, placeholder="", hint="", full=False):
    req = ' <span class="req">*</span>' if required else ""
    ph = ' placeholder="' + _esc(placeholder) + '"' if placeholder else ""
    hn = '<div class="field-hint">' + _esc(hint) + "</div>" if hint else ""
    style = ' style="grid-column:1/-1"' if full else ""
    return (
        '<div class="field"'
        + style
        + '><label for="'
        + fid
        + '">'
        + _esc(label)
        + req
        + "</label>"
        + hn
        + '<input id="'
        + fid
        + '" type="text"'
        + ph
        + ">"
        '<div class="field-err" id="err-' + fid + '"></div></div>'
    )


def _select_field(fid, label, options, hint=""):
    hn = '<div class="field-hint">' + _esc(hint) + "</div>" if hint else ""
    opts = '<option value="">&mdash; select &mdash;</option>'
    opts += "".join('<option value="' + _esc(o) + '">' + _esc(o) + "</option>" for o in options)
    return (
        '<div class="field"><label for="'
        + fid
        + '">'
        + _esc(label)
        + "</label>"
        + hn
        + '<select id="'
        + fid
        + '">'
        + opts
        + "</select>"
        '<div class="field-err" id="err-' + fid + '"></div></div>'
    )


def _datalist_field(fid, label, options, placeholder="", hint=""):
    """A free-text field with suggestions - the open-string vendor lists."""
    hn = '<div class="field-hint">' + _esc(hint) + "</div>" if hint else ""
    ph = ' placeholder="' + _esc(placeholder) + '"' if placeholder else ""
    opts = "".join('<option value="' + _esc(o) + '">' for o in options)
    return (
        '<div class="field"><label for="'
        + fid
        + '">'
        + _esc(label)
        + "</label>"
        + hn
        + '<input id="'
        + fid
        + '" type="text" list="'
        + fid
        + '-list"'
        + ph
        + ">"
        '<datalist id="' + fid + '-list">' + opts + "</datalist>"
        '<div class="field-err" id="err-' + fid + '"></div></div>'
    )


def _author_row_html():
    return (
        '<div class="author-row">'
        '<div class="field"><label>Name</label>'
        '<input class="a-name" type="text" placeholder="Jane Doe">'
        '<div class="field-err a-name-err"></div></div>'
        '<div class="field"><label>Affiliation <span class="req">*</span></label>'
        '<input class="a-aff" type="text" placeholder="University of ...">'
        '<div class="field-err a-aff-err"></div></div>'
        '<div class="field"><label>ORCID</label>'
        '<input class="a-orcid" type="text" placeholder="0000-0000-0000-0000">'
        '<div class="field-err a-orcid-err"></div></div>'
        "</div>"
    )


def generate_add_dataset_html() -> str:
    """The Add Dataset page: a schema-driven form that opens a prefilled PR."""
    fields = (
        _text_field(
            "f-name",
            "Dataset Name",
            required=True,
            placeholder="MgONanoCrystals",
            hint="Short CamelCase identifier - becomes the YAML key and file name.",
            full=True,
        )
        + '<div class="field" style="grid-column:1/-1"><label for="f-description">Description '
        '<span class="req">*</span></label>'
        '<div class="field-hint">Technique, sample, size, and anything notable.</div>'
        '<textarea id="f-description" placeholder="A 4D-STEM dataset of ..."></textarea>'
        '<div class="field-err" id="err-f-description"></div></div>'
        + _text_field(
            "f-source",
            "Source URL",
            required=True,
            placeholder="https://zenodo.org/records/15490547/files",
            hint="Direct download base (no file name).",
        )
        + _text_field(
            "f-file",
            "File",
            required=True,
            placeholder="smallPtychography.hspy",
            hint="The file name at that source.",
        )
        + _text_field(
            "f-checksum",
            "Checksum",
            placeholder="md5:df9376d5c020a23f0f7f51cfe79f303f",
            hint="md5:<32 hex chars>",
        )
        + _text_field(
            "f-size_bytes",
            "Size (bytes)",
            placeholder="1104287335",
            hint="The file's Content-Length, in bytes.",
        )
        + _datalist_field(
            "f-detector_manufacturer",
            "Detector Manufacturer",
            _MANUFACTURERS,
            placeholder="Direct Electron",
        )
        + _text_field("f-detector", "Detector", placeholder="CeleritasXS")
        + _datalist_field(
            "f-microscope_vendor",
            "Microscope Vendor",
            _VENDORS,
            placeholder="Thermo Fisher Scientific",
        )
        + _text_field("f-microscope_model", "Microscope Model", placeholder="Gen 1 Titan")
        + _text_field("f-camera_length", "Camera Length", placeholder="e.g. 100 mm")
        + _text_field("f-voltage", "Voltage", placeholder="200 kV", hint="e.g. 200 kV")
        + _select_field("f-technique", "Technique", _TECHNIQUES)
        + _text_field("f-license", "License", placeholder="CC-BY-4.0")
        + _text_field("f-doi", "DOI", placeholder="10.5281/zenodo.15490547")
        + _text_field(
            "f-tags",
            "Tags",
            placeholder="Orientation Mapping, Nanocrystals",
            hint="Comma-separated.",
            full=True,
        )
    )

    issue_url = "https://github.com/" + _REPO + "/issues/new?template=new_dataset.yaml"

    body = (
        '<main class="app-main">'
        '<div class="app-hero" style="padding:24px 0 6px">'
        '<h1 style="font-size:32px">Add a Dataset</h1>'
        "<p>Fill in the metadata; the YAML builds live on the right. "
        "&ldquo;Open a Pull Request&rdquo; sends you to GitHub with the new file "
        "pre-filled &mdash; commit it to a branch there and GitHub opens the PR.</p>"
        "<p>From a terminal, <code>python -m emdatabase.new_dataset &lt;url&gt;</code> "
        "fills in the checksum and size for you; see "
        '<a href="contributing.html">Contributing a Dataset</a>.</p>'
        "</div>"
        '<div class="form-wrap">'
        '<form id="ds-form" class="ds-form" autocomplete="off">'
        '<div class="grid2">' + fields + "</div>"
        '<div class="section-title">Authors</div>'
        '<div id="authors">' + _author_row_html() + "</div>"
        '<button type="button" id="add-author" class="btn-ghost">+ Add author</button>'
        "</form>"
        '<aside class="yaml-side">'
        '<div class="yaml-head"><span>Generated YAML</span>'
        '<button type="button" id="copy-yaml" class="copy-mini">Copy</button></div>'
        '<pre id="yaml-preview" class="yaml-pre"><code></code></pre>'
        '<div class="submit-row">'
        '<button type="button" id="submit-pr" class="btn-primary" disabled>'
        "Open a Pull Request on GitHub &#8599;</button>"
        '<a id="submit-issue" class="btn-secondary" target="_blank" rel="noopener" href="'
        + issue_url
        + '">Submit as an issue instead</a>'
        "</div>"
        '<p class="form-note">Requires a GitHub account. The button opens GitHub&rsquo;s '
        "&ldquo;create new file&rdquo; page pre-filled at "
        "<code>emdatabase/index/&lt;Name&gt;.yaml</code>; if you cannot push to the "
        "repo, GitHub forks it for you and lets you propose the change. Fields marked "
        '<span class="req">*</span> are required.</p>'
        "</aside>"
        "</div>"
        "</main>"
    )

    js = _ADD_DATASET_JS.replace("__REPO__", _REPO).replace("__BRANCH__", _BRANCH)
    scripts = "<script>\n" + js + "\n</script>"
    return _app_page(
        "Add Dataset &middot; EM-Database",
        body,
        active="Add Dataset",
        extra_css=_FORM_CSS,
        scripts=scripts,
    )


_ADD_DATASET_JS = r"""
(function () {
  var REPO = "__REPO__", BRANCH = "__BRANCH__";
  var form = document.getElementById("ds-form");
  var preview = document.querySelector("#yaml-preview code");
  var submitPr = document.getElementById("submit-pr");
  var copyBtn = document.getElementById("copy-yaml");
  var addAuthor = document.getElementById("add-author");
  var authorsBox = document.getElementById("authors");

  function val(id) { var e = document.getElementById(id); return e ? e.value.trim() : ""; }
  function sanitizeName(s) { return String(s).replace(/[^A-Za-z0-9]+/g, ""); }

  // Emit a YAML scalar: plain when safe, double-quoted (with escapes) otherwise.
  function yamlStr(v) {
    v = String(v);
    if (v === "") return '""';
    if (/\n/.test(v)) {
      return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
        .replace(/\n/g, "\\n").replace(/\t/g, "\\t") + '"';
    }
    var risky = /^\s|\s$/.test(v)
      || /^[-?:,\[\]{}#&*!|>'"%@`]/.test(v)
      || /:(\s|$)/.test(v)
      || /\s#/.test(v)
      || /^(true|false|null|yes|no|on|off|~)$/i.test(v)
      || /^[-+]?(\d[\d_]*\.?\d*([eE][-+]?\d+)?)$/.test(v);
    if (risky) return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
    return v;
  }

  function authors() {
    var out = [];
    form.querySelectorAll(".author-row").forEach(function (r) {
      var name = r.querySelector(".a-name").value.trim();
      var aff = r.querySelector(".a-aff").value.trim();
      var orcid = r.querySelector(".a-orcid").value.trim();
      if (name) out.push({ name: name, aff: aff, orcid: orcid });
    });
    return out;
  }

  function tags() {
    return val("f-tags").split(",").map(function (t) { return t.trim(); }).filter(Boolean);
  }

  function buildYaml() {
    var name = sanitizeName(val("f-name")) || "DatasetName";
    var lines = ["# $schema: ./json-schema.json", name + ":"];
    function add(k, v) { if (v !== "" && v != null) lines.push("  " + k + ": " + yamlStr(v)); }
    add("description", val("f-description"));
    add("source", val("f-source"));
    add("checksum", val("f-checksum"));
    add("file", val("f-file"));
    var bytes = val("f-size_bytes").replace(/[^0-9]/g, "");
    if (bytes) { lines.push("  size_bytes: " + bytes); }
    add("detector_manufacturer", val("f-detector_manufacturer"));
    add("detector", val("f-detector"));
    add("microscope_vendor", val("f-microscope_vendor"));
    add("microscope_model", val("f-microscope_model"));
    add("camera_length", val("f-camera_length"));
    add("voltage", val("f-voltage"));
    add("license", val("f-license"));
    add("technique", val("f-technique"));
    add("doi", val("f-doi"));
    var tg = tags();
    if (tg.length) {
      lines.push("  tags:");
      tg.forEach(function (t) { lines.push("    - " + yamlStr(t)); });
    }
    var au = authors();
    if (au.length) {
      lines.push("  authors:");
      au.forEach(function (a) {
        lines.push("    " + yamlStr(a.name) + ":");
        lines.push("      affiliation: " + yamlStr(a.aff));
        if (a.orcid) lines.push("      orcid: " + yamlStr(a.orcid));
      });
    }
    return lines.join("\n") + "\n";
  }

  function setError(id, msg) {
    var e = document.getElementById("err-" + id);
    if (e) e.textContent = msg || "";
    var field = document.getElementById(id);
    if (field) field.classList.toggle("invalid", !!msg);
  }

  function validate() {
    var ok = true;
    if (!sanitizeName(val("f-name"))) { setError("f-name", "Required"); ok = false; }
    else setError("f-name", "");
    if (!val("f-description")) { setError("f-description", "Required"); ok = false; }
    else setError("f-description", "");
    var src = val("f-source");
    if (!src) { setError("f-source", "Required"); ok = false; }
    else if (!/^https?:\/\/\S+$/i.test(src)) { setError("f-source", "Must be an http(s) URL"); ok = false; }
    else setError("f-source", "");
    if (!val("f-file")) { setError("f-file", "Required"); ok = false; }
    else setError("f-file", "");
    var cs = val("f-checksum");
    if (cs && !/^md5:[0-9a-fA-F]{32}$/.test(cs)) { setError("f-checksum", "Must match md5:<32 hex>"); ok = false; }
    else setError("f-checksum", "");
    var volt = val("f-voltage");
    if (volt && !/^[0-9]+\s?kV$/.test(volt)) { setError("f-voltage", "e.g. 200 kV"); ok = false; }
    else setError("f-voltage", "");
    form.querySelectorAll(".author-row").forEach(function (r) {
      var n = r.querySelector(".a-name"), a = r.querySelector(".a-aff"), o = r.querySelector(".a-orcid");
      var ae = r.querySelector(".a-aff-err"), oe = r.querySelector(".a-orcid-err");
      if (n.value.trim() && !a.value.trim()) { if (ae) ae.textContent = "Affiliation required"; a.classList.add("invalid"); ok = false; }
      else { if (ae) ae.textContent = ""; a.classList.remove("invalid"); }
      if (o.value.trim() && !/^\d{4}-\d{4}-\d{4}-\d{4}$/.test(o.value.trim())) { if (oe) oe.textContent = "0000-0000-0000-0000"; o.classList.add("invalid"); ok = false; }
      else { if (oe) oe.textContent = ""; o.classList.remove("invalid"); }
    });
    return ok;
  }

  function refresh() {
    preview.textContent = buildYaml();
    submitPr.disabled = !validate();
  }

  function copyText(text, btn) {
    var done = function () {
      var old = btn.textContent; btn.textContent = "Copied!"; btn.classList.add("copied");
      setTimeout(function () { btn.textContent = old; btn.classList.remove("copied"); }, 1100);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text, done); });
    } else { fallbackCopy(text, done); }
  }
  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) {}
    ta.remove();
  }

  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);

  addAuthor.addEventListener("click", function () {
    var tmp = document.createElement("div");
    tmp.innerHTML = authorsBox.querySelector(".author-row").outerHTML;
    var row = tmp.firstChild;
    row.querySelectorAll("input").forEach(function (i) { i.value = ""; i.classList.remove("invalid"); });
    row.querySelectorAll(".field-err").forEach(function (e) { e.textContent = ""; });
    authorsBox.appendChild(row);
    refresh();
  });

  copyBtn.addEventListener("click", function () { copyText(buildYaml(), copyBtn); });

  submitPr.addEventListener("click", function () {
    if (!validate()) { refresh(); return; }
    var name = sanitizeName(val("f-name")) || "Dataset";
    var url = "https://github.com/" + REPO + "/new/" + BRANCH
      + "?filename=" + encodeURIComponent("emdatabase/index/" + name + ".yaml")
      + "&value=" + encodeURIComponent(buildYaml());
    window.open(url, "_blank", "noopener");
  });

  refresh();
})();
"""


if __name__ == "__main__":
    # Manual smoke test: write every generated page to ./_docs_preview so they
    # can be opened in a browser without a full Sphinx build.
    out = Path("_docs_preview")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(generate_landing_html(), encoding="utf-8")
    (out / "all_data.html").write_text(generate_all_data_html(), encoding="utf-8")
    (out / "add_dataset.html").write_text(generate_add_dataset_html(), encoding="utf-8")
    (out / "datasets_browser.html").write_text(generate_browser_html(), encoding="utf-8")
    print("Wrote preview pages to", out.resolve())
