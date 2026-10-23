// dag.js: the graph (laid out by pele), zoom and pan, and what the report shows.

// ------------------------------------------------------------------ DAG
// The graph is the report's table of contents: a node selects that node, a group's label
// its group, the background the app's overview. Every node shows its state from the start
// (○ not run), the data it reads (rows, size, the schema check) and the metrics its file
// declares (headline ones first), without values until it has run, then with Δ from the
// reference run. State is shown by the node's border, a light tint and a status line with
// a glyph (.dag [data-status] in app.css), never by colour alone.
const GLYPH = { done: "✓", stale: "↻", running: "…", error: "✕", blocked: "–", pending: "○" };
const NODE_STATUS = { done: "done", pending: "not run", stale: "stale", running: "running", error: "failed", blocked: "blocked" };
const nodeStatus = (n) => `${GLYPH[state.node[n].status] || ""} ${NODE_STATUS[state.node[n].status] || state.node[n].status}`;
const STATUS_VARIANTS = Object.values(NODE_STATUS).map((t) => `✓ ${t}`);
const lineReserve = new Map();
const VALUE_RESERVE = "-0.00000";
const METRIC_LINES = 3;
// A node's declared metrics (headline ones first) and, after a run, their values with the
// change from the reference run's.
function nodeMetrics(n) {
  const decl = declaredFor(n).sort((a, b) => b.headline - a.headline).slice(0, METRIC_LINES);
  const now = ran(n) ? state.node[n].metrics || {} : null;
  return decl.map((m) => {
    const v = now ? now[m.key] : undefined, c = now ? metricCell(n, m.key) : null;
    return [m, v, c && c.differs && c.delta !== null ? `(Δ ${signed(c.delta)})` : ""];
  });
}
function metricLine(m, v, suffix) {
  const text = `${m.label} ${typeof v === "number" ? fmt(v) : "—"}${suffix ? ` ${suffix}` : ""}`;
  lineReserve.set(text, [`${m.label} ${VALUE_RESERVE}`, `${m.label} ${VALUE_RESERVE} (Δ ${VALUE_RESERVE})`]);
  return text;
}
// The data a node reads: rows (or files) and size once loaded, then its schema check, each
// on its own line.
function dataLines(n) {
  const ds = nodeData(n);
  const lines = ds.map((d) => {
    const st = state.data[d.name] || {}, p = st.profile || {};
    if (st.status !== "mounted") return `${d.name} ${st.status === "converting" ? "converting…" : "not loaded"}`;
    return p.kind === "table" ? `${fmtCount(p.rows, "row")} · ${fmtBytes(st.size)}` : p.kind === "dir" ? `${fmtCount(p.files, "file")} · ${fmtBytes(p.bytes)}` : fmtBytes(st.size);
  });
  if (lines.length) lineReserve.set(lines[0], ["0,000,000 rows · 000.0 MB"]);
  const notes = ds.map((d) => schemaNote(d.name)).filter(Boolean).map((x) => x.text);
  notes.forEach((t) => lineReserve.set(t, ["checking schema…", "matches its schema", "00 schema problems"]));
  return [...lines, ...notes];
}
function stateLabel(n) {
  const s = state.node[n], text = nodeStatus(n).slice(2);
  if (s.status === "done") return `${text} · ${fmtSec(s.seconds)}`;
  return s.status === "blocked" && s.error ? `blocked: ${s.error}` : text;
}
const RANK = { error: 7, blocked: 6, running: 5, stale: 2, pending: 1, done: 0 };
function groupStatus(g) {
  return groups[g].nodes.map((n) => state.node[n].status).reduce((w, s) => (RANK[s] > RANK[w] ? s : w), "done");
}
// pele lays out and routes the graph from a Mermaid flowchart built from the nodes' inputs
// (groups become subgraphs). Ids are synthetic (s0…, g0…).
const peleIds = Object.fromEntries(order.map((n, i) => [n, `s${i}`]));
const groupIds = Object.fromEntries(groupNames.map((g, i) => [g, `g${i}`]));
const fromId = { ...Object.fromEntries(order.map((n) => [peleIds[n], { node: n }])), ...Object.fromEntries(groupNames.map((g) => [groupIds[g], { group: g }])) };
const mermaidText = (t) => String(t).replace(/["#<>&\[\]{}|]/g, (c) => `#${c.charCodeAt(0)};`);
function nodeLabel(n) {
  const status = nodeStatus(n);
  lineReserve.set(status, STATUS_VARIANTS);
  const lines = [`<b>${mermaidText(n)}</b>`, mermaidText(status)];
  for (const d of dataLines(n)) lines.push(mermaidText(d));
  for (const [m, v, suffix] of nodeMetrics(n)) lines.push(mermaidText(metricLine(m, v, suffix)));
  return lines.join("<br/>");
}
function mermaidSource() {
  const lines = ["flowchart TD"];
  const placed = new Set();
  for (const g of groupNames) {
    lines.push(`  subgraph ${groupIds[g]}["${mermaidText(g)}"]`);
    for (const n of groups[g].nodes) { lines.push(`    ${peleIds[n]}["${nodeLabel(n)}"]`); placed.add(n); }
    lines.push("  end");
  }
  for (const n of order) if (!placed.has(n)) lines.push(`  ${peleIds[n]}["${nodeLabel(n)}"]`);
  const seen = new Set();
  for (const e of graph.edges) {
    const key = `${peleIds[e.from]} --> ${peleIds[e.to]}`;
    if (!seen.has(key)) { seen.add(key); lines.push(`  ${key}`); }
  }
  return lines.join("\n");
}
const TITLE_PX = 13;
let measureCtx = null;
function measurer(family) {
  measureCtx = measureCtx || document.createElement("canvas").getContext("2d");
  const cache = new Map();
  return {
    width(text, size, style) {
      const bold = style & 1, mono = style & 4;
      const px = bold ? TITLE_PX : size;
      const font = `${bold ? 650 : 400} ${px}px ${mono ? getComputedStyle(document.body).getPropertyValue("--mono") : family}`;
      const one = (t) => {
        const key = font + "\u0000" + t;
        if (!cache.has(key)) { measureCtx.font = font; cache.set(key, measureCtx.measureText(t).width); }
        return cache.get(key);
      };
      return Math.max(one(text), ...(lineReserve.get(text) || []).map(one));
    },
  };
}
function importWithoutStyleAttrs(svgText) {
  // The CSP forbids inline style attributes, so rename them before parsing and
  // re-apply them through CSSOM, which CSP allows. pele escapes attribute values.
  const doc = new DOMParser().parseFromString(svgText.replace(/ style="([^"]*)"/g, ' data-cx-style="$1"'), "image/svg+xml");
  const svg = document.importNode(doc.documentElement, true);
  for (const el of [svg, ...svg.querySelectorAll("[data-cx-style]")]) {
    const css = el.getAttribute("data-cx-style");
    if (css === null) continue;
    for (const decl of css.split(";")) {
      const at = decl.indexOf(":");
      if (at > 0) el.style.setProperty(decl.slice(0, at).trim(), decl.slice(at + 1).trim());
    }
    el.removeAttribute("data-cx-style");
  }
  return svg;
}
function activate(el, label, fn) {
  el.setAttribute("tabindex", "0");
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", label);
  el.addEventListener("click", (ev) => { ev.stopPropagation(); fn(); });
  el.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); } });
}
const isSelected = (kind, name) => state.sel.kind === kind && state.sel.name === name;
function renderGraphPele() {
  const family = getComputedStyle(document.body).fontFamily;
  const r = window.pele.render(mermaidSource(), { fontSize: 11, fontFamily: family, measurer: measurer(family), links: false, images: false, padding: 8 });
  const svg = importWithoutStyleAttrs(r.svg);
  svg.classList.add("dag", "dag-pele");
  svg.setAttribute("aria-label", "Nodes: the report's contents");
  for (const g of svg.querySelectorAll("g.pele-node[data-id]")) {
    const ref = fromId[g.getAttribute("data-id")];
    if (!ref || !ref.node) continue;
    const n = ref.node;
    g.classList.add("node");
    const first_ = g.querySelector(".pele-label tspan");
    if (first_) { first_.classList.add("title"); first_.setAttribute("y", Number(first_.getAttribute("y")) - 1.5); }
    g.querySelectorAll(".pele-label tspan").forEach((t, i) => { if (i === 1) t.classList.add("status"); if (i > 1) t.classList.add("metric"); });
    if (isSelected("node", n)) g.classList.add("selected");
    g.setAttribute("data-node", n);
    g.setAttribute("data-status", state.node[n].status);
    g.prepend(h("svg:title", {}, nodes[n].desc || n));
    activate(g, `Node ${n}: ${stateLabel(n)}`, () => select({ kind: "node", name: n }));
  }
  for (const c of svg.querySelectorAll("g.pele-cluster[data-id]")) {
    const ref = fromId[c.getAttribute("data-id")];
    if (!ref || !ref.group) continue;
    c.setAttribute("data-group", ref.group);
    c.setAttribute("data-status", groupStatus(ref.group));
    if (isSelected("group", ref.group)) c.classList.add("selected");
    const label = c.querySelector(".pele-cluster-label");
    if (label) activate(label, `Group ${ref.group}`, () => select({ kind: "group", name: ref.group }));
  }
  for (const e of svg.querySelectorAll("g.pele-edge[data-id]")) {
    const m = e.getAttribute("data-id").match(/^L_(s\d+)_(s\d+)_/);
    if (m && state.sel.kind === "node" && [m[1], m[2]].some((id) => fromId[id] && fromId[id].node === state.sel.name)) e.classList.add("active");
  }
  placeDrawing(svg, r.width, r.height);
}
// Zoom: "fit" scales the drawing down to the pane (never below MIN_FIT); manual zoom is a factor.
const MIN_FIT = 0.65, MIN_ZOOM = 0.25, MAX_ZOOM = 3;
state.zoom = "fit";
function fitFactor(w, hgt) {
  const cs = getComputedStyle(ui.graph);
  const availW = ui.graph.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const availH = ui.graph.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  if (!(availW > 0 && availH > 0)) return 1;
  return Math.max(MIN_FIT, Math.min(1, availW / w, availH / hgt));
}
function placeDrawing(svg, w, hgt) {
  const g = ui.graph, left = g.scrollLeft, top = g.scrollTop;
  ui.drawing = { svg, w, h: hgt };
  sizeDrawing();
  g.replaceChildren(svg);
  g.scrollLeft = left;
  g.scrollTop = top;
  refreshZoomUi();
}
function sizeDrawing() {
  const d = ui.drawing, k = currentZoom();
  d.svg.style.setProperty("max-width", "none");
  d.svg.setAttribute("width", (d.w * k).toFixed(1));
  d.svg.setAttribute("height", (d.h * k).toFixed(1));
}
function refreshZoomUi() {
  const g = ui.graph;
  g.classList.toggle("pannable", g.scrollWidth > g.clientWidth + 1 || g.scrollHeight > g.clientHeight + 1);
  if (ui.zoomLabel) ui.zoomLabel.textContent = state.zoom === "fit" ? "Fit" : `${Math.round(currentZoom() * 100)}%`;
}
function currentZoom() {
  const d = ui.drawing;
  return !d ? 1 : state.zoom === "fit" ? fitFactor(d.w, d.h) : state.zoom;
}
function applyZoom(anchor) {
  const d = ui.drawing;
  if (!d) return;
  const g = ui.graph;
  const box = g.getBoundingClientRect();
  const ax = anchor ? anchor.x - box.left : g.clientWidth / 2, ay = anchor ? anchor.y - box.top : g.clientHeight / 2;
  const sb = d.svg.getBoundingClientRect();
  const fx = sb.width ? (anchor ? anchor.x : box.left + ax) - sb.left : 0, fy = sb.height ? (anchor ? anchor.y : box.top + ay) - sb.top : 0;
  const before = sb.width || 0;
  const k = currentZoom();
  sizeDrawing();
  if (before) {
    const r = (d.w * k) / before;
    const sb2 = d.svg.getBoundingClientRect();
    g.scrollLeft += (sb2.left + fx * r) - (box.left + ax);
    g.scrollTop += (sb2.top + fy * r) - (box.top + ay);
  }
  refreshZoomUi();
}
function zoomBy(f, anchor) {
  state.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, currentZoom() * f));
  applyZoom(anchor);
}
// Drag to pan; a drag never also counts as a click on a node.
function enablePan(el) {
  let start = null, panned = false;
  el.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 || !el.classList.contains("pannable")) return;
    start = { x: ev.clientX, y: ev.clientY, left: el.scrollLeft, top: el.scrollTop, id: ev.pointerId };
    panned = false;
  });
  el.addEventListener("pointermove", (ev) => {
    if (!start || ev.pointerId !== start.id) return;
    const dx = ev.clientX - start.x, dy = ev.clientY - start.y;
    if (!panned && Math.hypot(dx, dy) < 4) return;
    if (!panned) { panned = true; el.classList.add("panning"); el.setPointerCapture(ev.pointerId); }
    el.scrollLeft = start.left - dx;
    el.scrollTop = start.top - dy;
  });
  const end = (ev) => {
    if (!start || ev.pointerId !== start.id) return;
    if (panned) {
      el.classList.remove("panning");
      const swallow = (e) => { e.stopPropagation(); e.preventDefault(); };
      el.addEventListener("click", swallow, { capture: true, once: true });
      setTimeout(() => el.removeEventListener("click", swallow, { capture: true }), 0);
    }
    start = null;
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}
function renderGraph() {
  if (!ui.graph) return;
  try { renderGraphPele(); } catch (e) {
    ui.graph.replaceChildren(h("pre", { class: "log" }, `The graph could not be drawn: ${e.message}`));
    ui.drawing = null;
  }
}
// Show the overview, the runs, a group or a node in the report. Choosing one opens the report if it
// is hidden (open: false keeps it as it is).
function select(sel, open = true) {
  const s = sel && sel.kind ? sel : { kind: "overview" };
  if (s.kind === "node" && !(s.name in nodes)) throw new Error(`no node ${s.name}`);
  if (!["overview", "runs", "group", "node"].includes(s.kind)) throw new Error(`no page ${s.kind}`);
  if (s.kind === "group" && !(s.name in groups)) throw new Error(`no group ${s.name}`);
  state.sel = { kind: s.kind, name: ["overview", "runs"].includes(s.kind) ? null : s.name };
  if (open && !state.reportShown && ui.body) setReportShown(true);
  renderGraph(); renderReport();
  if (ui.report) ui.report.scrollTop = 0;
}
