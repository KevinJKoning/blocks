// modals.js: the header's Data, Settings and Download modals.

// ------------------------------------------------------------------ modals
// Data: the datasets (swap a file to run on other data); runs have their own page
// (runs.js). Settings: two sections, Graph (every node's settings, in graph
// order; each node's are also live on its page) and App (theme, report, plugins,
// earlier versions, this build). Each is a <dialog> that is only
// opened and closed, never moved, so the views in it keep their state. Data opens by
// itself while data is missing.
const modals = {
  data: { label: "Data", title: "Data", render: renderData },
  settings: { label: "Settings", title: "Settings", render: renderSettings },
  download: { label: "Download", title: "Download", render: renderDownload },   // downloads.js
};
state.settingsTab = "graph";
function buildModals() {
  for (const [name, m] of Object.entries(modals)) {
    m.top = h("div", {});
    m.slot = h("div", { class: "view-slot" });   // this modal's views, after the integrity check
    m.rest = h("div", {});
    m.note = h("span", { class: "small muted grow" });
    m.dialog = h("dialog", { class: "modal", "data-modal": name, "aria-label": m.title },
      h("header", { class: "modal-head" }, h("h2", {}, m.title),
        h("button", { class: "btn link", "data-action": "close-modal", "aria-label": "Close", onclick: closeModal }, "✕")),
      h("div", { class: "modal-body" }, m.top, m.slot, m.rest),
      h("footer", { class: "modal-foot" }, m.note, h("button", { class: "cap primary", "data-action": "done", onclick: closeModal }, "Done")));
    m.dialog.addEventListener("click", (e) => { if (e.target === m.dialog) closeModal(); });   // the backdrop
    document.body.append(m.dialog);
  }
  renderModals();
}
function renderModals() {
  for (const m of Object.values(modals)) {
    if (!m.dialog) continue;
    const top = h("div", {}), rest = h("div", {});
    m.render(top, rest, m);
    m.top.replaceChildren(top);
    m.rest.replaceChildren(rest);
  }
}
const openModalName = () => Object.keys(modals).find((n) => modals[n].dialog && modals[n].dialog.open) || null;
// at: a node whose settings to scroll to (Settings), or "app" (Settings > App).
function openModal(name, at) {
  const m = modals[name];
  if (!m || !m.dialog) return;
  if (name === "settings" && at) { state.settingsTab = at === "app" ? "app" : "graph"; renderModals(); }
  if (openModalName() !== name) { closeModal(); m.dialog.showModal(); }
  const el = at && at !== "app" && m.dialog.querySelector(`[data-node-group="${CSS.escape(at)}"]`);
  if (el) el.scrollIntoView({ block: "start" });
}
function closeModal() {
  for (const m of Object.values(modals)) if (m.dialog && m.dialog.open) m.dialog.close();
}
const startNote = () => state.fatal ? "The runtime failed to start." : !state.ready ? "Starting the Python runtime…"
  : !dataReady() ? "Provide the data, then press Run." : state.hasRun ? "" : "Press Run to run the graph.";
