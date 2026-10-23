// runs.js: runs as data, the one this run is compared with, and the one the report shows
// (docs/runs.md).
//
// A run is a run file (blocks-run/1), made by the worker after every run (blocks.runs):
// the settings and data, and per node its metrics, output digest and blocks. The page keeps
// one list of them, state.runs, each {name, doc, from}: this session's runs ("session"),
// earlier ones from the dev server's run log ("log"), the ones the app ships ("app", e.g.
// its baseline or a superseded version's) and files the viewer loads ("file"). The run
// log page shows the list. This run is compared with one of them, the reference: the one the
// viewer picked, else the one named "baseline", else the latest that is not this
// session's. The viewer can also view one: the whole report then shows that run's results
// instead of this session's, until they go back. Every comparison comes from the worker
// (blocks.runs.compare, summarize); this file keeps the list and draws none of it.
//
// Runs are a block an app can leave out (app.yaml ui: runs: false): then there is no list,
// no reference and no run log, and a viewer changes data, runs and downloads.

const RUN_FORMAT = manifest.run_format;   // blocks.runs.FORMAT
const RUNS = manifest.ui.runs;
const appId = manifest.id;
state.runs = [];         // [{name, doc, from: "session" | "log" | "app" | "file"}]
state.current = null;    // the run file of the graph as it now stands (complete or not)
state.reference = null;  // the name the viewer picked as reference (null: the default)
state.cmp = null;        // blocks.runs.compare(state.current, reference): per node, the headline, changes
state.summary = null;    // blocks.runs.summarize(every run, reference): per run, and the best
state.viewing = null;    // the name of the run the report shows instead of this session's, or null
const runNameOf = (fileName) => fileName.replace(/\.run\.json$/i, "").replace(/\.json$/i, "");
const freeName = (name) => { let n = name, i = 2; while (state.runs.some((r) => r.name === n)) n = `${name}-${i++}`; return n; };
function addRun(name, doc, from = "file") {
  if (!doc || doc.format !== RUN_FORMAT) throw new Error(`${name}: not a ${RUN_FORMAT} run file`);
  if (doc.project !== manifest.project) throw new Error(`${name}: a run of the project ${doc.project}, not ${manifest.project}`);
  state.runs = state.runs.filter((r) => r.name !== name).concat([{ name, doc, from }]);
}
// A run of this session: kept in the list (and in the dev server's run log, runs.jsonl).
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
      state.runs.push({ name: freeName(doc.name), doc, from: "log" });
    }
  } catch { /* server without a run log */ }
}
function loadShippedRuns() {
  for (const r of manifest.runs || []) {
    try { addRun(r.name, jsonOf(r.path), "app"); } catch (e) { console.warn(`run ${r.name} not loaded`, e); }
  }
}
async function addRunFiles(files) {
  for (const f of files) addRun(runNameOf(f.name), JSON.parse(await f.text()));
  await compareRuns();
  refresh();
}
async function removeRun(name) {
  state.runs = state.runs.filter((r) => r.name !== name);
  if (state.reference === name) state.reference = null;
  if (state.viewing === name) state.viewing = null;
  await compareRuns();
  refresh();
}
async function setReference(name) {
  if (name && !runByName(name)) throw new Error(`no run ${name}`);
  state.reference = name || null;
  await compareRuns();
  refresh();
}
const loaded = () => state.runs.filter((r) => r.from !== "session");
const runByName = (name) => state.runs.find((r) => r.name === name) || null;
const reference = () => runByName(state.reference) || runByName("baseline")
  || [...loaded()].sort((a, b) => String(b.doc.made).localeCompare(String(a.doc.made)))[0] || null;
const sameApp = (r) => r.doc.app === appId;
const runLabel_ = (r) => `${r.name}${sameApp(r) ? "" : ` (${String(r.doc.app).split("/").pop()})`}`;
// Ask the worker to compare this run with the reference, and every run with it.
async function compareRuns() {
  if (!RUNS || !state.ready) return;
  const r = reference();
  try {
    state.cmp = state.current && r ? await call("compare", { run: state.current, ref: r.doc }) : null;
    state.summary = await call("summarize", { runs: state.runs.map((x) => x.doc), ref: r ? r.doc : null });
  } catch (e) { console.warn("runs not compared", e); }
}
// The reference's record of node n (status, seconds, metrics, digest, blocks), or null.
function refNode(n) {
  const r = reference(), s = r && (r.doc.nodes || {})[n];
  return s && s.status === "done" ? s : null;
}
const refBlock = (n, id) => { const s = refNode(n); return s ? (s.blocks || []).find((b) => b.id === id) || null : null; };
const viewed = () => runByName(state.viewing);
// Compared with the reference: this session's results of n, when the reference has some.
const comparable = (n) => !viewed() && ran(n) && !!refNode(n);
// Which results of a node the report shows: "run" (this session's), "viewed" (the viewed
// run's), or null when there are none.
const shownSide = (n) => { const v = viewed();
  if (v) return ((v.doc.nodes || {})[n] || {}).status === "done" ? "viewed" : null;
  return ran(n) ? "run" : null; };
const shownRecord = (n) => ({ run: state.node[n], viewed: viewed() && (viewed().doc.nodes || {})[n] }[shownSide(n)] || null);
function viewRun(name) {
  if (name && !runByName(name)) throw new Error(`no run ${name}`);
  state.viewing = name || null;
  refresh();
}
// The comparison's cells (blocks.runs.cell): a node's metric, a metrics block's item, a headline metric.
const metricCell = (n, key) => state.cmp && state.cmp.nodes[n] ? state.cmp.nodes[n].metrics[key] || null : null;
const blockCell = (n, id, key) => { const b = state.cmp && state.cmp.nodes[n] && state.cmp.nodes[n].blocks[id]; return b ? b[key] || null : null; };
const headlineCell = (id) => state.cmp ? state.cmp.headline[id] || null : null;
const headlineNow = () => (state.current || {}).headline || {};
const signed = (d) => (d > 0 ? "+" : "") + fmt(d);
// What changed between two runs' inputs (blocks.runs.changes), in words.
const changeText = (c) => c.kind === "app" ? `app ${c.from} → ${c.to}` : c.kind === "setting" ? `${c.key} ${fmt(c.from)} → ${fmt(c.to)}`
  : `${c.key}: ${c.from || "none"} → ${c.to || "none"}`;
const changesLine = (r) => { const c = state.cmp ? state.cmp.changes : [];
  return h("p", { class: "small muted", "data-changes": "" }, c.length ? `Compared with ${runLabel_(r)}: ${c.map(changeText).join("; ")}.` : `Same settings and data as ${runLabel_(r)}.`); };
