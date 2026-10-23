// blocks.js: every report page is a list of blocks, drawn here (docs/blocks.md).
//
// A page's blocks come with it (blocktool/docs.py), and some are live: a dataset's state
// and check, the settings as controls, and a node's results, which are the blocks its
// view(out) made of its output (blocks.ui). A block of a node's results also shows the
// reference run's block with the same node and id, where that means something: metrics
// add its values and Δ, charts draw its series dashed underneath.

// ctx: {node, side}: the node the blocks belong to, and which run they come from.
function renderBlocks(list, ctx = {}) {
  return list.map((b) => {
    const draw = BLOCKS[b.type];
    let body;
    try { body = draw ? draw(b, ctx) : h("p", { class: "small muted" }, `(a ${b.type} block, which this page does not draw)`); }
    catch (e) { body = h("p", { class: "small problem" }, `${b.type} block: ${e.message}`); console.error(e); }
    return body === null ? null : h("section", { class: `block block-${b.type}`, "data-block": b.type, "data-id": b.id || null },
      b.title && b.type !== "fold" ? h("h3", {}, b.title) : null, body);
  });
}
// The reference's version of a block of this run (same node, same id), or null.
const refOf = (b, ctx) => ctx.node && ctx.side === "run" && comparable(ctx.node) ? refBlock(ctx.node, b.id) : null;

const BLOCKS = {
  markdown: (b) => h("div", { class: "doc", "data-doc": b.doc || null }, markdown(b.text)),
  metrics: (b, ctx) => metricsTable(b, refOf(b, ctx), ctx),
  table: (b) => tableOf(b.columns, b.rows, b.total),
  chart: (b, ctx) => { const ref = refOf(b, ctx); return chart(b, ref, ref && reference().name); },
  data: (b) => fileCard(b),
  figure: (b) => h("figure", { class: "figure" }, h("img", { src: b.media === "image/svg+xml" ? URL.createObjectURL(new Blob([b.data], { type: b.media }))
    : imageFromBase64(b.data, b.media), alt: b.caption || "figure" }), b.caption ? h("figcaption", { class: "small" }, b.caption) : null),
  // the page's own, filled with what only the page knows
  results: (b, ctx) => nodeResults(ctx.node, ctx),
  fold: (b, ctx) => h("details", { class: "fold about", "data-fold": b.id, open: !!state.open[b.id],
    ontoggle: (e) => { state.open[b.id] = e.target.open; } }, h("summary", {}, b.title), renderBlocks(b.blocks, ctx)),
  dataset: (b) => b.brief ? dataBrief(datasets[b.dataset]) : dataCard(datasets[b.dataset]),
  settings: (b) => h("div", { class: "settings-inline" }, b.keys.map(paramControl)),
  links: (b) => h("ul", { class: "files" }, b.items.map((it) => h("li", {},
    it.node ? nodeLink(it.node) : h("span", { class: "mono" }, it.dataset),
    h("span", { class: "size" }, it.node ? nodes[it.node].desc || "" : `dataset · ${datasets[it.dataset].at}`)))),
  code: (b) => { const text = has(`project/${b.path}`) ? textOf(`project/${b.path}`) : null;
    return text !== null ? h("details", { class: "fold" }, h("summary", {}, b.path), h("pre", { class: "src" }, text)) : null; },
  contents: (b) => contentsList(b.nodes),
  // the overview's and a group's, made from this session's state
  headline: () => headline.length ? headlineTable() : null,
  changes: () => reference() && state.cmp ? changesLine(reference()) : null,
  runs: () => runsTable(),
  nodes: (b) => nodesTable(b.nodes),
  // a block of a node's results, shown on another page (app.yaml overview:)
  pick: (b) => { const rec = state.node[b.node], blk = rec && rec.blocks && rec.blocks.find((x) => x.id === b.block);
    if (!blk) return null;
    const draw = BLOCKS[blk.type], ctx = { node: b.node, side: shownSide(b.node) };
    return h("div", {}, blk.title ? h("h3", {}, blk.title, " ", h("span", { class: "muted small" }, "from "), nodeLink(b.node)) : null, draw(blk, ctx)); },
};
const imageFromBase64 = (data, media) => URL.createObjectURL(new Blob([fromBase64(data)], { type: media }));
const tableOf = (columns, rows, total) => h("div", { class: "runs-wrap" }, h("table", { class: "kv small" },
  h("thead", {}, h("tr", {}, columns.map((c) => h("th", {}, c)))),
  h("tbody", {}, rows.map((r) => h("tr", {}, r.map((x) => h("td", { class: typeof x === "number" ? "num" : null }, fmt(x))))))),
  total > rows.length ? h("p", { class: "small muted" }, `${(total - rows.length).toLocaleString("en-US")} more rows`) : null);

