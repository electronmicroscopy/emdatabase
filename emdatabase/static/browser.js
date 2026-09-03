// browser.js - frontend for emdatabase.browse()
//
// A dataset browser themed after SpyDE (Catppuccin Mocha): technique tabs +
// search at the top, a scrollable list on the left with ○/● download status, a
// details panel on the right, and download toasts pinned to the bottom-right of
// the viewport. Rendering is a pure function of state (model traits + a little
// local UI state), so a button never gets stuck on a one-shot label.

const MB = 1e6;

const TAB_LABEL = { "In-situ TEM": "In-situ", "Cryo-EM": "Cryo" };

function fmtMB(bytes) {
  const mb = bytes / MB;
  if (mb >= 100) return mb.toFixed(0);
  if (mb >= 10) return mb.toFixed(1);
  return mb.toFixed(2);
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html != null) node.innerHTML = html;
  return node;
}

// CamelCase class name -> snake_case variable, e.g. AlNanocrystals -> al_nanocrystals.
function toSnake(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
}

// Copy text to the clipboard (clipboard API, with a textarea fallback for
// non-secure contexts) and briefly flash the button so the click is felt.
function copyText(text, btn) {
  const done = () => {
    const old = btn.textContent;
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = old; btn.classList.remove("copied"); }, 1100);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ }
  ta.remove();
}

