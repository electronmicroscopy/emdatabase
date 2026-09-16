// browser.js - frontend for emdatabase.browse(); widget.py puts common.js first.
//
// A dataset browser themed after SpyDE (Catppuccin Mocha): technique tabs +
// search at the top, a scrollable list on the left with ○/● download status, a
// details panel on the right, and each running download's progress along the
// bottom. Rendering is a pure function of state (model traits + a little
// local UI state), so a button never gets stuck on a one-shot label.

function render({ model, el: root }) {
  root.classList.add("emdb");

  const state = {
    tab: "All",
    search: "",
    selected: null,   // name shown in the details panel (sticky)
    hovered: null,    // name under the cursor (transient preview)
  };
  const view = newView(model, () => drawList());

  const header = el("div", "emdb-header");
  const top = el("div", "emdb-header-top",
    `<div class="emdb-brand"><span class="emdb-diamond">◆</span> Datasets</div>`);
  const count = el("div", "emdb-count");
  const search = el("input", "emdb-search");
  search.type = "text";
  search.placeholder = "Search datasets…";
  search.addEventListener("input", () => { state.search = search.value; drawList(); });
  top.appendChild(count);
  header.append(top, search);
  const tabsEl = el("div", "emdb-tabs");
  const listEl = el("div", "emdb-list");
  const detailsEl = el("div", "emdb-details");
  const body = el("div", "emdb-body");
  body.append(listEl, detailsEl);
  const toasts = el("div", "emdb-toasts");
  root.append(header, tabsEl, body, toasts);

  const allItems = () => model.get("groups").flatMap((g) => g.items);

  function drawCount() {
    count.textContent = `${model.get("n_downloaded")} / ${model.get("n_total")} downloaded`;
  }

  function drawTabs() {
    fillTabs(tabsEl, model.get("groups").map((g) => g.technique), state, drawList);
  }

  function drawList() {
    // A row is marked whichever version of it is running.
    const active = new Set([...activeLabels(view)].map((label) => label.split("@")[0]));
    fillList(listEl, model.get("groups"), state, (item) => drawRow(item, active.has(item.name)),
      "No datasets match.");
    state.selected ??= allItems()[0]?.name;
    drawDetails();
  }

  function drawRow(item, active) {
    const row = el("div", "emdb-row" + (state.selected === item.name ? " selected" : ""));
    const shared = inShared(item);
    const glyph = el("span", "emdb-glyph " + (shared ? "shared" : item.downloaded ? "on" : "off"),
      item.downloaded ? "●" : "○");
    if (shared) glyph.title = sharedTitle(item);
    const actions = el("span", "emdb-actions");
    if (item.downloaded) {
      actions.appendChild(el("span", "emdb-check", "✓"));
    } else if (active) {
      actions.appendChild(el("span", "emdb-spinner", "downloading…"));
    } else {
      const btn = el("button", "emdb-dl", "Download");
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        startDownload(view, item.name, "");
      });
      actions.appendChild(btn);
    }
    row.append(glyph, el("span", "emdb-name", esc(item.name)),
      el("span", "emdb-meta", esc(item.size)), actions);
    row.addEventListener("mouseenter", () => { state.hovered = item.name; drawDetails(); });
    row.addEventListener("click", () => { state.selected = item.name; drawList(); });
    return row;
  }

  function drawDetails() {
    const name = state.hovered || state.selected;
    const item = allItems().find((it) => it.name === name);
    if (item) drawEntry(detailsEl, item, view);
    else detailsEl.innerHTML = `<div class="emdb-details-empty">Hover or select a dataset.</div>`;
  }

  listEl.addEventListener("mouseleave", () => { state.hovered = null; drawDetails(); });

  const onGroups = () => { drawTabs(); drawList(); };
  const onDownloads = () => downloadsChanged(view, toasts);
  model.on("change:groups", onGroups);
  model.on("change:n_downloaded", drawCount);
  model.on("change:n_total", drawCount);
  model.on("change:downloads", onDownloads);

  drawCount();
  drawTabs();
  onDownloads();  // draws the list, the details panel and the toasts

  return () => {
    model.off("change:groups", onGroups);
    model.off("change:n_downloaded", drawCount);
    model.off("change:n_total", drawCount);
    model.off("change:downloads", onDownloads);
  };
}

export default { render };
