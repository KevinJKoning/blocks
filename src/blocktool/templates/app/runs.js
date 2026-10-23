// runs.js: previous runs as data, and the one this run is compared with (docs/runs.md).
//
// A run file (blocks-run/1) records one complete run, each node's blocks included. The Data
// modal loads any number as previous runs, each named after its file, and an app may ship
// some (app.yaml runs:, e.g. its baseline or a superseded version's). This run is compared
// with one of them, the reference: the one the viewer picked, else the one named
// "baseline", else the latest. The rule is one: a block shows the reference's version of
// the block with the same node and id (blocks.js). Nothing of it shows before a run.

const appId = manifest.id;
state.prev = [];         // previous runs: {name, doc, from: "file" | "app"}
state.reference = null;  // the name the viewer picked as reference (null: the default)
state.compare = {};      // node -> true while the viewer looks at the reference's results instead
const runNameOf = (fileName) => fileName.replace(/\.run\.json$/i, "").replace(/\.json$/i, "");
function addRun(name, doc, from = "file") {
  if (!doc || doc.format !== RUN_FORMAT) throw new Error(`${name}: not a ${RUN_FORMAT} run file`);
  if (doc.project !== manifest.project) throw new Error(`${name}: a run of the project ${doc.project}, not ${manifest.project}`);
  state.prev = state.prev.filter((r) => r.name !== name).concat([{ name, doc, from }]);
}
async function addRunFiles(files) {
  for (const f of files) addRun(runNameOf(f.name), JSON.parse(await f.text()));
  refresh();
}
function removeRun(name) {
  state.prev = state.prev.filter((r) => r.name !== name);
  if (state.reference === name) state.reference = null;
  refresh();
}
function setReference(name) {
  if (name && !state.prev.some((r) => r.name === name)) throw new Error(`no previous run ${name}`);
  state.reference = name || null;
  refresh();
}
const reference = () => state.prev.find((r) => r.name === state.reference) || state.prev.find((r) => r.name === "baseline")
  || [...state.prev].sort((a, b) => String(b.doc.made).localeCompare(String(a.doc.made)))[0] || null;
const sameApp = (r) => r.doc.app === appId;
const runLabel_ = (r) => `${r.name}${sameApp(r) ? "" : ` (${String(r.doc.app).split("/").pop()})`}`;
const runByName = (name) => name === "reference" ? reference() : state.prev.find((r) => r.name === name) || null;
// The reference's record of node n (status, seconds, metrics, digest, blocks), or null.
function refNode(n) {
  const r = reference(), s = r && (r.doc.nodes || {})[n];
  return s && s.status === "done" ? s : null;
}
const refBlock = (n, id) => { const s = refNode(n); return s ? (s.blocks || []).find((b) => b.id === id) || null : null; };
const comparable = (n) => ran(n) && !!refNode(n);
// Which version of a node's results the report shows: "run", "reference", or null before it has run.
const shownSide = (n) => !ran(n) ? null : state.compare[n] && comparable(n) ? "reference" : "run";
const shownRecord = (n) => ({ run: state.node[n], reference: refNode(n) }[shownSide(n)] || null);
function setShown(n, onReference) {
  state.compare[n] = onReference;
  renderReport(); notifyViews();
}
const differs = (v, b) => typeof v === "number" && typeof b === "number" && Math.abs(v - b) > Math.max(tol.abs_tol, tol.rel_tol * Math.abs(b));
const signed = (d) => (d > 0 ? "+" : "") + fmt(d);
// A metric of the reference: from its node record (declared ones are in every run file).
const refMetric = (m) => metricValue(refNode(m.node), m);
// What changed between this run and a previous one: settings, and data that is not the same.
function changesFrom(r) {
  if (!r) return [];
  const out = [];
  for (const k of new Set([...Object.keys(state.settings), ...Object.keys(r.doc.settings || {})])) {
    if (!same(state.settings[k], (r.doc.settings || {})[k])) out.push(`${k} ${fmt((r.doc.settings || {})[k])} → ${fmt(state.settings[k])}`);
  }
  for (const [name, d] of Object.entries(dataRecord())) {
    const theirs = (r.doc.data || {})[name] || {};
    const same_ = d.sha256 && theirs.sha256 ? d.sha256 === theirs.sha256 : d.original && theirs.original;
    if (!same_) out.push(`${name}: ${theirs.file || (theirs.original ? "original" : "other data")} → ${d.file || (d.original ? "original" : "other data")}`);
  }
  if (!sameApp(r)) out.unshift(`app ${r.doc.app} → ${appId}`);
  return out;
}
const changesLine = (r) => { const c = changesFrom(r);
  return h("p", { class: "small muted", "data-changes": "" }, c.length ? `Compared with ${runLabel_(r)}: ${c.join("; ")}.` : `Same settings and data as ${runLabel_(r)}.`); };
function loadShippedRuns() {
  for (const r of manifest.runs || []) {
    try { addRun(r.name, jsonOf(r.path), "app"); } catch (e) { console.warn(`run ${r.name} not loaded`, e); }
  }
}
