// card.js - frontend for a single dataset's card (DownloadableDataset display).
//
// The same content as the browser's details panel, standalone: metadata,
// description, a copy-to-load block, and a Download/Delete button with inline
// progress. Shares browser.css for styling.

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

function toSnake(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
}

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
  root.classList.add("emdb", "emdb-card-host");
  const card = el("div", "emdb-card");
  root.appendChild(card);

  let nonce = 0;
  let cancelling = false;
  let downloadingNow = false;
  function cmd(action, extra) {
    model.set("_command", Object.assign({ action, nonce: nonce++ }, extra || {}));
    model.save_changes();
  }

  function copyRow(shownText, copyValue, variant) {
    const row = el("div", "emdb-copy" + (variant ? " " + variant : ""));
    row.appendChild(el("code", "emdb-code", esc(shownText)));
    const btn = el("button", "emdb-copy-btn", "Copy");
    btn.addEventListener("click", (event) => { event.stopPropagation(); copyText(copyValue, btn); });
    row.appendChild(btn);
    return row;
  }

  function progressBox(dl) {
    const pct = dl.total > 0 ? Math.min(100, (100 * dl.done) / dl.total) : null;
    const box = el("div", "emdb-inline-toast" + (cancelling ? " cancelling" : ""));
    const bar = (pct == null || cancelling)
      ? `<div class="emdb-fill indet" style="width:32%"></div>`
      : `<div class="emdb-fill" style="width:${pct}%"></div>`;
    const bytes = cancelling
      ? "Cancelling…"
      : (pct == null ? `${fmtMB(dl.done)} MB`
        : `${fmtMB(dl.done)} / ${fmtMB(dl.total)} MB · ${pct.toFixed(0)}%`);
    box.innerHTML =
      `<div class="emdb-toast-row"><span class="emdb-bytes">${bytes}</span>` +
      `<button class="emdb-x" title="Cancel download">✕</button></div>` +
      `<div class="emdb-track">${bar}</div>`;
    // Send cancel first; keep the button clickable so a retry re-sends.
    box.querySelector(".emdb-x").addEventListener("click", () => {
      cmd("cancel"); cancelling = true; draw();
    });
    return box;
  }

  function errorBox(dl) {
    const box = el("div", "emdb-inline-toast error");
    box.innerHTML =
      `<div class="emdb-toast-row"><span class="emdb-toast-err">${esc(dl.error)}</span>` +
      `<button class="emdb-x" title="Dismiss">✕</button></div>`;
    box.querySelector(".emdb-x").addEventListener("click", () => cmd("dismiss"));
    return box;
  }

  function draw() {
    const it = model.get("info") || {};
    const dl = model.get("download") || {};
    const downloading = dl.done != null && !dl.error;
    downloadingNow = downloading;
    card.innerHTML = "";

    const title = el("div", "emdb-d-title", esc(it.name || ""));
    if (it.kind === "weights") title.appendChild(el("span", "emdb-kind", "weights"));
    card.appendChild(title);
    const sub = [it.technique, it.size, it.shape].filter(Boolean).join("  ·  ");
    card.appendChild(el("div", "emdb-d-sub", esc(sub)));

    const status = el("div", "emdb-d-status");
    if (downloading) {
      status.appendChild(el("span", "emdb-d-badge", "downloading…"));
    } else if (it.downloaded && it.location && it.location !== "user") {
      // `location` is the name of the store the copy was found in.
      const label = "● " + it.location + (it.user_path ? " + yours" : "");
      const badge = el("span", "emdb-d-badge shared", esc(label));
      badge.title = "from the " + it.location + " store: " + it.path
        + (it.user_path ? "\nyour copy: " + it.user_path : "");
      status.appendChild(badge);
      if (it.user_path) {
        const del = el("button", "emdb-delete", "Delete yours");
        del.title = "Remove your copy (" + it.user_path + "). The " + it.location
          + " store keeps its own.";
        del.addEventListener("click", () => cmd("delete"));
        status.appendChild(del);
      }
    } else if (it.downloaded) {
      status.appendChild(el("span", "emdb-d-badge on", "● downloaded"));
      const del = el("button", "emdb-delete", "Delete");
      del.title = "Remove the downloaded file from disk";
      del.addEventListener("click", () => cmd("delete"));
      status.appendChild(del);
    } else {
      const btn = el("button", "emdb-dl", "Download");
      btn.addEventListener("click", () => { btn.disabled = true; btn.textContent = "starting…"; cmd("download"); });
      status.appendChild(btn);
    }
    card.appendChild(status);

    if (downloading) card.appendChild(progressBox(dl));
    else if (dl.error) card.appendChild(errorBox(dl));

    // Two columns: description + load on the left (wide), metadata on the right.
    const cols = el("div", "emdb-card-cols");
    const main = el("div", "emdb-card-col-main");
    const side = el("div", "emdb-card-col-side");

    if (it.description) main.appendChild(el("p", "emdb-d-desc", esc(it.description)));
    main.appendChild(el("div", "emdb-load-label", "Load"));
    const snippet = `${toSnake(it.name || "dataset")} = emdatabase.data.${it.name}()`;
    main.appendChild(copyRow(snippet, snippet));
    if (it.downloaded && it.path) main.appendChild(copyRow(it.path, it.path, "path"));

    const pairs = [
      ["Detector", it.detector], ["Microscope", it.microscope], ["Voltage", it.voltage],
      ["Tags", (it.tags || []).join(", ")], ["Authors", (it.authors || []).join(", ")],
      ["License", it.license], ["File", it.file], ["DOI", it.doi],
      ["Version", it.version], ["Model", it.model_class],
      ["Framework", it.model_framework], ["quantem", it.model_quantem],
    ];
    const meta = el("div", "emdb-d-meta");
    for (const [key, value] of pairs) {
      if (!value) continue;
      const kv = el("div", "emdb-kv");
      kv.appendChild(el("span", "emdb-k", key));
      kv.appendChild(el("span", "emdb-v", esc(value)));
      meta.appendChild(kv);
    }
    side.appendChild(meta);

    cols.appendChild(main);
    cols.appendChild(side);
    card.appendChild(cols);
  }

  // Update the progress bar/bytes IN PLACE so the ✕ button is never rebuilt
  // mid-download (rebuilding it under the cursor was eating cancel clicks).
  function updateProgress(dl) {
    const box = card.querySelector(".emdb-inline-toast");
    if (!box || cancelling) { draw(); return; }
    const pct = dl.total > 0 ? Math.min(100, (100 * dl.done) / dl.total) : null;
    const fill = box.querySelector(".emdb-fill");
    if (fill) {
      if (pct == null) { fill.classList.add("indet"); fill.style.width = "32%"; }
      else { fill.classList.remove("indet"); fill.style.width = pct + "%"; }
    }
    const bytesEl = box.querySelector(".emdb-bytes");
    if (bytesEl) {
      bytesEl.textContent = pct == null ? `${fmtMB(dl.done)} MB`
        : `${fmtMB(dl.done)} / ${fmtMB(dl.total)} MB · ${pct.toFixed(0)}%`;
    }
  }

  const onInfo = () => { cancelling = false; draw(); };
  const onDownload = () => {
    const dl = model.get("download") || {};
    const downloading = dl.done != null && !dl.error;
    // A byte-progress tick while already downloading: update numbers only.
    if (downloading && downloadingNow && !cancelling) { updateProgress(dl); return; }
    if (!downloading) cancelling = false;  // cleared/failed -> reset
    draw();
  };
  model.on("change:info", onInfo);
  model.on("change:download", onDownload);
  draw();

  return () => {
    model.off("change:info", onInfo);
    model.off("change:download", onDownload);
  };
}

export default { render };
