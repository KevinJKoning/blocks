// views.js: the views of an app's own plugins, in sandboxed frames, and the bridge requests they make.

// ------------------------------------------------------------------ views
// A view (plugin.yaml `views:`, docs/plugins.md) runs in a sandboxed srcdoc frame: opaque
// origin, the page's CSP inherited plus the view's own narrower one (both built by
// build.py). A frame reaches the app only through the port handed to view-bridge.js, and
// every request is checked against what the view declared (reads, can). A view is shown in
// the Data modal, or on the report's page of the overview, a group or a node. A view that
// reads datasets is there before any run (with DuckDB, confined to them); one that reads
// nodes' outputs once they have run.
const views = manifest.views || {};
const VIEW_READ_MAX = 64 * 2 ** 20;
const frames = {};   // name -> {wrap, frame, port, t0, sent: number of the last state sent}
let viewSeq = 0;
const viewState = Object.fromEntries(Object.keys(views).map((n) => [n,
  { status: "not mounted", ms: null, rendered: 0, settled: false, summary: null, describe: null, errors: [], violations: [] }]));
const END_SCRIPT = "<" + "/script>", END_STYLE = "<" + "/style>";   // this file is itself inline
const attr = (s) => String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
function viewDoc(name) {
  const v = views[name], t = currentTheme();
  return `<!doctype html><html data-theme="${attr(t.name)}" data-mode="${attr(t.mode)}"><head>` +
    `<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${attr(v.csp)}">` +
    ["proto/themes.css", "proto/view-base.css", ...v.css].map((p) => `<style>${textOf(p)}${END_STYLE}`).join("") +
    `</head><body><div id="view"></div>` +
    ["proto/view-bridge.js", ...v.code].map((p) => `<script>${textOf(p)}${END_SCRIPT}`).join("") + "</body></html>";
}
function viewSnapshot() {
  // Per node: its status and metrics (shown: "run", or "reference" while the viewer looks at
  // the reference run's results; compare: the reference has results for it). Per dataset:
  // its state, profile and schema check. reference and runs: the previous runs loaded.
  const r = reference(), now = headlineNow();
  return { nodes: Object.fromEntries(order.map((n) => [n, { status: state.node[n].status, cached: !!state.node[n].cached,
      shown: shownSide(n), compare: comparable(n), metrics: (shownRecord(n) || {}).metrics || {} }])),
    reference: r && r.name,
    runs: state.prev.map((x) => ({ name: x.name, app: x.doc.app, made: x.doc.made, headline: x.doc.headline || {}, settings: x.doc.settings || {} })),
    data: Object.fromEntries(manifest.datasets.map((d) => { const x = state.data[d.name] || {};
      const c = x.check && x.check.status === "done" ? { ok: x.check.result.ok, problems: schemaProblems(x.check.result) } : x.check ? { status: x.check.status } : null;
      return [d.name, { status: x.status || "waiting", original: x.original ?? null, file: x.file || null, path: d.at, profile: x.profile || null, schema: c }]; })),
    settings: { ...state.settings }, busy: !!state.busy, ready: state.ready && dataReady(),
    headline: headline.map((m) => ({ id: m.id, label: m.label, goal: m.goal, now: now[m.id], reference: r ? (r.doc.headline || {})[m.id] : undefined })) };
}
const integrityOk = () => !!state.integrity && !state.integrity.bad.length && !state.integrity.unavailable;
function mountView(name) {
  if (frames[name]) return frames[name].wrap;
  if (!integrityOk()) throw new Error("views are composed only after the integrity check passes");
  const v = views[name];
  const frame = h("iframe", { sandbox: "allow-scripts", title: v.title, class: "view-frame", "data-view": name });
  const f = frames[name] = { frame, port: null, t0: performance.now(), sent: 0,
    wrap: h("section", { class: "view", "data-view": name }, h("h3", {}, v.title), frame) };
  Object.assign(viewState[name], { status: "loading" });
  frame.addEventListener("load", () => {
    if (f.port) f.port.close();
    f.loads = (f.loads || 0) + 1;
    const ch = new MessageChannel();
    f.port = ch.port1;
    ch.port1.onmessage = (ev) => onViewMessage(name, ev.data || {});
    frame.contentWindow.postMessage({ type: "bridge-init" }, "*", [ch.port2]);
    f.sent = ++viewSeq;
    viewState[name].status = "loading";   // a reloaded frame must report ready again
    ch.port1.postMessage({ type: "init", seq: f.sent, theme: currentTheme(), state: viewSnapshot(),
      view: { name, title: v.title, at: v.at, reads: v.reads, can: v.can } });
  });
  frame.srcdoc = viewDoc(name);
  return f.wrap;
}
const viewSel = (v) => ({ kind: v.at.kind, name: v.at.target });
const viewHere = (v) => v.at.kind !== "data" && v.at.kind === state.sel.kind && (v.at.target || null) === (state.sel.name || null);
// A result view has something to show once every node it reads has run.
const viewCanShow = (v) => v.before_run || resultsAvailable(viewSel(v)) && v.reads.every((n) => ran(n));
function showReportViews() {
  if (!ui.viewSlot) return;
  for (const [name, v] of Object.entries(views)) {
    if (v.at.kind === "data") continue;
    const here = viewHere(v);
    if (here && !frames[name] && integrityOk() && viewCanShow(v)) ui.viewSlot.append(mountView(name));
    if (frames[name]) frames[name].wrap.hidden = !here;
  }
}
function mountDataViews() {
  if (!integrityOk()) return;
  for (const [name, v] of Object.entries(views)) if (v.at.kind === "data") modals.data.slot.append(mountView(name));
}
function onViewMessage(name, m) {
  const vs = viewState[name], f = frames[name];
  if (m.type === "ready") Object.assign(vs, { status: "ready", ms: Math.round(performance.now() - f.t0), summary: m.summary, rendered: Math.max(vs.rendered, m.seq || 0) });
  else if (m.type === "rendered") vs.rendered = Math.max(vs.rendered, m.seq || 0);
  else if (m.type === "describe") vs.describe = m.value;
  else if (m.type === "escape" && views[name].at.kind === "data") closeModal();   // Esc pressed inside the frame
  else if (m.type === "resize") f.frame.style.height = `${Math.max(40, Math.min(m.height, Math.round(innerHeight * 0.8)))}px`;
  else if (m.type === "error") { if (vs.errors.length < 50) vs.errors.push(String(m.message)); console.error(`[view ${name}]`, m.message); }
  else if (m.type === "violation") { if (vs.violations.length < 50) vs.violations.push(`${m.directive} ${m.blocked}`); console.error(`CSP-VIOLATION [view ${name}] ${m.directive} ${m.blocked}`); }
  else if (m.type === "request") {
    viewRequest(name, m.method, m.args || {}).then(
      (value) => f.port.postMessage({ type: "reply", id: m.id, ok: true, value }),
      (e) => f.port.postMessage({ type: "reply", id: m.id, ok: false, error: e.message || String(e) }));
  }
}
const NEEDS = { setSettings: "params", query: "query", download: "download" };
async function viewRequest(name, method, args) {
  const v = views[name];
  if (NEEDS[method] && !v.can.includes(NEEDS[method])) throw new Error(`view ${name} cannot ${method}: add '${NEEDS[method]}' to its can: in plugin.yaml`);
  // read(name): a node's output as JSON (a view of results), or a dataset's bytes (before a run).
  if (method === "read") {
    const what = String(args.name || "");
    if (!v.reads.includes(what)) throw new Error(`view ${name} may not read ${what}: not in its reads: in plugin.yaml`);
    if (!v.before_run) return readOutput(what);
    const bytes = await call("readBytes", { path: datasets[what].at });
    if (bytes.length > VIEW_READ_MAX) throw new Error(`${what} is ${fmtBytes(bytes.length)}, over the ${fmtBytes(VIEW_READ_MAX)} a view may read; query it`);
    return bytes;
  }
  if (method === "settings") return { values: { ...state.settings }, spec: settingSpec };
  if (method === "setSettings") {   // only Data modal views may (spec.read_views); a change runs as any change does
    const out = { warnings: await setSettings(args.values || {}) };
    refresh();
    return out;
  }
  // DuckDB itself confines a view's SQL to its declared reads (see Session.query).
  if (method === "query") return call("query", { sql: String(args.sql || ""), limit: Math.min(Number(args.limit) || 200, 5000), allow: v.paths });
  if (method === "download") { download(String(args.name || "download"), args.data, args.type); return { ok: true }; }
  throw new Error(`unknown request ${method}`);
}
let notifyQueued = false;
function notifyViews() {
  if (notifyQueued) return;
  notifyQueued = true;
  queueMicrotask(() => {
    notifyQueued = false;
    const st = viewSnapshot();
    for (const f of Object.values(frames)) if (f.port) { f.sent = ++viewSeq; f.port.postMessage({ type: "update", seq: f.sent, state: st }); }
  });
}
function themeViews() {
  for (const f of Object.values(frames)) if (f.port) f.port.postMessage({ type: "theme", theme: currentTheme() });
}
function viewList() {
  // settled: the view has drawn the latest state sent to it.
  return Object.entries(views).map(([n, v]) => ({ name: n, plugin: v.plugin, title: v.title, at: v.at, reads: v.reads, can: v.can,
    ...viewState[n], loads: frames[n] ? frames[n].loads || 0 : 0,
    settled: viewState[n].status === "ready" && !!frames[n] && viewState[n].rendered >= frames[n].sent }));
}
async function openView(name, timeoutMs = 15000) {
  const v = views[name];
  if (!v) throw new Error(`no view ${name} (have: ${Object.keys(views).join(", ") || "none"})`);
  if (!viewCanShow(v)) throw new Error(`view ${name} shows run results: run ${v.reads.join(", ")} first`);
  if (v.at.kind === "data") openModal("data"); else { closeModal(); select(viewSel(v)); }
  const t0 = performance.now();
  const settled = () => viewState[name].status === "ready" && frames[name] && viewState[name].rendered >= frames[name].sent;
  do await new Promise((r) => setTimeout(r, 50));   // lets a queued update reach the frame first
  while (!settled() && !viewState[name].errors.length && performance.now() - t0 < timeoutMs);
  return viewList().find((x) => x.name === name);
}
