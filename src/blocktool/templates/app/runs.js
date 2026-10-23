// runs.js: runs as data, the run the page shows (the active run), and the runs it is
// compared with (docs/runs.md).
//
// A run is a run file (blocks-run/2), made by the worker after every run (blocks.runs): a
// snapshot of the run, with the app's code, the settings and data (by key), and per node its
// key, metrics, output digest (and the output itself when small) and the blocks the page
// showed. The page keeps one list of them, state.runs, each {name, doc, from}: this
// session's runs ("session"), earlier ones from the dev server's run log ("log"), the ones
// the app ships ("app", e.g. its baseline or a superseded version's) and files the viewer
// loads ("file").
//
// The page shows one run, the active run: after Run, the run it made; activating another
// reinstates it, its settings (and original data) and every page, the DAG and the headline
// as they were. Any number of other runs can be selected to compare with it. Every
// comparison comes from the worker (blocks.runs.compare_many, summarize) and the comparison
// block draws it (blocks.js); this file keeps the list, the active run and the selection.
//
// Runs are a block an app can leave out (app.yaml ui: runs: false): then there is no list,
// no selection and no run log; the active run is always the graph as it now stands.

const RUN_FORMAT = manifest.run_format;   // blocks.runs.FORMAT
const RUNS = manifest.ui.runs;
const appId = manifest.id;
state.runs = [];         // [{name, doc, from: "session" | "log" | "app" | "file"}]
state.current = null;    // the run file of the graph as it now stands in the worker (complete or not)
state.active = null;     // the name of the run the page shows; null: state.current
state.compare = [];      // the names of the runs it is compared with
state.cmp = [];          // blocks.runs.compare_many(active, compared runs), in the order of comparedRuns()
state.summary = null;    // blocks.runs.summarize(every run, active): per run, and the best
const runNameOf = (fileName) => fileName.replace(/\.run\.json$/i, "").replace(/\.json$/i, "");
const freeName = (name) => { let n = name, i = 2; while (state.runs.some((r) => r.name === n)) n = `${name}-${i++}`; return n; };
function addRun(name, doc, from = "file") {
  if (!doc || doc.format !== RUN_FORMAT) throw new Error(`${name}: not a ${RUN_FORMAT} run file`);
  if (doc.project !== manifest.project) throw new Error(`${name}: a run of the project ${doc.project}, not ${manifest.project}`);
  state.runs = state.runs.filter((r) => r.name !== name).concat([{ name, doc: { ...doc, name }, from }]);
}
// A run of this session: kept in the list (and in the dev server's run log, build/<app>/runs.jsonl).
async function keepRun(doc) {
  const name = freeName(doc.name);
  const run = { name, doc: { ...doc, name }, from: "session" };
  if (!RUNS) return run;
  state.runs.push(run);
  if (linked && manifest.api && !harvest) {
    try { await fetch(manifest.api, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(run.doc) }); }
    catch (e) { console.warn("run not saved", e); }
  }
  return run;
}
async function loadRuns() {
  if (!RUNS || !linked || !manifest.api) return;
  try {
    const r = await fetch(manifest.api, { cache: "no-store" });
    if (!r.ok) return;
    for (const doc of (await r.json()).runs || []) if (doc && doc.format === RUN_FORMAT && doc.project === manifest.project) {
      const name = freeName(doc.name);
      state.runs.push({ name, doc: { ...doc, name }, from: "log" });
    }
  } catch { /* server without a run log */ }
}
// The runs the app ships; its baseline, if it ships one, is compared with from the start.
function loadShippedRuns() {
  for (const r of manifest.runs || []) {
    try { addRun(r.name, jsonOf(r.path), "app"); } catch (e) { console.warn(`run ${r.name} not loaded`, e); }
  }
  if (runByName("baseline")) state.compare = ["baseline"];
}
async function addRunFiles(files) {
  for (const f of files) addRun(runNameOf(f.name), JSON.parse(await f.text()));
  await compareRuns();
  refresh();
}
async function removeRun(name) {
  state.runs = state.runs.filter((r) => r.name !== name);
  state.compare = state.compare.filter((x) => x !== name);
  if (state.active === name) state.active = null;
  await compareRuns();
  refresh();
}
const runByName = (name) => state.runs.find((r) => r.name === name) || null;
const loaded = () => state.runs.filter((r) => r.from !== "session");
const sameApp = (r) => r.doc.app === appId;
const runLabel_ = (r) => r.name ? `${r.name}${sameApp(r) ? "" : ` (${String(r.doc.app).split("/").pop()})`}` : "this run";

