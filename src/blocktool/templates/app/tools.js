// tools.js: the agent interface (WebMCP tools, also on window.blocksApp.tools). An agent
// iterating on an app in conversation reads the graph, sets settings, runs, reads outputs
// and blocks, and compares runs, through these.

// ------------------------------------------------------------------ agent interface (WebMCP + window.blocksApp)
const snapshot = (n) => {
  const s = state.node[n], node = nodes[n], ref = refNode(n);
  return { name: n, group: groupOf[n] || null, doc: node.doc, file: node.file, inputs: node.deps, status: s.status, cached: !!s.cached,
    seconds: s.seconds, settings: Object.fromEntries(nodeSettings(n).map((k) => [k, state.settings[k]])),
    declared_metrics: declaredFor(n).map(({ key, label, goal, headline: hl }) => ({ key, label, goal, headline: hl })),
    metrics: s.metrics || {}, digest: s.digest || null, data: nodeData(n).map((d) => ({ name: d.name, profile: (state.data[d.name] || {}).profile || null })),
    error: s.status === "error" ? s.error : undefined, showing: shownSide(n),
    blocks: ((shownRecord(n) || {}).blocks || []).map((b) => ({ type: b.type, id: b.id, title: b.title })),
    reference: ref ? reference().name : null, reference_metrics: ref ? ref.metrics : null, compare: comparable(n),
    comparison: state.cmp && state.cmp.nodes[n] ? { verdict: state.cmp.nodes[n].verdict, metrics: state.cmp.nodes[n].metrics } : null,
    log: (s.log || "").slice(-4000) };
};
// A run in a few fields: its name, source, the settings it changed from the defaults, its data, headline, what it computed.
const summary = (r) => r && { name: r.name, source: r.doc.source, settings: r.doc.changed_settings, data: r.doc.data,
  headline: r.doc.headline, ran: r.doc.ran, seconds: r.doc.seconds, made: r.doc.made };