// ---- metrics
// What the node declares first; when it declares some, the other numbers its output holds
// are folded under "Other metrics". Next to the reference's block, each item's cell from
// the comparison (blocks.runs).
function metricsTable(b, ref, ctx) {
  if (!b.items.length) return h("p", { class: "muted small" }, "No metrics.");
  const table = (items) => h("table", { class: "kv metrics" }, h("thead", {}, h("tr", {}, h("th", {}, "metric"),
    h("th", { class: "num" }, ctx.side === "reference" ? reference().name : "this run"),
    ref ? [h("th", { class: "num" }, runLabel_(reference())), h("th", { class: "num" }, "Δ")] : null)),
    h("tbody", {}, items.map((it) => { const c = ref ? blockCell(ctx.node, b.id, it.key) : null;
      return h("tr", { "data-metric": it.key, class: it.undeclared ? "undeclared" : null },
        h("td", { title: it.key }, it.label), h("td", { class: "num" }, fmt(it.value)),
        ref ? [h("td", { class: "num" }, fmt(c ? c.ref : undefined)), deltaCell(c)] : null); })));
  const main = b.items.filter((it) => !it.undeclared), rest = b.items.filter((it) => it.undeclared);
  if (!main.length || !rest.length) return table(b.items);
  return [table(main), h("details", { class: "fold" }, h("summary", {}, `Other metrics (${rest.length})`), table(rest))];
}
// A comparison cell (blocks.runs.cell) as Δ: "=" within the tolerance, else the change,
// coloured better or worse by the metric's goal when it has one.
function deltaCell(c) {
  if (!c || (!c.differs && c.delta === null)) return h("td", { class: "num" }, "");
  if (!c.differs) return h("td", { class: "num delta same" }, "=");
  if (c.delta === null) return h("td", { class: "num delta changed" }, "≠");
  return h("td", { class: `num delta ${c.better === null ? "changed" : c.better ? "better" : "worse"}` }, signed(c.delta));
}
function headlineTable() {
  const now = headlineNow(), r = reference();
  return h("table", { class: "kv headline" }, h("thead", {}, h("tr", {}, h("th", {}, "headline"), h("th", { class: "num" }, "this run"),
    r ? [h("th", { class: "num" }, runLabel_(r)), h("th", { class: "num" }, "Δ")] : null, h("th", { class: "num" }, "goal"))),
    h("tbody", {}, headline.map((m) => { const c = headlineCell(m.id);
      return h("tr", { "data-headline": m.id }, h("td", {}, m.label), h("td", { class: "num" }, fmt(now[m.id])),
        r ? [h("td", { class: "num" }, fmt(c ? c.ref : (r.doc.headline || {})[m.id])), deltaCell(c)] : null, h("td", { class: "num small muted" }, m.goal)); })));
}
// Every run, newest first: where it comes from, what differs from the reference, its
// headline metrics (the best of each marked), and a button to set its settings. The
// comparisons are the worker's (blocks.runs.summarize).
const RUN_FROM = { session: "this session", log: "run log", app: "shipped with the app", file: "loaded file" };
function runsTable() {
  if (!state.runs.length) return h("p", { class: "small muted" }, "No runs yet. Every run that computes something is kept here", linked ? " (and in runs.jsonl on the dev server)." : ".");
  const sum = state.summary || { rows: [], best: {} }, ref = reference();
  const rowOf = Object.fromEntries(sum.rows.map((r) => [r.name, r]));
  const runs = [...state.runs].sort((a, b) => String(b.doc.made).localeCompare(String(a.doc.made)));
  return h("div", { class: "runs-wrap" }, h("table", { class: "kv runs" },
    h("thead", {}, h("tr", {}, h("th", {}, "run"), h("th", {}, ref ? `changed from ${ref.name}` : "changed"),
      headline.map((m) => h("th", { class: "num", title: `${m.id} (${m.goal})` }, m.label)), h("th", { class: "num" }, "time"), h("th", {}, ""))),
    h("tbody", {}, runs.slice(0, 200).map((r) => { const row = rowOf[r.name] || { changes: [] };
      return h("tr", { "data-run": r.name, class: r === ref ? "reference" : null },
        h("td", { class: "small" }, h("span", { class: "mono" }, r.name), h("div", { class: "muted" }, RUN_FROM[r.from] || r.from, r === ref ? " · reference" : "")),
        h("td", { class: "small mono" }, r === ref ? "" : row.changes.length ? row.changes.map(changeText).join("; ") : h("span", { class: "muted" }, "nothing")),
        headline.map((m) => h("td", { class: `num${sum.best[m.id] === r.name ? " best" : ""}` }, fmt((r.doc.headline || {})[m.id]))),
        h("td", { class: "num" }, fmtSec(r.doc.seconds)),
        h("td", {}, h("button", { class: "btn link", title: "Set these settings", onclick: () => applyRun(r.name) }, "apply"))); }))),
    linked ? null : h("button", { class: "btn", onclick: () => download(`${manifest.name}-runs.json`,
      JSON.stringify(state.runs.filter((r) => r.from === "session").map((r) => r.doc), null, 1), "application/json") }, "Export this session's runs (.json)"));
}
function nodesTable(names) {
  return h("table", { class: "kv group-results" }, h("thead", {}, h("tr", {}, h("th", {}, "node"), h("th", {}, "state"), h("th", {}, "metrics"))),
    h("tbody", {}, names.map((n) => h("tr", { "data-node": n }, h("td", {}, nodeLink(n), nodes[n].desc ? h("div", { class: "small muted" }, nodes[n].desc) : null),
      h("td", {}, h("span", { class: `pill ${state.node[n].status}` }, stateLabel(n))),
      h("td", { class: "small" }, declaredFor(n).map((m) => h("div", {}, `${m.label} `, h("span", { class: "mono" }, fmt(ran(n) ? metricValue(state.node[n], m) : undefined)))))))));
}