// ------------------------------------------------------------------ the active run
// The run the page shows: the one made active, else the graph as it now stands.
const activeRun = () => runByName(state.active) || (state.current ? { name: null, doc: state.current, from: "live" } : null);
const activeDoc = () => (activeRun() || {}).doc || null;
// After a run: the run it made, else (nothing computed) the newest run with the same keys.
function activeAfterRun(kept) {
  if (kept) return kept.name;
  const rec = state.current;
  if (!rec || !rec.complete) return null;
  const same = state.runs.filter((r) => order.every((n) => ((r.doc.nodes || {})[n] || {}).key === rec.nodes[n].key));
  return same.length ? same.sort((a, b) => String(b.doc.made).localeCompare(String(a.doc.made)))[0].name : null;
}
// Make a run active: its settings (the others back to defaults) and, where it read the
// original data, the original data; the page then shows its results as they were.
async function activateRun(name) {
  const r = runByName(name);
  if (!r) throw new Error(`no run ${name}`);
  state.active = name;
  state.compare = state.compare.filter((x) => x !== name);
  const known = Object.fromEntries(Object.entries(r.doc.settings || {}).filter(([k]) => k in settingSpec));
  const warnings = await setSettings({ ...defaults, ...known });
  const data = [];
  for (const d of manifest.datasets) {
    const want = (r.doc.data || {})[d.name], have = state.data[d.name] || {};
    if (!want || want.key === have.key) continue;
    if (want.original) { await restoreData(d.name); data.push(`${d.name}: the original`); }
    else data.push(`${d.name}: ${want.file || "another file"} (provide it in Data to run on it)`);
  }
  await compareRuns();
  refresh();
  return { active: name, settings: r.doc.changed_settings, warnings, data };
}
// The active run's record of node n (status, key, metrics, digest, output, blocks), or null.
const shownNode = (n) => ((activeDoc() || {}).nodes || {})[n] || null;
const shown = (n) => (shownNode(n) || {}).status === "done";
// The worker holds the active run's output of n (its cache has the same key), and it is current.
const held = (n) => { const r = shownNode(n), s = state.node[n];
  return !!r && !!s.key && s.key === r.key && ["done", "stale"].includes(s.status); };
const live = (n) => held(n) && state.node[n].status === "done";
const ancestors = (n) => { const out = new Set(), stack = [n];
  while (stack.length) for (const p of parents(stack.pop())) if (!out.has(p)) { out.add(p); stack.push(p); }
  return order.filter((x) => out.has(x)); };
// The settings and data that reach n are those of the active run.
function matchesControls(n) {
  const run = activeDoc() || {}, reach = [...ancestors(n), n];
  return reach.every((m) => nodeSettings(m).every((k) => same(state.settings[k], (run.settings || {})[k])))
    && reach.flatMap(nodeData).every((d) => ((run.data || {})[d.name] || {}).key === (state.data[d.name] || {}).key);
}
// What the page says of n: running; done (the active run's, current in the worker); kept (the
// active run's, from its run file: Run computes it again); stale (a setting or input changed
// since); failed or blocked in the active run; not run.
function shownStatus(n) {
  const s = state.node[n], r = shownNode(n);
  if (s.status === "running") return "running";
  if (!r || r.status === "pending") return "pending";
  if (!matchesControls(n)) return "stale";
  if (r.status !== "done") return r.status;
  return live(n) ? "done" : "kept";
}
// Nodes whose own code differs between the active run and the app now.
const otherCode = (n) => { const r = shownNode(n); return !!r && !!r.code && r.code !== nodes[n].compute_sha; };

// ------------------------------------------------------------------ comparing
const comparedRuns = () => { const a = activeRun();
  return state.compare.map(runByName).filter((r) => r && r !== a); };
async function setCompare(names) {
  for (const n of names) if (!runByName(n)) throw new Error(`no run ${n}`);
  state.compare = [...new Set(names)].filter((n) => n !== state.active);
  await compareRuns();
  refresh();
}
const toggleCompare = (name, on) => setCompare(on ? [...state.compare, name] : state.compare.filter((x) => x !== name));
// What summarize and changes read of a run (blocks.runs.brief): the list's name, no blocks, outputs or code.
const brief = (r) => ({ name: r.name, app: r.doc.app, code_sha: r.doc.code_sha, settings: r.doc.settings, data: r.doc.data,
  headline: r.doc.headline, made: r.doc.made,
  nodes: Object.fromEntries(Object.entries(r.doc.nodes || {}).map(([n, s]) => [n, { code: s.code, status: s.status }])) });
// Ask the worker to compare the active run with each selected run, and every run with it.
async function compareRuns() {
  if (!RUNS || !state.ready) return;
  const a = activeRun(), refs = comparedRuns();
  try {
    state.cmp = a && refs.length ? await call("compare", { run: a.doc, refs: refs.map((r) => r.doc) }) : [];
    state.summary = await call("summarize", { runs: state.runs.map(brief), ref: a ? brief(a) : null });
  } catch (e) { console.warn("runs not compared", e); }
}
// The comparison with each selected run: [{run, cmp}].
const comparisons = () => comparedRuns().map((run, i) => ({ run, cmp: state.cmp[i] })).filter((x) => x.cmp);
const signed = (d) => (d > 0 ? "+" : "") + fmt(d);
// What changed between two runs' inputs (blocks.runs.changes), in words; n: only what reaches node n.
const changeText = (c) => c.kind === "app" ? `app ${c.from} → ${c.to}`
  : c.kind === "code" ? `code${c.nodes.length ? ` of ${c.nodes.join(", ")}` : " (helpers, packages or recorded data)"}`
    + `${c.added.length ? `; new ${c.added.join(", ")}` : ""}${c.removed.length ? `; no ${c.removed.join(", ")}` : ""}`
  : c.kind === "setting" ? `${c.key} ${fmt(c.from)} → ${fmt(c.to)}` : `${c.key}: ${c.from || "none"} → ${c.to || "none"}`;
function changesFor(list, n) {
  if (!n) return list;
  const reach = new Set([...ancestors(n), n]), data = new Set([...reach].flatMap(nodeData).map((d) => d.name));
  return list.flatMap((c) => c.kind === "setting" ? (reach.has(c.key.split(".")[0]) ? [c] : [])
    : c.kind === "data" ? (data.has(c.key) ? [c] : [])
      : c.kind === "code" ? (c.nodes.some((x) => reach.has(x)) || reach.has(n) && c.added.concat(c.removed).includes(n) || !c.nodes.length ? [c] : [])
        : [c]);
}
