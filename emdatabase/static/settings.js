// settings.js - an editable settings panel (what display(emdatabase.settings) shows).
//
// Edit the data directory directly: type a path and Save (persist), Use for
// session (in-memory), or Reset to the default. Also shows the settings-file
// location and the shared-then-user search order.

function esc(value) {
  return String(value).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function el(tag, cls, html) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}

function render({ model, el: root }) {
  root.classList.add("emdb", "emdb-settings-host");

  let nonce = 0;
  function cmd(action, extra) {
    model.set("_command", Object.assign({ action, nonce: nonce++ }, extra || {}));
    model.save_changes();
  }

  function draw() {
    root.innerHTML = "";
    const wrap = el("div", "emdb-settings");
    wrap.appendChild(el("div", "emdb-brand", '<span class="emdb-diamond">◆</span> Settings'));

    // Data directory field
    const field = el("div", "emdb-field");
    field.appendChild(el("div", "emdb-field-label", "Data directory"));
    // Input + Browse on one line (Browse to the right of the path field).
    const row = el("div", "emdb-field-row");
    const input = el("input", "emdb-search");
    input.type = "text";
    input.value = model.get("data_dir") || "";
    input.placeholder = model.get("default_dir") || "";
    input.spellcheck = false;
    row.appendChild(input);
    const browse = el("button", "emdb-browse", "Browse…");
    browse.title = "Pick any file inside the folder you want; its folder is used";
    row.appendChild(browse);
    field.appendChild(row);

    // Client-side picker: a plain file <input> (a normal "Open" dialog, no
    // "upload" prompt). We use the selected file's parent as the directory. The
    // absolute path is available on desktop/Electron (File.path); a plain
    // browser hides it, so we fall back to asking the user to type it.
    const picker = el("input");
    picker.type = "file";
    picker.style.display = "none";
    field.appendChild(picker);
    const hint = el("div", "emdb-hint");
    field.appendChild(hint);

    browse.addEventListener("click", function () { picker.click(); });
    picker.addEventListener("change", function () {
      const f = picker.files && picker.files[0];
      if (f) {
        if (f.path) {  // absolute path available (desktop/Electron)
          const dir = f.path.slice(0, f.path.length - f.name.length).replace(/[\\/]+$/, "");
          input.value = dir;
          hint.textContent = "Selected " + dir + " — click Save to keep it.";
        } else {
          hint.textContent =
            "This browser can’t share the folder’s path — type it above instead.";
        }
      }
      picker.value = "";  // let the same file be picked again
    });

    const actions = el("div", "emdb-field-actions");
    const save = el("button", "emdb-dl", "Save");
    save.title = "Set and remember across sessions";
    save.addEventListener("click", function () { cmd("save", { data_dir: input.value.trim() }); });
    const session = el("button", "emdb-copy-btn", "Use for session");
    session.title = "Set for this session only (not written to disk)";
    session.addEventListener("click", function () { cmd("session", { data_dir: input.value.trim() }); });
    const reset = el("button", "emdb-delete", "Reset");
    reset.title = "Back to the default location";
    reset.addEventListener("click", function () { cmd("reset"); });
    actions.appendChild(save);
    actions.appendChild(session);
    actions.appendChild(reset);
    field.appendChild(actions);
    wrap.appendChild(field);

    const status = model.get("status");
    if (status) wrap.appendChild(el("div", "emdb-status", esc(status)));

    // Info: settings file + search order
    const info = el("div", "emdb-settings-info");
    info.appendChild(el("div", "emdb-kv",
      '<span class="emdb-k">Settings file</span>' +
      '<span class="emdb-v">' + esc(model.get("config_path") || "") + "</span>"));

    const dirs = model.get("search_dirs") || [];
    if (dirs.length) {
      info.appendChild(el("div", "emdb-field-label", "Search order"));
      const list = el("div", "emdb-searchlist");
      dirs.forEach(function (d, i) {
        const last = i === dirs.length - 1;
        const tag = last
          ? '<span class="emdb-tag">downloads here</span>'
          : '<span class="emdb-tag shared">shared</span>';
        list.appendChild(el("div", "emdb-searchdir", esc(d) + "  " + tag));
      });
      info.appendChild(list);
    }
    wrap.appendChild(info);
    root.appendChild(wrap);
  }

  const redraw = function () { draw(); };
  model.on("change:data_dir", redraw);
  model.on("change:status", redraw);
  model.on("change:search_dirs", redraw);
  model.on("change:config_path", redraw);
  draw();

  return function () {
    model.off("change:data_dir", redraw);
    model.off("change:status", redraw);
    model.off("change:search_dirs", redraw);
    model.off("change:config_path", redraw);
  };
}

export default { render };
