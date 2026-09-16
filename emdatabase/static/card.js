// card.js - frontend for one dataset's card, what display(ds) shows;
// widget.py puts common.js first.
//
// The same content as the browser's details panel, standalone, with running
// downloads shown inline under the status line. Shares browser.css for styling.

function render({ model, el: root }) {
  root.classList.add("emdb");
  const card = el("div", "emdb-card");
  root.appendChild(card);
  const toasts = el("div", "emdb-toasts");
  const view = newView(model, () => drawEntry(card, model.get("info"), view, toasts));

  const onDownloads = () => downloadsChanged(view, toasts);
  model.on("change:info", view.redraw);
  model.on("change:downloads", onDownloads);
  onDownloads();  // draws the card and its downloads

  return () => {
    model.off("change:info", view.redraw);
    model.off("change:downloads", onDownloads);
  };
}

export default { render };
