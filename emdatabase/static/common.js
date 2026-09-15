// common.js - what browser.js and card.js share.
//
// anywidget loads each widget's `_esm` as a single module and there is no
// bundler, so widget.py puts this file in front of each widget's own file
// rather than having them import it.

const MB = 1e6;

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

// --- a widget view -----------------------------------------------------

// What one view of a widget keeps between draws. `cmd` sends a command to
// Python through the synced `_command` trait; the nonce makes a repeated
// action (e.g. two cancels) still register as a change.
function newView(model, redraw) {
  let nonce = 0;
  return {
    model,
    redraw,
    cmd(action, extra) {
      model.set("_command", Object.assign({ action, nonce: nonce++ }, extra));
      model.save_changes();
    },
    optimistic: new Set(),  // labels just clicked, before Python confirms
    versions: {},           // name -> chosen version of a weights family ("" = latest)
    activeSig: null,        // the running downloads at the last redraw
  };
}

// A download is labelled "Name" or "Name@260902", as widget.py names it.
function labelFor(name, version) {
  return version ? name + "@" + version : name;
}

function activeLabels(view) {
  const labels = new Set(view.optimistic);
  for (const dl of Object.values(view.model.get("downloads"))) {
    if (!dl.error) labels.add(dl.label);
  }
  return labels;
}

function startDownload(view, name, version) {
  view.optimistic.add(labelFor(name, version));
  view.redraw();
  view.cmd("download", { name, version });
}

// `downloads` changed, so Python has confirmed or refused what was clicked.
// Redraw only if the set of running downloads changed; a byte count changing
// needs just the toasts.
function downloadsChanged(view, stack) {
  view.optimistic.clear();
  const sig = [...activeLabels(view)].sort().join("|");
  if (sig !== view.activeSig) {
    view.activeSig = sig;
    view.redraw();
  }
  drawToasts(stack, view);
}

// --- download progress -----------------------------------------------

// One toast per entry of `downloads`, drawn into `stack` inside the widget:
// progress and a cancel button while it runs, the error and a dismiss button
// once it has failed. The toasts are rebuilt only when that set changes; a
// byte count is updated in place, so the ✕ button is not rebuilt under the
// cursor (which was eating cancel clicks).
function drawToasts(stack, view) {
  const downloads = view.model.get("downloads");
  const cancelling = (stack.cancelling ||= new Set());
  for (const token of cancelling) if (!(token in downloads)) cancelling.delete(token);
  const sig = Object.keys(downloads)
    .map((t) => t + (downloads[t].error ? ":e" : cancelling.has(t) ? ":c" : ""))
    .sort().join("|");
  if (stack.dataset.sig !== sig) {
    stack.dataset.sig = sig;
    stack.innerHTML = "";
    for (const [token, dl] of Object.entries(downloads)) {
      const toast = el("div", "emdb-toast"
        + (dl.error ? " error" : cancelling.has(token) ? " cancelling" : ""));
      toast.dataset.token = token;
      toast.innerHTML =
        `<div class="emdb-toast-row"><span class="emdb-toast-title">`
        + esc((dl.error ? "Failed: " : "") + dl.label) + `</span>`
        + `<button class="emdb-x" title="${dl.error ? "Dismiss" : "Cancel download"}">✕</button></div>`
        + (dl.error
          ? `<div class="emdb-toast-err">${esc(dl.error)}</div>`
          : `<div class="emdb-track"><div class="emdb-fill"></div></div><div class="emdb-bytes"></div>`);
      toast.querySelector(".emdb-x").addEventListener("click", () => {
        if (dl.error) { view.cmd("dismiss", { token }); return; }
        // Send the cancel first, so a redraw can't drop it, and keep the button
        // clickable so a second click re-sends if the first didn't land.
        view.cmd("cancel", { token });
        cancelling.add(token);
        drawToasts(stack, view);
      });
      stack.appendChild(toast);
    }
  }
  for (const toast of stack.children) {
    const dl = downloads[toast.dataset.token];
    if (dl.error) continue;
    const pct = cancelling.has(toast.dataset.token) || !(dl.total > 0)
      ? null : Math.min(100, (100 * dl.done) / dl.total);
    const fill = toast.querySelector(".emdb-fill");
    fill.classList.toggle("indet", pct == null);
    fill.style.width = pct == null ? "32%" : pct + "%";
    toast.querySelector(".emdb-bytes").textContent =
      cancelling.has(toast.dataset.token) ? "Cancelling…"
        : pct == null ? `${fmtMB(dl.done)} MB`
          : `${fmtMB(dl.done)} / ${fmtMB(dl.total)} MB · ${pct.toFixed(0)}%`;
  }
}

// --- one catalogue row -------------------------------------------------