function renderData(top, rest, m) {
  put(top, h("p", { class: "small muted" }, "The data the nodes read. Swap a file to run on other data."));
  put(top, manifest.datasets.map(dataControl));
  m.note.textContent = startNote();
}
function renderSettings(top, rest, m) {
  const tab = state.settingsTab;
  const seg = (id, label) => h("button", { role: "tab", class: "tab", "data-settings-tab": id, "aria-selected": String(tab === id),
    onclick: () => { state.settingsTab = id; renderModals(); } }, label);
  put(top, h("div", { class: "tabs", role: "tablist", "aria-label": "Settings" }, seg("graph", "Graph"), seg("app", "App")));
  if (tab === "graph") graphSettings(top, rest, m); else appSettings(top, rest, m);
}
function graphSettings(top, rest, m) {
  const withSettings = order.filter((n) => nodeSettings(n).length);
  if (!withSettings.length) { put(top, h("p", { class: "small muted" }, "No node has settings (keyword-only parameters).")); m.note.textContent = ""; return; }
  put(top, h("p", { class: "small muted" }, "A node's settings are its keyword-only parameters. Changing one makes that node and what depends on it stale;" +
    " Run runs them again."));
  for (const n of withSettings) put(top, h("section", { class: "settings-group", "data-node-group": n },
    h("h3", {}, n), nodes[n].desc ? h("p", { class: "small muted" }, nodes[n].desc) : null, nodeSettings(n).map(paramControl)));
  const changed = Object.keys(changedSettings()).length;
  m.note.textContent = changed ? `${changed} setting${changed > 1 ? "s" : ""} changed from the defaults.` : "All settings at their defaults.";
  if (!atDefaults()) put(rest, h("button", { class: "btn", "data-action": "reset", onclick: async () => { await resetAll(); refresh(); } }, "Reset settings and data to defaults"));
}
function appSettings(top, rest, m) {
  put(top, h("section", { class: "settings-group" }, h("h3", {}, "Appearance"),
    h("div", { class: "row-line" }, h("span", { class: "grow" }, "Theme"), themePicker()),
    h("div", { class: "row-line" }, h("span", { class: "grow" }, "Show the report beside the graph"),
      h("input", { type: "checkbox", "data-action": "report-shown", checked: !!state.reportShown, onchange: (e) => setReportShown(e.target.checked) }))));
  put(top, h("section", { class: "settings-group" }, h("h3", {}, "Plugins"),
    (manifest.plugins || []).length ? h("ul", { class: "plugins" }, manifest.plugins.map((p) => h("li", { "data-plugin": p.name },
      h("strong", {}, p.title), h("span", { class: "muted small" }, ` ${p.name} · ${p.builtin ? "built-in" : "this app's"}`,
        [...p.formats.map((f) => ` · format ${f}`), ...p.views.map((v) => ` · view ${v}`)].join("")),
      p.description ? h("div", { class: "small" }, inline(p.description)) : null)))
      : h("p", { class: "small muted" }, "None: this app uses only the core (charts, comparing runs and schemas are built in).")));
  if (manifest.superseded && manifest.superseded.length) put(top, h("section", { class: "settings-group" }, h("h3", {}, "Earlier versions"),
    h("p", { class: "small muted" }, "Superseded versions of this app, served for comparison (export a run there, load it here under Data)."),
    h("ul", { class: "files" }, manifest.superseded.map((s) => h("li", {}, h("a", { href: s.url }, s.name))))));
  put(rest, h("details", { class: "about" }, h("summary", {}, "About this build"), about()));
  m.note.textContent = "";
}

// ---- settings and data controls
let paramSeq = 0;
function paramControl(key) {
  const s = settingSpec[key] || {};
  const val = state.settings[key];
  const check = validate(key, val);
  const changed = !same(val, defaults[key]);
  const hint = h("div", { class: `hint${check.level === "warn" ? " warn" : ""}` },
    `default ${fmt(defaults[key])}`, check.text ? ` · ${check.text}` : null, s.note ? ` · ${s.note}` : null);
  const apply = async (v) => {
    try { await setSettings({ [key]: v }); } catch (e) { hint.textContent = e.message; return; }
    refresh();
  };
  const id = `p-${++paramSeq}`;   // a setting shows in Settings and on its node's page
  const row = h("div", { class: "row" }, h("label", { class: "key", for: id }, key));
  const wrap = h("div", { class: `param${changed ? " changed" : ""}`, "data-param": key }, row);
  if (s.choices) {
    const opts = s.choices.some((o) => same(o, val)) ? s.choices : [...s.choices, val];
    row.append(h("select", { id, class: "choice", onchange: (e) => apply(opts[Number(e.target.value)]) },
      opts.map((o, i) => h("option", { value: String(i), selected: same(o, val) }, fmt(o)))));
  } else if (typeof defaults[key] === "boolean") {
    row.append(h("input", { id, type: "checkbox", checked: val, onchange: (e) => apply(e.target.checked) }));
  } else if (typeof defaults[key] === "number") {
    const num = h("input", { id, type: "number", value: val, step: s.step || "any", onchange: (e) => apply(Number(e.target.value)) });
    row.append(num);
    if ("min" in s && "max" in s) {
      const log = s.scale === "log" && s.min > 0;
      const toS = (v) => log ? Math.log10(v) : v, fromS = (v) => log ? Number((10 ** v).toPrecision(3)) : v;
      wrap.append(h("input", { type: "range", "aria-label": `${key} slider`, min: toS(s.min), max: toS(s.max),
        step: log ? (toS(s.max) - toS(s.min)) / 100 : (s.step || (s.max - s.min) / 100), value: toS(val),
        oninput: (e) => { num.value = fromS(Number(e.target.value)); }, onchange: (e) => apply(fromS(Number(e.target.value))) }));
    }
  } else if (typeof defaults[key] === "object" && defaults[key] !== null) {
    row.append(h("input", { id, type: "text", class: "json", value: JSON.stringify(val), spellcheck: false,
      onchange: (e) => { let v; try { v = JSON.parse(e.target.value); } catch { hint.textContent = "not valid JSON"; hint.className = "hint warn"; return; } apply(v); } }));
  } else {
    row.append(h("input", { id, type: "text", value: val, onchange: (e) => apply(e.target.value) }));
  }
  wrap.append(hint);
  return wrap;
}

