import json
from collections import defaultdict
from importlib import resources
from pathlib import Path

import yaml

from emdatabase.metadata import NON_DATASET_FILES, acquisition_techniques


def parse_datasets(yaml_dir):
    """Parse all YAML files and organize by technique.

    An entry may declare several techniques, in which case it is listed under
    each of them; ``techniques`` on the record is all of them, so the table can
    still draw it as one row.
    """
    datasets_by_technique = defaultdict(list)

    for yaml_file in sorted(Path(yaml_dir).glob("*.yaml")):
        if yaml_file.name in NON_DATASET_FILES:
            continue
        with open(yaml_file, "r") as f:
            data = yaml.safe_load(f)

        for name, info in data.items():
            if info.get("kind") == "weights":
                continue  # the Model Weights page, not this one
            techniques = info.get("technique") or ["Unknown"]
            if isinstance(techniques, str):
                techniques = [techniques]
            record = {
                "name": name,
                "techniques": list(techniques),
                "description": info.get("description", ""),
                "tags": info.get("tags", []),
                "source": info.get("source", ""),
                "file": info.get("file", ""),
                "license": info.get("license", ""),
                "detector": info.get("detector", "Unknown"),
                "detector_manufacturer": info.get("detector_manufacturer", "Unknown"),
            }
            for technique in techniques:
                datasets_by_technique[technique].append(record)

    return dict(datasets_by_technique)


