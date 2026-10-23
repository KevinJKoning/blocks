// tools.js: the agent interface (WebMCP tools, also on window.blocksApp.tools). An agent
// iterating on an app in conversation reads the graph, sets settings, runs, reads outputs
// and blocks, and compares runs, through these.

// ------------------------------------------------------------------ agent interface (WebMCP + window.blocksApp)
// A node in the active run: its state (runs.js shownStatus), settings, metrics, digest, blocks,
// whether its code differs from the app's now, and its comparison with each selected run.
const snapshot = (n) => {
  const s = state.node[n], node = nodes[n], r = shownNode(n) || {}, a = activeRun();
  return { name: n, group: groupOf[n] || null, doc: node.doc, file: node.file, inputs: node.deps, status: shownStatus(n), cached: !!s.cached && live(n),
    seconds: r.seconds, settings: Object.fromEntries(nodeSettings(n).map((k) => [k, state.settings[k]])),
    declared_metrics: declaredFor(n).map(({ key, label, goal, headline: hl }) => ({ key, label, goal, headline: hl })),
    metrics: r.metrics || {}, digest: r.digest || null, data: nodeData(n).map((d) => ({ name: d.name, profile: (state.data[d.name] || {}).profile || null })),
    error: ["error", "blocked"].includes(r.status) ? r.error : undefined, active: a ? a.name : null, other_code: otherCode(n),
    blocks: (r.blocks || []).map((b) => ({ type: b.type, id: b.id, title: b.title })), output_readable: readable(n),
    comparison: comparisons().map(({ run, cmp }) => ({ run: run.name, verdict: (cmp.nodes[n] || {}).verdict, metrics: (cmp.nodes[n] || {}).metrics || {},
      changes: changesFor(cmp.changes, n) })),
    log: held(n) ? (s.log || "").slice(-4000) : "" };
};
// A run in a few fields: its name, source, the settings it changed from the defaults, its data, headline, what it computed.
const summary = (r) => r && { name: r.name, source: r.doc.source, settings: r.doc.changed_settings, data: r.doc.data,
  headline: r.doc.headline, ran: r.doc.ran, seconds: r.doc.seconds, made: r.doc.made, code_sha: r.doc.code_sha };
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
      results.push({ settings: combo, ok: res.ok, failed: res.failed, warnings, run: res.run ? summary(res.run) : { headline: (state.current || {}).headline || {} } });
    }
    if (restore) { await setSettings(start); await runGraph(source); }
  } finally { refresh(); }
  const ranked = await call("summarize", { runs: docs.map((doc) => brief({ name: doc.name, doc })), ref: null });   // the best, by each metric's goal (blocks.runs)
  const best = Object.fromEntries(Object.entries(ranked.best).map(([id, name]) => { const i = Number(name.slice(6));
    return [id, { value: docs[i].headline[id], settings: results[i].settings }]; }));
  return { runs: results, best, restored: restore };
}
const SEL = { type: "object", properties: { node: { type: "string", enum: order }, group: { type: "string", enum: groupNames }, runs: { type: "boolean" } } };
const tools = [
  { name: "get_overview", description: "The app's question and description, the active run (the one the page shows) and its headline metrics (with goals) against each run compared with it, nodes with their inputs and status, groups, settings with ranges, datasets with what they hold, previous runs loaded, run count.",
    inputSchema: { type: "object", properties: {} },
    run: () => { const a = activeRun(), cs = comparisons(), now = (activeDoc() || {}).headline || {};
      return { project: manifest.project, app: manifest.id, title: manifest.title, question: manifest.question, description: manifest.description, mode: manifest.mode,
        ready: state.ready && dataReady(), at_defaults: atDefaults(), active: a ? a.name : null, compare: comparedRuns().map((r) => r.name),
        headline: headline.map((m) => ({ ...m, now: now[m.id],
          compared: Object.fromEntries(cs.map(({ run, cmp }) => { const c = cmp.headline[m.id] || {}; return [run.name, { value: c.ref, delta: c.delta, better: c.better }]; })) })),
        nodes: order.map((n) => ({ name: n, group: groupOf[n] || null, description: nodes[n].desc, inputs: nodes[n].deps.map((d) => d.name), status: shownStatus(n) })),
        groups: Object.fromEntries(groupNames.map((g) => [g, groups[g].nodes])), edges: graph.edges,
        settings: Object.fromEntries(Object.entries(settingSpec).map(([k, v]) => [k, { ...v, value: state.settings[k] }])),
        datasets: manifest.datasets.map((d) => ({ name: d.name, kind: d.kind, desc: d.desc, size: d.size, at: d.at, state: state.data[d.name] })),
        changes: Object.fromEntries(cs.map(({ run, cmp }) => [run.name, cmp.changes])),
        previous_runs: loaded().map((x) => ({ name: x.name, app: x.doc.app, made: x.doc.made, from: x.from, headline: x.doc.headline })),
        plugins: (manifest.plugins || []).map((p) => p.name), runs: state.runs.filter((x) => x.from === "session").length, runtime: manifest.runtime,
        superseded: (manifest.superseded || []).map((s) => s.name),
        views: viewList().map(({ name, title, at, status }) => ({ name, title, at, status })) }; } },
  { name: "get_node", description: "One node: its documentation (docstring), file, inputs, settings, the metrics it declares and this run's values (and the reference's), its output's digest, its results blocks, log, error.",
    inputSchema: { type: "object", properties: { name: { type: "string", enum: order } }, required: ["name"] },
    run: ({ name }) => snapshot(name) },
  { name: "get_report", description: "What the report shows now (the overview, the run log, a group or a node) as text, and the active run it shows; folds count only when open.",
    inputSchema: { type: "object", properties: {} },
    run: () => ({ selected: state.sel, active: (activeRun() || {}).name || null, shown: !!state.reportShown, text: ui.report ? ui.report.innerText : "" }) },
  { name: "get_source", description: "Read a file of the app, e.g. nodes/train.py or app.yaml (paths relative to the app).",
    inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] },
    run: ({ path }) => ({ path, text: textOf(has(path) ? path : `project/${path}`) }) },
  { name: "set_settings", description: "Set settings (node.param, e.g. train.alpha). Returns range warnings; the nodes they reach become stale until a run. Pass run:true to run afterwards.",
    inputSchema: { type: "object", properties: { values: { type: "object" }, run: { type: "boolean" } }, required: ["values"] },
    run: async ({ values, run }) => {
      const warnings = await setSettings(values); refresh();
      const out = { warnings, changed: changedSettings() };
      if (run) { const r = await runGraph("agent"); out.ok = r.ok; out.failed = r.failed; out.computed = r.computed; out.run = summary(r.run); out.active = state.active; }
      return out; } },
  { name: "run", description: "Run the graph: every node whose code, settings or inputs changed (the rest come from the cache); all:true runs every node again.",
    inputSchema: { type: "object", properties: { all: { type: "boolean" }, source: { type: "string" } } },
    run: async ({ all = false, source } = {}) => {
      const r = await runGraph(source || "agent", all);
      return { ok: r.ok, failed: r.failed, error: r.error, computed: r.computed, run: summary(r.run), active: state.active,
        nodes: order.map((n) => ({ name: n, status: shownStatus(n), cached: !!state.node[n].cached, seconds: state.node[n].seconds, error: state.node[n].error })) }; } },
  { name: "sweep", description: "Grid sweep over settings (grid: {node.param: [values]}): run each combination (only what changed recomputes), then restore the starting settings. Returns each run's headline and the best per metric.",
    inputSchema: { type: "object", properties: { grid: { type: "object" }, max_runs: { type: "number" }, restore: { type: "boolean" } }, required: ["grid"] },
    run: (args) => sweep(args) },
  { name: "list_runs", description: "Every run: this session's, the run log's, the app's and loaded files (from), each with the settings it changed from the defaults, its data, headline metrics, what it computed, and what differs from the active run (code, settings, data). Optionally sorted best-first by a headline metric id.",
    inputSchema: { type: "object", properties: { sort_by: { type: "string", enum: headline.map((m) => m.id) }, limit: { type: "number" } } },
    run: ({ sort_by, limit = 50 } = {}) => {
      const sum = state.summary || { rows: [], best: {}, order: {} }, rowOf = Object.fromEntries(sum.rows.map((r) => [r.name, r]));
      let runs = [...state.runs].sort((a, b) => String(b.doc.made).localeCompare(String(a.doc.made)));
      if (sort_by && sum.order[sort_by]) runs = sum.order[sort_by].map(runByName).filter(Boolean);
      return { total: state.runs.length, active: state.active, compare: comparedRuns().map((r) => r.name), best: sum.best,
        runs: runs.slice(0, limit).map((r) => ({ ...summary(r), from: r.from, changes: (rowOf[r.name] || {}).changes || [] })) };
    } },
  { name: "activate_run", description: "Make a run active: the page shows it as it was (its results, metrics, blocks) and takes its settings (others back to defaults) and, where it read the original data, the original data. Its results are kept ones until Run computes them again (with the app's code as it is now); run:true runs at once.",
    inputSchema: { type: "object", properties: { name: { type: "string" }, run: { type: "boolean" } }, required: ["name"] },
    run: async ({ name, run }) => { const out = await activateRun(name);
      if (run) { const res = await runGraph("agent"); Object.assign(out, { ok: res.ok, failed: res.failed, computed: res.computed, run: summary(res.run), active: state.active }); }
      return out; } },
  { name: "set_compare", description: "Pick the runs the active run is compared with (any in list_runs; [] for none). The comparison is in get_overview, get_node and the report's comparison blocks.",
    inputSchema: { type: "object", properties: { names: { type: "array", items: { type: "string" } } }, required: ["names"] },
    run: async ({ names }) => { await setCompare(names || []);
      return { active: state.active, compare: comparedRuns().map((r) => r.name), changes: Object.fromEntries(comparisons().map(({ run, cmp }) => [run.name, cmp.changes])) }; } },
  { name: "list_files", description: "The files each node's downloads(out) offers (made from its current results only when downloaded), and whether they can be made now.",
    inputSchema: { type: "object", properties: {} },
    run: () => ({ nodes: offering.map((n) => ({ node: n, status: state.node[n].status, ready: filesReady(n), files: state.node[n].files || [],
      error: state.node[n].files_error || undefined })), all_ready: current() }) },
  { name: "read_file", description: "Make one file a node offers and return it: text as text (up to max_chars), other bytes as their size. save:true also downloads it.",
    inputSchema: { type: "object", properties: { node: { type: "string", enum: offering }, name: { type: "string" }, max_chars: { type: "number" }, save: { type: "boolean" } }, required: ["node", "name"] },
    run: async ({ node, name, max_chars = 20000, save = false }) => {
      const f = (state.node[node].files || []).find((x) => x.name === name);
      if (!f) throw new Error(`${node} offers no file ${name} (list_files)`);
      if (!filesReady(node)) throw new Error(`${node} is ${state.node[node].status}: run it first`);
      const bytes = await call("file", { node, name });
      if (save) download(name, bytes, f.media);
      const text = /^(text\/|application\/(json|geo\+json)|image\/svg)/.test(f.media) ? new TextDecoder().decode(bytes) : null;
      return { node, name, media: f.media, bytes: bytes.length, text: text === null ? undefined : text.slice(0, max_chars), truncated: text !== null && text.length > max_chars };
    } },
  { name: "download_all", description: "Every file the nodes offer and run.json (the active run, which they come from), as one zip download. Needs the active run's results current (Run).",
    inputSchema: { type: "object", properties: {} },
    run: () => downloadAll() },
  { name: "read_output", description: "A node's output in the active run as JSON (numpy arrays as lists, tables as {columns, rows}): from the worker, or the run file where it keeps it (small outputs).",
    inputSchema: { type: "object", properties: { node: { type: "string", enum: order } }, required: ["node"] },
    run: async ({ node }) => ({ node, output: await readOutput(node) }) },
  { name: "export_run", description: "The active run as a run file (blocks-run/2, made by blocks.runs): the app's code, settings, data keys, and per node its key, metrics, output digest (and small outputs) and blocks. save:true downloads it; name renames it. Needs a complete run.",
    inputSchema: { type: "object", properties: { name: { type: "string" }, save: { type: "boolean" } } },
    run: ({ name, save = false } = {}) => {
      const run = runFile(name);
      if (save) download(`${run.name}.run.json`, JSON.stringify(run, null, 1), "application/json");
      return { name: run.name, run, missing: order.filter((n) => !((run.nodes || {})[n] || {}).blocks) };
    } },
  { name: "add_run", description: "Load a run file (the JSON from export_run, or run.json from Download) as a run named name, to make active or compare with.",
    inputSchema: { type: "object", properties: { name: { type: "string" }, run: { type: "object" } }, required: ["name", "run"] },
    run: async ({ name, run }) => { addRun(name, run); await compareRuns(); refresh(); return { previous_runs: loaded().map((r) => r.name), active: state.active }; } },
  { name: "remove_run", description: "Remove a run from the list.",
    inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] },
    run: async ({ name }) => { await removeRun(name); return { previous_runs: loaded().map((r) => r.name) }; } },
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
  { name: "select", description: "Show the overview (no node or group), the runs page (runs: true), a group or a node in the report.",
    inputSchema: SEL,
    run: ({ node, group, runs } = {}) => { select(node ? { kind: "node", name: node } : group ? { kind: "group", name: group } : { kind: runs ? "runs" : "overview" });
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
// Runs are a block an app can leave out (ui: runs: false), and with them their tools.
const RUN_TOOLS = ["list_runs", "activate_run", "set_compare", "add_run", "remove_run"];
if (!RUNS) tools.splice(0, tools.length, ...tools.filter((t) => !RUN_TOOLS.includes(t.name)));
function registerWebMCP() {
  const mc = navigator.modelContext;
  const wrap = (t) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema,
    execute: async (args) => ({ content: [{ type: "text", text: JSON.stringify(await t.run(args || {}), null, 1) }] }) });
  try {
    if (mc && typeof mc.provideContext === "function") mc.provideContext({ tools: tools.map(wrap) });
    else if (mc && typeof mc.registerTool === "function") tools.forEach((t) => mc.registerTool(wrap(t)));
  } catch (e) { console.warn("WebMCP registration failed", e); }
}