function render({ model, el: root }) {
  root.classList.add("emdb");
  root.innerHTML = "";

  // --- local UI state --------------------------------------------------
  const state = {
    tab: "All",
    search: "",
    selected: null,   // name shown in the details panel (sticky)
    hovered: null,    // name under the cursor (transient preview)
    version: {},      // name -> chosen version of a weights family ("" = latest)
    optimistic: new Set(),  // labels just clicked, before Python confirms
    cancelling: new Set(),  // tokens whose ✕ was clicked, awaiting teardown
    activeSig: "",    // signature of the active-download set, to avoid churn
  };

  // --- static structure ------------------------------------------------
  const header = el("div", "emdb-header");
  const tabsEl = el("div", "emdb-tabs");
  const body = el("div", "emdb-body");
  const listEl = el("div", "emdb-list");
  const detailsEl = el("div", "emdb-details");
  body.appendChild(listEl);
  body.appendChild(detailsEl);
  root.appendChild(header);
  root.appendChild(tabsEl);
  root.appendChild(body);

  // Toasts live on <body> so `position: fixed` is relative to the viewport
  // (an ancestor transform in the notebook would otherwise trap them).
  const toastRoot = el("div", "emdb-toast-root");
  document.body.appendChild(toastRoot);

  // Send a command to Python via a synced trait (reliable two-way sync); the
  // nonce makes a repeated action (e.g. two cancels) still register as a change.
  let nonce = 0;
  function cmd(action, extra) {
    model.set("_command", Object.assign({ action, nonce: nonce++ }, extra || {}));
    model.save_changes();
  }

  // --- derived data ----------------------------------------------------
  const allItems = () => (model.get("groups") || []).flatMap((g) => g.items);

  function techniques() {
    return (model.get("groups") || []).map((g) => g.technique);
  }

  // A download is labelled "Name" or "Name@260902"; the list marks the entry
  // whatever version is running, the details panel marks the one selected.
  function labelFor(name, version) {
    return version ? name + "@" + version : name;
  }

  function activeLabels() {
    const labels = new Set(state.optimistic);
    const downloads = model.get("downloads") || {};
    for (const dl of Object.values(downloads)) {
      if (!dl.error) labels.add(dl.label);
    }
    return labels;
  }

  function activeNames() {
    return new Set([...activeLabels()].map((label) => label.split("@")[0]));
  }

  // Which version the details panel is showing: "" is latest, and is all a
  // dataset (or a family whose selection has gone away) ever has.
  function currentVersion(item) {
    const chosen = state.version[item.name];
    if (!chosen) return "";
    return (item.versions || []).some((v) => v.version === chosen) ? chosen : "";
  }

  // The download state of one version: the same shape as an item's own fields,
  // which describe latest, so one set of helpers reads either.
  function versionState(item, version) {
    if (!version) return item;
    return (item.versions || []).find((v) => v.version === version) || {};
  }

  function matchesSearch(item) {
    if (!state.search) return true;
    // `item.search` is a lowercased blob of every field (name, description,
    // detector, microscope, tags, authors + affiliations, license, …), so a
    // query like "Carter Francis" matches on author, not just the name.
    // emdatabase.search() matches this same blob by this same rule; matching
    // stays here rather than in the kernel so typing never waits on a round trip.
    const blob = item.search || item.name.toLowerCase();
    return state.search.toLowerCase().split(/\s+/).every((term) => blob.includes(term));
  }

  function findItem(name) {
    return allItems().find((it) => it.name === name) || null;
  }

  // --- header ----------------------------------------------------------
  function drawHeader() {
    const nDown = model.get("n_downloaded") || 0;
    const nTot = model.get("n_total") || 0;
    header.innerHTML = "";
    const left = el("div", "emdb-brand", `<span class="emdb-diamond">◆</span> Datasets`);
    const count = el("div", "emdb-count", `${nDown} / ${nTot} downloaded`);
    const top = el("div", "emdb-header-top");
    top.appendChild(left);
    top.appendChild(count);
    header.appendChild(top);

    const search = el("input", "emdb-search");
    search.type = "text";
    search.placeholder = "Search datasets…";
    search.value = state.search;
    search.addEventListener("input", () => {
      state.search = search.value;
      drawList();
    });
    header.appendChild(search);
  }

  // --- tabs ------------------------------------------------------------
  function drawTabs() {
    tabsEl.innerHTML = "";
    const tabs = ["All", ...techniques()];
    for (const tab of tabs) {
      const label = tab === "All" ? "All" : (TAB_LABEL[tab] || tab);
      const btn = el("button", "emdb-tab" + (state.tab === tab ? " active" : ""), esc(label));
      btn.addEventListener("click", () => {
        state.tab = tab;
        drawTabs();
        drawList();
      });
      tabsEl.appendChild(btn);
    }
  }

  // --- list ------------------------------------------------------------
  function drawList() {
    const active = activeNames();
    listEl.innerHTML = "";
    const groups = model.get("groups") || [];
    let shown = 0;
    for (const group of groups) {
      if (state.tab !== "All" && group.technique !== state.tab) continue;
      const items = group.items.filter(matchesSearch);
      if (!items.length) continue;
      if (state.tab === "All") {
        listEl.appendChild(el("div", "emdb-group-head", esc(group.technique)));
      }
      for (const item of items) {
        listEl.appendChild(drawRow(item, active));
        shown += 1;
      }
    }
    if (!shown) {
      listEl.appendChild(el("div", "emdb-empty", "No datasets match."));
    }
    if (!state.selected && groups.length) {
      state.selected = allItems()[0]?.name || null;
    }
    drawDetails();
  }

  function drawRow(item, active) {
    const isActive = active.has(item.name);
    const row = el("div", "emdb-row" + (state.selected === item.name ? " selected" : ""));
    const meta = [item.size, item.shape].filter(Boolean).join("  ·  ");
    const glyph = el("span", "emdb-glyph " + glyphClass(item), item.downloaded ? "●" : "○");
    if (inShared(item)) glyph.title = sharedTitle(item);
    row.appendChild(glyph);
    row.appendChild(el("span", "emdb-name", esc(item.name)));
    row.appendChild(el("span", "emdb-meta", esc(meta)));
    row.appendChild(drawAction(item, isActive));

    row.addEventListener("mouseenter", () => { state.hovered = item.name; drawDetails(); });
    row.addEventListener("click", () => { state.selected = item.name; drawList(); });
    return row;
  }

  // `location` is the name of the location a copy was found in; "personal" is
  // the user's own directory. `where` is an item (which describes latest) or
  // one of its versions.
  function inShared(where) {
    return where.downloaded && where.location && where.location !== "personal";
  }

  // A shared copy and your own can both exist; the tooltip names each.
  function sharedTitle(where) {
    const lines = ["from " + where.location + ": " + where.path];
    if (where.user_path) lines.push("your copy: " + where.user_path);
    return lines.join("\n");
  }

  function glyphClass(item) {
    if (!item.downloaded) return "off";
    return inShared(item) ? "shared" : "on";
  }

  function drawAction(item, isActive) {
    const wrap = el("span", "emdb-actions");
    if (item.downloaded) {
      wrap.appendChild(el("span", "emdb-check", "✓"));
    } else if (isActive) {
      wrap.appendChild(el("span", "emdb-spinner", "downloading…"));
    } else {
      const btn = el("button", "emdb-dl", "Download");
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        startDownload(item.name);
      });
      wrap.appendChild(btn);
    }
    return wrap;
  }

  // --- details panel ---------------------------------------------------
  function drawDetails() {
    const name = state.hovered || state.selected;
    const item = name ? findItem(name) : null;
    detailsEl.innerHTML = "";
    if (!item) {
      detailsEl.appendChild(el("div", "emdb-details-empty", "Hover or select a dataset."));
      return;
    }
    const version = currentVersion(item);
    const where = versionState(item, version);
    const active = activeLabels().has(labelFor(item.name, version));

    const head = el("div", "emdb-d-head");
    const title = el("div", "emdb-d-title", esc(item.name));
    if (item.kind === "weights") title.appendChild(el("span", "emdb-kind", "weights"));
    if ((item.versions || []).length) title.appendChild(versionSelect(item, version));
    head.appendChild(title);
    const sub = [item.technique, item.size, item.shape].filter(Boolean).join("  ·  ");
    head.appendChild(el("div", "emdb-d-sub", esc(sub)));
    detailsEl.appendChild(head);

    // status / action line, for whichever version is selected
    const statusRow = el("div", "emdb-d-status");
    if (inShared(where)) {
      const label = "● " + where.location + (where.user_path ? " + yours" : "");
      const badge = el("span", "emdb-d-badge shared", esc(label));
      badge.title = sharedTitle(where);
      statusRow.appendChild(badge);
      if (where.user_path) {
        const del = el("button", "emdb-delete", "Delete yours");
        del.title = "Remove your copy (" + where.user_path + "). The copy in "
          + where.location + " is untouched.";
        del.addEventListener("click", () => cmd("delete", { name: item.name, version }));
        statusRow.appendChild(del);
      }
    } else if (where.downloaded) {
      statusRow.appendChild(el("span", "emdb-d-badge on", "● downloaded"));
      const del = el("button", "emdb-delete", "Delete");
      del.title = "Remove the downloaded file from disk";
      del.addEventListener("click", () => cmd("delete", { name: item.name, version }));
      statusRow.appendChild(del);
    } else if (active) {
      statusRow.appendChild(el("span", "emdb-d-badge", "downloading…"));
    } else {
      const btn = el("button", "emdb-dl", "Download");
      btn.addEventListener("click", () => startDownload(item.name, version));
      statusRow.appendChild(btn);
    }
    detailsEl.appendChild(statusRow);

    if (item.description) {
      detailsEl.appendChild(el("p", "emdb-d-desc", esc(item.description)));
    }
    const pairs = [
      ["Detector", item.detector],
      ["Microscope", item.microscope],
      ["Voltage", item.voltage],
      ["Tags", (item.tags || []).join(", ")],
      ["Authors", (item.authors || []).join(", ")],
      ["License", item.license],
      ["File", item.file],
      ["DOI", item.doi],
      ["Versions", (item.versions || []).map((v) => v.version).join(", ")],
      ["Model", item.model_class],
      ["Framework", item.model_framework],
      ["quantem", item.model_quantem],
    ];
    const meta = el("div", "emdb-d-meta");
    for (const [key, value] of pairs) {
      if (!value) continue;
      const kv = el("div", "emdb-kv");
      kv.appendChild(el("span", "emdb-k", key));
      kv.appendChild(el("span", "emdb-v", esc(value)));
      meta.appendChild(kv);
    }
    detailsEl.appendChild(meta);

    // Load block: copy a ready-to-paste snippet, and the on-disk path.
    detailsEl.appendChild(el("div", "emdb-load-label", "Load"));
    const snippet = version
      ? `path = emdatabase.data.${item.name}().download(version="${version}")`
      : `${toSnake(item.name)} = emdatabase.data.${item.name}()`;
    detailsEl.appendChild(copyRow(snippet, snippet));
    if (where.downloaded && where.path) {
      detailsEl.appendChild(copyRow(where.path, where.path, "path"));
    }
  }

  // The version picker for a weights family: `latest`, then the dated
  // snapshots, ● on the ones already on disk. Everything below it - the
  // Download/Delete button, the path and the load snippet - follows it.
  function versionSelect(item, version) {
    const select = el("select", "emdb-version");
    select.title = "Which version to download, delete or load";
    const choices = [["", "latest"]].concat(
      (item.versions || []).map((v) => [v.version, v.version])
    );
    for (const [value, text] of choices) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text + (versionState(item, value).downloaded ? " ●" : "");
      option.selected = value === version;
      select.appendChild(option);
    }
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("change", () => {
      state.version[item.name] = select.value;
      drawDetails();
    });
    return select;
  }

  function copyRow(shownText, copyValue, variant) {
    const row = el("div", "emdb-copy" + (variant ? " " + variant : ""));
    row.appendChild(el("code", "emdb-code", esc(shownText)));
    const btn = el("button", "emdb-copy-btn", "Copy");
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      copyText(copyValue, btn);
    });
    row.appendChild(btn);
    return row;
  }

  // --- downloads / toasts ---------------------------------------------
  function startDownload(name, version) {
    state.optimistic.add(labelFor(name, version));
    drawList();
    cmd("download", { name, version: version || "" });
  }

  let lastToastSig = "";
  function drawToasts() {
    const downloads = model.get("downloads") || {};
    // Drop cancelling markers for toasts that are already gone.
    for (const token of [...state.cancelling]) {
      if (!(token in downloads)) state.cancelling.delete(token);
    }
    // Signature of the toast *set* (tokens + cancelling/error state). When only
    // byte-progress changed, update numbers in place so the ✕ button isn't
    // rebuilt under the cursor (rebuilding it was eating cancel clicks).
    const tokens = Object.keys(downloads);
    const sig = tokens
      .map((t) => t + (downloads[t].error ? ":e" : state.cancelling.has(t) ? ":c" : ""))
      .sort().join("|");
    if (sig === lastToastSig) {
      for (const t of tokens) {
        if (!downloads[t].error && !state.cancelling.has(t)) updateToastProgress(t, downloads[t]);
      }
      return;
    }
    lastToastSig = sig;
    toastRoot.innerHTML = "";
    for (const [token, dl] of Object.entries(downloads)) {
      toastRoot.appendChild(dl.error ? errorToast(token, dl) : progressToast(token, dl));
    }
  }

  function updateToastProgress(token, dl) {
    let card = null;
    for (const c of toastRoot.children) { if (c.dataset.token === token) { card = c; break; } }
    if (!card) return;
    const pct = dl.total > 0 ? Math.min(100, (100 * dl.done) / dl.total) : null;
    const fill = card.querySelector(".emdb-fill");
    if (fill) {
      if (pct == null) { fill.classList.add("indet"); fill.style.width = "32%"; }
      else { fill.classList.remove("indet"); fill.style.width = pct + "%"; }
    }
    const bytes = card.querySelector(".emdb-bytes");
    if (bytes) {
      bytes.textContent = pct == null ? `${fmtMB(dl.done)} MB`
        : `${fmtMB(dl.done)} / ${fmtMB(dl.total)} MB · ${pct.toFixed(0)}%`;
    }
  }

  function progressToast(token, dl) {
    const cancelling = state.cancelling.has(token);
    const pct = dl.total > 0 ? Math.min(100, (100 * dl.done) / dl.total) : null;
    const card = el("div", "emdb-toast" + (cancelling ? " cancelling" : ""));
    card.dataset.token = token;
    const bar = pct == null || cancelling
      ? `<div class="emdb-fill indet" style="width:32%"></div>`
      : `<div class="emdb-fill" style="width:${pct}%"></div>`;
    const bytes = cancelling
      ? "Cancelling…"
      : (pct == null
        ? `${fmtMB(dl.done)} MB`
        : `${fmtMB(dl.done)} / ${fmtMB(dl.total)} MB · ${pct.toFixed(0)}%`);
    card.innerHTML =
      `<div class="emdb-toast-row"><span class="emdb-toast-title">${esc(dl.label)}</span>` +
      `<button class="emdb-x" title="Cancel download">✕</button></div>` +
      `<div class="emdb-track">${bar}</div>` +
      `<div class="emdb-bytes">${bytes}</div>`;
    // Send the cancel FIRST (so a redraw can't drop it), and keep the button
    // clickable so a second click re-sends if the first didn't land.
    card.querySelector(".emdb-x").addEventListener("click", () => {
      cmd("cancel", { token });
      state.cancelling.add(token);
      drawToasts();
    });
    return card;
  }

  function errorToast(token, dl) {
    const card = el("div", "emdb-toast error");
    card.innerHTML =
      `<div class="emdb-toast-row"><span class="emdb-toast-title">Failed: ${esc(dl.label)}</span>` +
      `<button class="emdb-x" title="Dismiss">✕</button></div>` +
      `<div class="emdb-toast-err">${esc(dl.error)}</div>`;
    card.querySelector(".emdb-x").addEventListener("click", () => {
      cmd("dismiss", { token });
    });
    return card;
  }

  // --- events ----------------------------------------------------------
  listEl.addEventListener("mouseleave", () => { state.hovered = null; drawDetails(); });

  const onGroups = () => { drawTabs(); drawList(); };
  const onCounts = () => drawHeader();
  const onDownloads = () => {
    // A confirmed state change clears the optimistic guesses.
    state.optimistic.clear();
    const sig = [...activeNames()].sort().join("|");
    if (sig !== state.activeSig) {   // membership changed -> refresh buttons
      state.activeSig = sig;
      drawList();
    }
    drawToasts();
  };
  model.on("change:groups", onGroups);
  model.on("change:n_downloaded", onCounts);
  model.on("change:n_total", onCounts);
  model.on("change:downloads", onDownloads);

  // --- first paint -----------------------------------------------------
  drawHeader();
  drawTabs();
  drawList();
  drawToasts();

  // Cleanup when the widget view goes away.
  return () => {
    toastRoot.remove();
    model.off("change:groups", onGroups);
    model.off("change:n_downloaded", onCounts);
    model.off("change:n_total", onCounts);
    model.off("change:downloads", onDownloads);
  };
}

export default { render };