def generate_html_table(datasets_by_technique):
    """Generate HTML with filterable table and technique tabs."""
    from emdatabase import catalogue

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

    technique_tabs_json = json.dumps(catalogue.ordered_groups(datasets_by_technique))
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

    # A dataset declaring several techniques is under each of their keys, so it
    # gets one row carrying all of them and the tabs filter on membership.
    written = set()
    for technique in sorted(datasets_by_technique.keys()):
        for dataset in datasets_by_technique[technique]:
            if dataset["name"] in written:
                continue
            written.add(dataset["name"])
            tags_str = ", ".join(dataset["tags"])
            techniques_str = ", ".join(dataset["techniques"])
            manufacturer = dataset.get("detector_manufacturer", "Unknown")
            detector = dataset.get("detector", "Unknown")
            detector_full = f"{manufacturer} - {detector}"
            html += f"""            <tr data-tags="{tags_str}" data-technique="{techniques_str}" data-detector="{detector}" data-manufacturer="{manufacturer}">
                <td>{techniques_str}</td>
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
            const techniqueTabs = {technique_tabs_json};
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

                techniqueTabs.forEach(tech => {{
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
                    const rowTechniques = row.dataset.technique ? row.dataset.technique.split(', ') : [];
                    if (currentTechnique !== 'All' && !rowTechniques.includes(currentTechnique)) {{
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
  // What this page is browsing; baked in next to DATA so one script serves the
  // dataset pages and the weights page.
  var WHAT = (typeof LABEL !== "undefined" && LABEL) ? LABEL : "Datasets";
  // `version` maps a weights family to the version being shown ("" = latest).
  var state = { tab: "All", search: "", selected: null, hovered: null, version: {} };

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
      var b = el("button", "emdb-tab" + (state.tab === tab ? " active" : ""), esc(tab));
      b.addEventListener("click", function () { state.tab = tab; drawTabs(); drawList(); });
      tabsEl.appendChild(b);
    });
  }
  function drawList() {
    listEl.innerHTML = "";
    var shown = 0;
    // A dataset with several techniques is in several groups, so the All view
    // lists it under the first one and skips it after that.
    var drawn = {};
    (DATA.groups || []).forEach(function (g) {
      if (state.tab !== "All" && g.technique !== state.tab) return;
      var items = g.items.filter(matchesSearch).filter(function (it) { return !drawn[it.name]; });
      if (!items.length) return;
      if (state.tab === "All") listEl.appendChild(el("div", "emdb-group-head", esc(g.technique)));
      items.forEach(function (it) {
        if (state.tab === "All") drawn[it.name] = true;
        listEl.appendChild(drawRow(it)); shown++;
      });
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
  // Which version of an entry is being shown: "" is latest, and is all a
  // dataset (or a family whose selection has gone away) ever has.
  function currentVersion(it) {
    var chosen = state.version[it.name];
    if (!chosen) return "";
    return (it.versions || []).some(function (v) { return v.version === chosen; }) ? chosen : "";
  }
  // The link, pin and local file name of one version; an entry's own fields
  // describe latest, so the same reads serve either.
  function versionState(it, want) {
    if (!want) return { url: it.url, checksum: it.latest_checksum, file: it.file };
    var row = (it.versions || []).filter(function (v) { return v.version === want; })[0] || {};
    return { url: row.url, checksum: row.checksum, file: versionedFile(it.file, want) };
  }
  // Mirrors emdatabase.metadata.versioned_filename: w.pt -> w_260902.pt.
  function versionedFile(file, version) {
    return String(file || "").replace(/(\.[^.]*)$/, "_" + version + "$1");
  }
  function versionSelect(it, version) {
    var select = el("select", "emdb-version");
    select.title = "Which version to load or download";
    [["", "latest"]].concat((it.versions || []).map(function (v) {
      return [v.version, v.version];
    })).forEach(function (choice) {
      var option = document.createElement("option");
      option.value = choice[0];
      option.textContent = choice[1];
      option.selected = choice[0] === version;
      select.appendChild(option);
    });
    select.addEventListener("change", function () {
      state.version[it.name] = select.value;
      drawDetails();
    });
    return select;
  }
  function drawDetails() {
    var it = findItem(state.hovered || state.selected);
    detailsEl.innerHTML = "";
    if (!it) { detailsEl.appendChild(el("div", "emdb-details-empty", "Hover or select an entry.")); return; }
    var version = currentVersion(it);
    var pin = versionState(it, version);
    var title = el("div", "emdb-d-title", esc(it.name));
    if (it.kind === "weights") title.appendChild(el("span", "emdb-kind", "weights"));
    if ((it.versions || []).length) title.appendChild(versionSelect(it, version));
    detailsEl.appendChild(title);
    detailsEl.appendChild(el("div", "emdb-d-sub",
      esc([(it.technique || []).join(", "), it.size, it.shape]
        .filter(Boolean).join("  ·  "))));
    if (it.description) detailsEl.appendChild(el("p", "emdb-d-desc", esc(it.description)));
    var pairs = [["Detector", it.detector], ["Microscope", it.microscope], ["Voltage", it.voltage],
      ["Tags", (it.tags || []).join(", ")], ["Authors", (it.authors || []).join(", ")],
      ["License", it.license], ["DOI", it.doi],
      ["Versions", (it.versions || []).map(function (v) { return v.version; }).join(", ")],
      ["md5", it.kind === "weights" ? String(pin.checksum || "").replace(/^md5:/, "") : ""],
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
    var call = version ? '().download(version="' + version + '")' : "().download()";
    var snippet = it.kind === "weights"
      ? "import torch\nfrom emdatabase import data\n\npath = data." + it.name
        + call + "\ncheckpoint = torch.load(path, weights_only=True)"
      : toSnake(it.name) + " = emdatabase.data." + it.name + "()";
    detailsEl.appendChild(copyRow(snippet, snippet));
    if (pin.url) {
      var wrap = el("div", "emdb-dl-link");
      var a = document.createElement("a");
      a.href = pin.url; a.target = "_blank"; a.rel = "noopener";
      a.className = "emdb-dl-anchor"; a.textContent = "⤓ Download " + pin.file;
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
# weights / add-dataset) is a self-contained file: the widget CSS is inlined,
# the palette and top-nav live in _APP_CSS, and the catalogue JSON is baked in
# at build time so search and the list work with no backend and no external
# requests.
# ---------------------------------------------------------------------------

# Palette + top-nav + hero, keyed to the same Catppuccin tokens browser.css
# defines on .emdb (mirrored here on :root so the nav and hero get them too).
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

# Styling for the Add Dataset explainer page.
_EXPLAINER_CSS = """
.explainer { max-width: 780px; margin: 0 auto; }
.explainer h2 {
  font-size: 13px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--emdb-subtext); margin: 34px 0 12px; padding-top: 18px;
  border-top: 1px solid var(--emdb-surface0);
}
.explainer ul { padding-left: 20px; margin: 0; }
.explainer li { margin: 8px 0; }
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
    escaping. Every page is self-contained: the CSS and any ``scripts`` are
    inlined, and none of them loads an external resource.
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

    Tabs are every acquisition technique, so one with no dataset in it yet
    still shows, plus anything else present, in the browser's group order. For
    the weights page there is one group, so the tabs are whatever is there.
    """
    from emdatabase import catalogue

    payload = catalogue.catalogue(kind=kind)
    present = [g["technique"] for g in payload.get("groups", [])]
    if kind == "weights":
        return payload, present
    return payload, catalogue.ordered_groups([*acquisition_techniques(), *present])


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

    Each entry is one model, with a ``latest`` link and a dated version for
    every state that link has served. emdatabase downloads the checkpoint and
    nothing else, so the load snippet is where the page says how to open it -
    ``weights_only=True``, which is the condition of a checkpoint being
    accepted in the first place.
    """
    payload, tabs = _catalogue_payload(kind="weights")
    note = "" if payload.get("groups") else "<p>No model weights are published yet.</p>"
    body = (
        '<main class="app-main">'
        '<div class="app-hero" style="padding:18px 0 4px">'
        '<h1 style="font-size:30px">Model Weights</h1>'
        "<p>Trained model checkpoints, one entry per model. Downloading an entry "
        "follows its <code>latest</code> link, which serves whatever the current "
        "weights are; every earlier state of that link is kept as a dated version, "
        "pinned to its checksum. Pick one with the selector; the load snippet "
        "opens it with <code>weights_only=True</code>.</p>"
        "<p><code>download()</code> warns when the index on the project's "
        "<code>main</code> branch has newer weights than your installed release, "
        "and <code>download(refresh=True)</code> fetches them; the "
        "<code>check_updates</code> config key turns that check off.</p>" + note + "</div>"
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
        '<div class="app-hero" style="padding:24px 0 6px">'
        '<h1 style="font-size:32px">Add a Dataset</h1>'
        "<p>Submissions go through an issue. Fill in the new-dataset issue form and "
        "an action turns it into the entry\u2019s YAML file, fills in whatever it can "
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
        "<pre><code>" + _esc(_CLI_COMMAND) + "</code></pre>"
        "<p>It asks the same questions at the prompt and writes the YAML file, leaving "
        "the pull request to you. A trained model checkpoint takes "
        "<code>--kind weights</code> as well.</p>"
        "<p>It computes the checksum from the file on your own machine rather than on "
        "GitHub, which is the route to take for a very large file.</p>"
        '<p class="note">Full instructions, including writing the entry by hand and '
        'what CI checks: <a href="contributing.html">Contributing a Dataset</a>.</p>'
        "</div></main>"
    )
    return _app_page(
        "Add Dataset &middot; EM-Database",
        body,
        active="Add Dataset",
        extra_css=_EXPLAINER_CSS,
    )


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