async function applyRun(name, run) {
  const r = runByName(name);
  if (!r) throw new Error(`no run ${name}`);
  const known = Object.fromEntries(Object.entries(r.doc.settings || {}).filter(([k]) => k in settingSpec));
  const warnings = await setSettings({ ...defaults, ...known });
  refresh();
  const out = { applied: r.name, settings: r.doc.changed_settings, warnings };
  if (run) { const res = await runGraph("agent"); out.ok = res.ok; out.failed = res.failed; out.run = summary(res.run); }
  return out;
}
async function sweep({ grid, max_runs = 50, restore = true, source = "sweep" }) {
  const keys = Object.keys(grid || {});
  if (!keys.length) throw new Error("grid must map setting names (node.param) to lists of values");
  for (const k of keys) {
    if (!(k in settingSpec)) throw new Error(`unknown setting ${k}`);
    if (!Array.isArray(grid[k]) || !grid[k].length) throw new Error(`grid.${k} must be a non-empty list`);
  }
  let combos = [{}];
  for (const k of keys) combos = combos.flatMap((c) => grid[k].map((v) => ({ ...c, [k]: v })));
  if (combos.length > max_runs) throw new Error(`${combos.length} combinations exceed max_runs=${max_runs}`);
  const start = { ...state.settings }, results = [], docs = [];
  try {
    for (const combo of combos) {
      const warnings = await setSettings(combo);
      const res = await runGraph(source);
      const doc = res.run ? res.run.doc : state.current;   // a combination already run comes from the cache
      if (doc) docs.push({ ...doc, name: `sweep-${docs.length}` });
      results.push({ settings: combo, ok: res.ok, failed: res.failed, warnings, run: res.run ? summary(res.run) : { headline: headlineNow() } });
    }
    if (restore) { await setSettings(start); await runGraph(source); }
  } finally { refresh(); }
  const ranked = await call("summarize", { runs: docs, ref: null });   // the best, by each metric's goal (blocks.runs)
  const best = Object.fromEntries(Object.entries(ranked.best).map(([id, name]) => { const i = Number(name.slice(6));
    return [id, { value: docs[i].headline[id], settings: results[i].settings }]; }));
  return { runs: results, best, restored: restore };
}
const SEL = { type: "object", properties: { node: { type: "string", enum: order }, group: { type: "string", enum: groupNames } } };
const tools = [
  { name: "get_overview", description: "The app's question and description, its headline metrics (with goals) for this run and the reference run, nodes with their inputs and status, groups, settings with ranges, datasets with what they hold, previous runs loaded, run count.",
    inputSchema: { type: "object", properties: {} },
    run: () => { const r = reference();
      return { project: manifest.project, app: manifest.id, title: manifest.title, question: manifest.question, description: manifest.description, mode: manifest.mode,
        ready: state.ready && dataReady(), at_defaults: atDefaults(),
        headline: headline.map((m) => ({ ...m, now: headlineNow()[m.id], reference: r ? (r.doc.headline || {})[m.id] : undefined,
          delta: (headlineCell(m.id) || {}).delta, better: (headlineCell(m.id) || {}).better })),
        nodes: order.map((n) => ({ name: n, group: groupOf[n] || null, description: nodes[n].desc, inputs: nodes[n].deps.map((d) => d.name), status: state.node[n].status })),
        groups: Object.fromEntries(groupNames.map((g) => [g, groups[g].nodes])), edges: graph.edges,
        settings: Object.fromEntries(Object.entries(settingSpec).map(([k, v]) => [k, { ...v, value: state.settings[k] }])),
        datasets: manifest.datasets.map((d) => ({ name: d.name, kind: d.kind, desc: d.desc, size: d.size, at: d.at, state: state.data[d.name] })),
        reference: r && r.name, changes: state.cmp ? state.cmp.changes : [],
        previous_runs: loaded().map((x) => ({ name: x.name, app: x.doc.app, made: x.doc.made, from: x.from, headline: x.doc.headline })),
        plugins: (manifest.plugins || []).map((p) => p.name), runs: state.runs.filter((x) => x.from === "session").length, runtime: manifest.runtime,
        superseded: (manifest.superseded || []).map((s) => s.name),
        views: viewList().map(({ name, title, at, status }) => ({ name, title, at, status })) }; } },
  { name: "get_node", description: "One node: its documentation (docstring), file, inputs, settings, the metrics it declares and this run's values (and the reference's), its output's digest, its results blocks, log, error.",
    inputSchema: { type: "object", properties: { name: { type: "string", enum: order } }, required: ["name"] },
    run: ({ name }) => snapshot(name) },
  { name: "get_report", description: "What the report shows now (the overview, a group or a node) as text; folds count only when open.",
    inputSchema: { type: "object", properties: {} },
    run: () => ({ selected: state.sel, shown: !!state.reportShown, text: ui.report ? ui.report.innerText : "" }) },
  { name: "get_source", description: "Read a file of the app, e.g. nodes/train.py or app.yaml (paths relative to the app).",
    inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] },
    run: ({ path }) => ({ path, text: textOf(has(path) ? path : `project/${path}`) }) },
  { name: "set_settings", description: "Set settings (node.param, e.g. train.alpha). Returns range warnings; the nodes they reach become stale until a run. Pass run:true to run afterwards.",
    inputSchema: { type: "object", properties: { values: { type: "object" }, run: { type: "boolean" } }, required: ["values"] },
    run: async ({ values, run }) => {
      const warnings = await setSettings(values); refresh();
      const out = { warnings, changed: changedSettings() };
      if (run) { const r = await runGraph("agent"); out.ok = r.ok; out.failed = r.failed; out.computed = r.computed; out.run = summary(r.run); }
      return out; } },
  { name: "run", description: "Run the graph: every node whose code, settings or inputs changed (the rest come from the cache); all:true runs every node again.",
    inputSchema: { type: "object", properties: { all: { type: "boolean" }, source: { type: "string" } } },
    run: async ({ all = false, source } = {}) => {
      const r = await runGraph(source || "agent", all);
      return { ok: r.ok, failed: r.failed, error: r.error, computed: r.computed, run: summary(r.run),
        nodes: order.map((n) => ({ name: n, status: state.node[n].status, cached: !!state.node[n].cached, seconds: state.node[n].seconds, error: state.node[n].error })) }; } },
  { name: "sweep", description: "Grid sweep over settings (grid: {node.param: [values]}): run each combination (only what changed recomputes), then restore the starting settings. Returns each run's headline and the best per metric.",
    inputSchema: { type: "object", properties: { grid: { type: "object" }, max_runs: { type: "number" }, restore: { type: "boolean" } }, required: ["grid"] },
    run: (args) => sweep(args) },
  { name: "list_runs", description: "Every run: this session's, the run log's, the app's and loaded files (from), each with the settings it changed from the defaults, its data, headline metrics, what it computed, and what differs from the reference. Optionally sorted best-first by a headline metric id.",
    inputSchema: { type: "object", properties: { sort_by: { type: "string", enum: headline.map((m) => m.id) }, limit: { type: "number" } } },
    run: ({ sort_by, limit = 50 } = {}) => {
      const sum = state.summary || { rows: [], best: {}, order: {} }, rowOf = Object.fromEntries(sum.rows.map((r) => [r.name, r]));
      let runs = [...state.runs].sort((a, b) => String(b.doc.made).localeCompare(String(a.doc.made)));
      if (sort_by && sum.order[sort_by]) runs = sum.order[sort_by].map(runByName).filter(Boolean);
      return { total: state.runs.length, reference: reference() && reference().name, best: sum.best,
        runs: runs.slice(0, limit).map((r) => ({ ...summary(r), from: r.from, changes: (rowOf[r.name] || {}).changes || [] })) };
    } },
  { name: "apply_run", description: "Set the settings of a run (others back to defaults); run:true runs it.",
    inputSchema: { type: "object", properties: { name: { type: "string" }, run: { type: "boolean" } }, required: ["name"] },
    run: ({ name, run }) => applyRun(name, run) },
  { name: "read_output", description: "A node's output as JSON (numpy arrays as lists, tables as {columns, rows}): this session's.",
    inputSchema: { type: "object", properties: { node: { type: "string", enum: order } }, required: ["node"] },
    run: async ({ node }) => ({ node, output: await readOutput(node) }) },
  { name: "export_run", description: "This run as a run file (blocks-run/1, made by blocks.runs): settings, data, and per node its metrics, output digest and blocks. save:true downloads it; name defaults to its date and time. Needs every node done and current.",
    inputSchema: { type: "object", properties: { name: { type: "string" }, save: { type: "boolean" } } },
    run: ({ name, save = false } = {}) => {
      const run = runFile(name);
      if (save) download(`${run.name}.run.json`, JSON.stringify(run, null, 1), "application/json");
      return { name: run.name, run, missing: [] };
    } },
  { name: "add_run", description: "Load a run file (the JSON from export_run or Download run) as a previous run named name, to compare with.",
    inputSchema: { type: "object", properties: { name: { type: "string" }, run: { type: "object" } }, required: ["name", "run"] },
    run: async ({ name, run }) => { addRun(name, run); await compareRuns(); refresh(); return { previous_runs: loaded().map((r) => r.name), reference: reference() && reference().name }; } },
  { name: "remove_run", description: "Remove a run from the list.",
    inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] },
    run: async ({ name }) => { await removeRun(name); return { previous_runs: loaded().map((r) => r.name) }; } },
  { name: "set_reference", description: "Pick the run this run is compared with, any run in list_runs (omit name for the default: \"baseline\", else the latest loaded).",
    inputSchema: { type: "object", properties: { name: { type: "string" } } },
    run: async ({ name } = {}) => { await setReference(name || null); return { reference: reference() && reference().name, changes: state.cmp ? state.cmp.changes : [] }; } },
  { name: "show_reference", description: "In a node's results, show the reference run's blocks instead of this run's (on:false switches back).",
    inputSchema: { type: "object", properties: { node: { type: "string", enum: order }, on: { type: "boolean" } }, required: ["node"] },
    run: ({ node, on = true }) => { if (on && !comparable(node)) throw new Error(`${node}: no reference results to show (run it, and load a run that has it)`);
      setShown(node, on); return { node, shown: on ? "reference" : "run" }; } },
  { name: "check_data", description: "Check a dataset against the schema the node that reads it declares (SCHEMA): per field the type found, empty values, range, and the rules rows break.",
    inputSchema: { type: "object", properties: { dataset: { type: "string", enum: manifest.datasets.filter((d) => d.schema).map((d) => d.name) } }, required: ["dataset"] },
    run: async ({ dataset }) => {
      if (!(datasets[dataset] || {}).schema) throw new Error(`no node declares a schema for ${dataset}`);
      const c = await checkSchema(dataset);
      if (!c) throw new Error(`dataset ${dataset} is not loaded`);
      return c;
    } },
  { name: "query_data", description: "Run DuckDB SQL in the app's directory, e.g. SELECT * FROM 'data/measurements.parquet' LIMIT 5. Datasets are read in place; results are capped at limit rows.",
    inputSchema: { type: "object", properties: { sql: { type: "string" }, limit: { type: "number" } }, required: ["sql"] },
    run: ({ sql, limit }) => call("query", { sql, limit: Math.min(limit || 200, 5000) }) },
  { name: "reset", description: "Restore default settings and the original datasets.", inputSchema: { type: "object", properties: {} },
    run: async () => { await resetAll(); refresh(); return { ok: true }; } },
  { name: "select", description: "Show the overview (no node or group), a group or a node in the report.",
    inputSchema: SEL,
    run: ({ node, group } = {}) => { select(node ? { kind: "node", name: node } : group ? { kind: "group", name: group } : { kind: "overview" });
      return { selected: state.sel }; } },
  { name: "list_views", description: "The app's views (plugin.yaml views): where each is shown, what it may read and do, and its health: status (ready once it called bridge.ready), errors, CSP violations, and the summary it reports with bridge.describe.",
    inputSchema: { type: "object", properties: {} },
    run: () => ({ views: viewList() }) },
  { name: "open_view", description: "Show a view (its place in the report, or the Data modal) and wait until it has drawn the app's latest state (settled) or reports an error.",
    inputSchema: { type: "object", properties: { name: { type: "string", enum: Object.keys(views) }, timeout_ms: { type: "number" } }, required: ["name"] },
    run: ({ name, timeout_ms }) => openView(name, timeout_ms) },
  { name: "set_theme", description: "Switch the visual theme and/or light/dark mode.",
    inputSchema: { type: "object", properties: { name: { type: "string", enum: themeNames }, mode: { type: "string", enum: ["light", "dark"] } } },
    run: ({ name, mode } = {}) => { const t = currentTheme(); applyTheme(name || t.name, mode || t.mode); renderModals(); return currentTheme(); } },
  { name: "show_report", description: "Show or hide the report beside the graph.",
    inputSchema: { type: "object", properties: { shown: { type: "boolean" } }, required: ["shown"] },
    run: ({ shown }) => { setReportShown(shown); return { shown: state.reportShown }; } },
];
function registerWebMCP() {
  const mc = navigator.modelContext;
  const wrap = (t) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema,
    execute: async (args) => ({ content: [{ type: "text", text: JSON.stringify(await t.run(args || {}), null, 1) }] }) });
  try {
    if (mc && typeof mc.provideContext === "function") mc.provideContext({ tools: tools.map(wrap) });
    else if (mc && typeof mc.registerTool === "function") tools.forEach((t) => mc.registerTool(wrap(t)));
  } catch (e) { console.warn("WebMCP registration failed", e); }
}