// The download state of one version: an item's own fields describe latest, so
// the same reads work for the item or for one of its `versions`.
function versionState(item, version) {
  if (!version) return item;
  return item.versions.find((v) => v.version === version) || {};
}

// `location` names the location a copy was found in; "personal" is the user's
// own directory.
function inShared(where) {
  return where.downloaded && where.location !== "personal";
}

// A shared copy and your own can both exist; the tooltip names each.
function sharedTitle(where) {
  return "from " + where.location + ": " + where.path
    + (where.user_path ? "\nyour copy: " + where.user_path : "");
}

function copyRow(text, variant) {
  const row = el("div", "emdb-copy" + (variant ? " " + variant : ""));
  row.appendChild(el("code", "emdb-code", esc(text)));
  const btn = el("button", "emdb-copy-btn", "Copy");
  btn.addEventListener("click", () => copyText(text, btn));
  row.appendChild(btn);
  return row;
}

// Draw `item` into `parent`: what the browser's details panel and a dataset's
// card both show. A weights family gets a version picker - `latest`, then the
// dated snapshots, ● on those on disk - and the status, the path and the load
// snippet all follow it. `toasts`, if given, goes under the status line.
function drawEntry(parent, item, view, toasts) {
  const chosen = view.versions[item.name];
  const version = item.versions.some((v) => v.version === chosen) ? chosen : "";
  const where = versionState(item, version);
  parent.innerHTML = "";

  const title = el("div", "emdb-d-title", esc(item.name));
  if (item.kind === "weights") title.appendChild(el("span", "emdb-kind", "weights"));
  if (item.versions.length) {
    const select = el("select", "emdb-version");
    select.title = "Which version to download, delete or load";
    for (const value of ["", ...item.versions.map((v) => v.version)]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = (value || "latest") + (versionState(item, value).downloaded ? " ●" : "");
      option.selected = value === version;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      view.versions[item.name] = select.value;
      view.redraw();
    });
    title.appendChild(select);
  }
  parent.appendChild(title);
  const sub = [item.technique.join(", "), item.size].filter(Boolean).join("  ·  ");
  parent.appendChild(el("div", "emdb-d-sub", esc(sub)));

  const status = el("div", "emdb-d-status");
  const deleteButton = (text, tooltip) => {
    const del = el("button", "emdb-delete", text);
    del.title = tooltip;
    del.addEventListener("click", () => view.cmd("delete", { name: item.name, version }));
    status.appendChild(del);
  };
  if (activeLabels(view).has(labelFor(item.name, version))) {
    status.appendChild(el("span", "emdb-d-badge", "downloading…"));
  } else if (inShared(where)) {
    const label = "● " + where.location + (where.user_path ? " + yours" : "");
    const badge = el("span", "emdb-d-badge shared", esc(label));
    badge.title = sharedTitle(where);
    status.appendChild(badge);
    if (where.user_path) {
      deleteButton("Delete yours", "Remove your copy (" + where.user_path + "). The copy in "
        + where.location + " is untouched.");
    }
  } else if (where.downloaded) {
    status.appendChild(el("span", "emdb-d-badge on", "● downloaded"));
    deleteButton("Delete", "Remove the downloaded file from disk");
  } else {
    const btn = el("button", "emdb-dl", "Download");
    btn.addEventListener("click", () => startDownload(view, item.name, version));
    status.appendChild(btn);
  }
  parent.appendChild(status);
  if (toasts) parent.appendChild(toasts);

  const main = el("div", "emdb-d-main");
  if (item.description) main.appendChild(el("p", "emdb-d-desc", esc(item.description)));
  main.appendChild(el("div", "emdb-load-label", "Load"));
  main.appendChild(copyRow(`path = emdatabase.data.${item.name}().download(`
    + (version ? `version="${version}"` : "") + ")"));
  if (where.path) main.appendChild(copyRow(where.path, "path"));

  const meta = el("div", "emdb-d-meta");
  const pairs = [
    ["Detector", item.detector], ["Microscope", item.microscope], ["Voltage", item.voltage],
    ["Tags", item.tags.join(", ")], ["Authors", item.authors.join(", ")],
    ["License", item.license], ["File", item.file], ["DOI", item.doi],
    ["Versions", item.versions.map((v) => v.version).join(", ")],
    ["Model", item.model_class], ["Framework", item.model_framework],
    ["quantem", item.model_quantem],
  ];
  for (const [key, value] of pairs) {
    if (!value) continue;
    const kv = el("div", "emdb-kv");
    kv.appendChild(el("span", "emdb-k", key));
    kv.appendChild(el("span", "emdb-v", esc(value)));
    meta.appendChild(kv);
  }

  const cols = el("div", "emdb-d-cols");
  cols.append(main, meta);
  parent.appendChild(cols);
}