// ---- data
const fmtEta = (s) => s == null || !isFinite(s) ? "" : s < 1 ? "under a second" : s < 90 ? `${Math.ceil(s)} s` : `${Math.round(s / 60)} min`;
function dataNeeded(d) {
  if (!d.format) return `needed: ${d.files[0].rel}, ${fmtBytes(d.size)}`;
  const e = d.estimate || {};
  return `needed: ${d.files[0].rel} (${fmtBytes(d.size)}), ${d.adapter.describe}` +
    `${e.total ? ` (${e.total.toLocaleString("en-US")} ${e.unit})` : ""}, about ${fmtEta(estimateSeconds(d))}`;
}
function dataStatus(d) {
  const st = state.data[d.name] || { status: "waiting" };
  const where = { server: "dev server", embedded: "embedded in this file", user: "provided by you", file: "your file" }[st.source || d.source];
  const how = d.format && st.status === "mounted"
    ? ` · ${st.rows != null ? `${st.rows.toLocaleString("en-US")} ${d.adapter.unit}, ` : ""}${st.cached ? "converted earlier (cached)" : `converted in ${fmtSec(st.seconds)}${st.store === "opfs" ? ", cached for next time" : ""}`}` : "";
  return st.status === "mounted" ? (st.original ? `original · ${fmtBytes(st.size)} · ${where}${how}` : `swapped for ${st.file} (${fmtBytes(st.size)})${how}`)
    : st.status === "loading" ? "loading…" : st.status === "converting" ? "converting…" : st.status === "error" ? `not loaded: ${st.note}`
      : `${st.note === "conversion cancelled" ? "conversion cancelled; " : ""}${dataNeeded(d)}`;
}
// What a file holds: rows and columns of a table, files of a directory, else its size.
function profileFacts(p) {
  if (!p) return null;
  if (p.error && p.kind !== "file") return h("span", { class: "muted" }, `not profiled: ${p.error}`);
  if (p.kind === "table") return `${fmtCount(p.rows, "row")} · ${fmtCount(p.columns.length, "column")}`;
  if (p.kind === "dir") return `${fmtCount(p.files, "file")} · ${fmtBytes(p.bytes)}`;
  if (p.kind === "missing") return "not produced";
  return fmtBytes(p.bytes);
}
const columnsTable = (cols) => h("table", { class: "kv cols" }, h("thead", {}, h("tr", {}, h("th", {}, "column"), h("th", {}, "type"))),
  h("tbody", {}, cols.map((c) => h("tr", {}, h("td", { class: "mono" }, c.name), h("td", { class: "mono small" }, c.type)))));