const INGEST_PHASE = { starting: "Starting the converter", reading: "Reading the file's index", loading: "Loading the converter's packages",
  opening: "Opening the data", converting: "Converting", done: "Finishing" };
function ingestStatus(d, st) {
  const job = st.progress || {};
  const counted = job.phase === "converting" || job.phase === "done";
  return h("div", { class: "ingest", "data-ingest": d.name },
    h("progress", { max: counted ? Math.max(job.total, 1) : 1, value: counted ? job.done : undefined, "aria-label": `Converting ${d.name}` }),
    h("div", { class: "small" }, `${INGEST_PHASE[job.phase] || job.phase}${job.phase === "loading" ? ` (${d.adapter.packages.join(", ")})` : ""}…`,
      counted && job.total ? ` ${job.done.toLocaleString("en-US")} of ${job.total.toLocaleString("en-US")} ${job.unit}` : null,
      job.eta != null ? h("span", { class: "muted" }, ` · about ${fmtEta(Math.max(job.eta, 0))} left`) : null),
    h("button", { class: "btn", "data-action": "cancel-ingest", onclick: () => cancelIngest(d.name) }, "Cancel"));
}
function dataControl(d) {
  const st = state.data[d.name] || { status: "waiting" };
  const msg = h("div", { class: `small ${st.status === "error" || (st.status === "mounted" && !st.original) ? "hint warn" : "muted"}` },
    st.status === "converting" ? null : dataStatus(d), st.status === "mounted" && st.profile ? [" · ", profileFacts(st.profile)] : null,
    st.note && st.status === "mounted" ? ` · ${st.note}` : null);
  const file = h("input", { type: "file", hidden: true, "aria-label": `File for ${d.name}`,
    onchange: async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try { await provideFile(d.name, f); } catch (err) { msg.textContent = `Not loaded: ${err.message}`; msg.className = "small hint warn"; }
    } });
  const readers = nodesReading(d);
  return h("div", { class: "drop", "data-dataset": d.name },
    h("span", { class: "mono" }, d.name, h("span", { class: "muted" }, ` → ${d.targets.join(", ")}`)),
    d.kind === "file" ? h("button", { class: "btn", "data-action": "provide", onclick: () => file.click() }, st.status === "mounted" ? "Swap…" : "Choose file…") : null,
    st.status === "mounted" && !st.original && d.source !== "user" ? h("button", { class: "btn", onclick: () => restoreData(d.name) }, "Restore") : null,
    file, d.desc ? h("div", { class: "small" }, d.desc) : null, msg,
    readers.length ? h("div", { class: "small" }, "Details: ", readers.map((n, i) => [i ? ", " : "",
      h("button", { class: "btn link", onclick: () => { closeModal(); select({ kind: "node", name: n }); } }, n)])) : null,
    st.status === "converting" ? ingestStatus(d, st) : null);
}

function about() {
  const rt = manifest.runtime;
  const rows = [
    ["app", manifest.id + (manifest.version ? " (superseded)" : "")],
    ["build", linked ? "linked: runtime and data from the dev server" : "offline: everything embedded, no network"],
    ["built", manifest.built],
    ["code", manifest.code_sha.slice(0, 12)],
    ["runtime", `Pyodide ${rt.pyodide} (CPython ${state.python || rt.python})` + (state.timings ? ` · started in ${state.timings.total.toFixed(1)} s` : "")],
    ["packages", Object.entries(rt.packages).map(([n, v]) => `${n} ${v}`).join(", ")],
    ["integrity", !state.integrity ? "checking…" : state.integrity.bad.length ? `${state.integrity.bad.length} component(s) do not match the manifest` : `all ${state.integrity.ok} components match their SHA-256`],
  ];
  return h("div", {}, h("table", { class: "kv" }, h("tbody", {}, rows.map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, v))))),
    h("details", {}, h("summary", {}, "Content-Security-Policy"), h("pre", { class: "log" }, manifest.csp.split("; ").join(";\n"))),
    h("details", {}, h("summary", {}, "For software agents"),
      h("p", { class: "small" }, navigator.modelContext ? "WebMCP tools are registered on navigator.modelContext; " : "WebMCP is not available in this browser; ",
        "the same tools are callable as window.blocksApp.tools.<name>(args):"),
      h("ul", { class: "small" }, tools.map((t) => h("li", {}, h("code", {}, t.name), ` — ${t.description}`)))));
}