// A dataset in full: what it is, where it comes from, what it holds, and what it should hold.
function dataCard(d) {
  const st = state.data[d.name] || { status: "waiting" }, p = st.profile;
  const pill = st.status === "mounted" ? h("span", { class: "pill done" }, "loaded") : st.status === "error" ? h("span", { class: "pill error" }, "not loaded")
    : h("span", { class: "pill" }, st.status === "converting" ? "converting" : st.status === "loading" ? "loading" : "needed");
  return h("div", { class: "data-card", "data-dataset": d.name },
    h("div", { class: "data-head" }, h("strong", { class: "mono" }, d.name), pill, h("span", { class: "grow" }),
      h("button", { class: "btn link small", "data-action": "edit-data", onclick: () => openModal("data") }, "Data…")),
    d.desc ? h("p", { class: "small" }, d.desc) : null,
    h("table", { class: "kv facts" }, h("tbody", {},
      h("tr", {}, h("th", {}, "source"), h("td", { class: "mono small" }, d.path || d.files[0].rel, d.format ? h("span", { class: "muted" }, ` (${d.format})`) : null)),
      h("tr", {}, h("th", {}, "read as"), h("td", { class: "mono small" }, d.at)),
      h("tr", {}, h("th", {}, "size"), h("td", {}, fmtBytes(st.size || d.size))),
      h("tr", {}, h("th", {}, "holds"), h("td", {}, profileFacts(p) || h("span", { class: "muted" }, st.status === "mounted" ? "…" : "known once loaded"))),
      h("tr", {}, h("th", {}, "state"), h("td", { class: "small" }, dataStatus(d))))),
    d.schema ? schemaTable(d) : p && p.kind === "table" ? h("details", { class: "fold" }, h("summary", {}, `Columns (${p.columns.length})`), columnsTable(p.columns)) : null);
}
const dataBrief = (d) => { const st = state.data[d.name] || {};
  return h("p", { "data-dataset": d.name }, h("span", { class: "mono" }, d.name), " ",
    h("span", { class: "muted small" }, [fmtBytes(st.size || d.size), st.profile ? profileFacts(st.profile) : null, schemaNote(d.name) ? schemaNote(d.name).text : null].filter(Boolean).join(" · ")),
    " ", h("span", { class: "small" }, "read by "), nodesReading(d).map((n, i) => [i ? ", " : "", nodeLink(n)])); };
const nodesReading = (d) => order.filter((n) => nodeData(n).includes(d));
// A table a view shows as data (ui.data): its rows and columns, the first rows, the types.
const fileCard = (b) => { const p = b.profile || {};
  return h("div", { class: "data-card" },
    h("p", { class: "small" }, profileFacts(p) || ""),
    p.head && p.columns ? tableOf(p.columns.map((c) => c.name), p.head, p.rows) : null,
    p.kind === "table" && p.columns.some((c) => c.type) ? h("details", { class: "fold" }, h("summary", {}, `Columns (${p.columns.length})`), columnsTable(p.columns)) : null); };
const constraintText = (c) => Object.entries(c || {}).map(([k, v]) => k === "required" || k === "unique" ? (v ? k : null)
  : `${k} ${Array.isArray(v) ? v.join(" | ") : v}`).filter(Boolean).join(", ");
// The schema a node declares for a dataset it reads, and how the loaded data matches it.
function schemaTable(d) {
  const c = (state.data[d.name] || {}).check, r = c && c.status === "done" ? c.result : null, note = schemaNote(d.name);
  const byName = Object.fromEntries(((r && r.fields) || []).map((f) => [f.name, f]));
  return h("div", { class: "schema", "data-schema": d.name },
    h("div", { class: "schema-head" }, h("strong", {}, "Schema"), note ? h("span", { class: `pill ${note.cls}` }, note.text)
      : h("span", { class: "pill" }, "checked once the data is loaded"), h("span", { class: "small muted" }, "declared by ", nodeLink(d.schema_node))),
    h("table", { class: "kv schema-fields" }, h("thead", {}, h("tr", {}, h("th", {}, "field"), h("th", {}, "type"), h("th", {}, "rules"), h("th", {}, r ? "found" : ""))),
      h("tbody", {}, d.schema.fields.map((f) => { const got = byName[f.name];
        return h("tr", { "data-field": f.name, class: got && !got.ok ? "bad" : null },
          h("td", {}, h("span", { class: "mono" }, f.name), f.description ? h("div", { class: "small muted" }, f.description) : null),
          h("td", { class: "mono small" }, f.type, f.unit ? ` (${f.unit})` : ""),
          h("td", { class: "small" }, constraintText(f.constraints)),
          h("td", { class: "small" }, got ? [got.found ? h("span", { class: "mono" }, got.found) : null,
            got.min !== null && got.min !== undefined ? h("div", { class: "muted" }, `${fmt(got.min)} … ${fmt(got.max)}`) : null,
            got.nulls ? h("div", { class: "muted" }, `${fmt(got.nulls)} empty`) : null,
            got.problems.map((p) => h("div", { class: "problem" }, p))] : null)); }))),
    r && r.extra && r.extra.length ? h("p", { class: "small muted" }, `Also in the data, not in the schema: ${r.extra.join(", ")}.`) : null,
    r ? (r.problems || []).map((p) => h("p", { class: `small ${r.ok === null ? "muted" : "problem"}` }, p)) : null,
    c && c.status === "error" ? h("p", { class: "small problem" }, c.error) : null);
}

// ---- links, contents
const nodeLink = (n) => h("button", { class: "btn link mono", "data-goto": n, onclick: () => select({ kind: "node", name: n }) }, n);
const groupLink = (g) => h("button", { class: "btn link", "data-goto-group": g, onclick: () => select({ kind: "group", name: g }) }, g);
// Nodes as a list, in their groups (the report's table of contents, also for keyboards and screen readers).
function contentsList(names) {
  const item = (n) => h("li", {}, nodeLink(n), h("span", { class: "small muted" }, ` ${nodes[n].desc || ""}`));
  const all = names.length === order.length;
  const inGroups = all ? groupNames : [];
  return h("ul", { class: "contents" },
    inGroups.map((g) => h("li", {}, groupLink(g), h("ul", {}, groups[g].nodes.map(item)))),
    names.filter((n) => !all || !groupOf[n]).map(item));
}

// ---- charts: series over a shared x, scatter or line; a previous run's drawn faint and dashed
function ticks(lo, hi, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(10)));
  return out;
}
function chart(b, ref, refName) {
  const all = [b, ref].filter(Boolean);
  const finite = (xs) => xs.filter((v) => typeof v === "number" && Number.isFinite(v));
  const allX = finite(all.flatMap((c) => c.x)), allY = finite(all.flatMap((c) => c.series.flatMap((s) => s.y)));
  if (!allX.length || !allY.length) return h("p", { class: "muted small" }, "No numeric data to draw.");
  const W = 560, H = 260, L = 52, R = 12, T = 10, B = 34;
  let [x0, x1] = [Math.min(...allX), Math.max(...allX)], [y0, y1] = [Math.min(...allY), Math.max(...allY)];
  const pad = (y1 - y0) * 0.06 || 1; y0 -= pad; y1 += pad;
  const sx = (v) => L + (v - x0) / (x1 - x0 || 1) * (W - L - R), sy = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
  const svg = h("svg:svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `${b.title || "chart"}: ${b.series.map((s) => s.name).join(", ")}${ref ? `, with ${refName}` : ""}` });
  const grid = h("svg:g", { class: "grid" });
  for (const t of ticks(y0, y1)) grid.append(h("svg:line", { x1: L, x2: W - R, y1: sy(t), y2: sy(t) }), h("svg:text", { x: L - 6, y: sy(t) + 4, "text-anchor": "end" }, fmt(t)));
  for (const t of ticks(x0, x1)) grid.append(h("svg:text", { x: sx(t), y: H - B + 16, "text-anchor": "middle" }, fmt(t)));
  svg.append(grid, h("svg:text", { x: (L + W - R) / 2, y: H - 4, "text-anchor": "middle" }, b.x_label || ""));
  if (y0 < 0 && y1 > 0) svg.append(h("svg:line", { class: "zero", x1: L, x2: W - R, y1: sy(0), y2: sy(0) }));
  const colors = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
  const draw = (c, faint) => c.series.forEach((s, i) => {
    const col = faint ? "var(--faint)" : colors[i % colors.length];
    const pts = c.x.map((xv, j) => [xv, s.y[j]]).filter(([xv, yv]) => Number.isFinite(xv) && Number.isFinite(yv));
    if (s.kind === "scatter") {
      const g = h("svg:g", faint ? { class: "base", fill: "none", stroke: col } : { fill: col, "fill-opacity": 0.55 });
      for (const [xv, yv] of pts) g.append(h("svg:circle", { cx: sx(xv), cy: sy(yv), r: 2.4 }));
      svg.append(g);
    } else {
      const d = pts.map(([xv, yv], j) => `${j ? "L" : "M"}${sx(xv).toFixed(1)},${sy(yv).toFixed(1)}`).join("");
      svg.append(h("svg:path", { d, fill: "none", stroke: col, "stroke-width": 2, class: faint ? "base" : null }));
    }
  });
  if (ref) draw(ref, true);
  draw(b, false);
  const legend = [...(b.series.length > 1 ? b.series.map((s, i) => h("span", { cssvars: { "--c": colors[i % colors.length] } }, s.name)) : []),
    ref ? h("span", { class: "base", cssvars: { "--c": "var(--faint)" } }, refName) : null].filter(Boolean);
  return h("div", { "data-plot": b.id }, svg, legend.length ? h("div", { class: "chart-legend" }, legend) : null);
}
