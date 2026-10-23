// runtime.js: the Python worker, datasets, and running the graph.

// ------------------------------------------------------------------ worker
let worker = null;
let seq = 0;
const pending = new Map();
function call(type, args = {}, transfer = []) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, type, ...args }, transfer);
  });
}
async function runtimeText(name) {
  if (!linked) return textOf(`runtime/${name}`);
  const r = await fetch(manifest.runtime.base + name);
  if (!r.ok) throw new Error(`runtime file ${name}: HTTP ${r.status}`);
  return r.text();
}
async function workerSource() {
  // Load-time adaptation of the pinned ES modules into ONE classic-worker script.
  // Classic, because browsers refuse module workers from blob: URLs on opaque
  // (file://) origins; both build modes take the same path. Three mechanical edits:
  //   1. drop the trailing `export default` / `export {...}` statements;
  //   2. wrap pyodide.mjs in a function that returns its exports;
  //   3. replace `import.meta.url` (used only on Node/fallback paths) with self.location.href.
  const dropMap = (s) => s.replace(/\n\/\/# sourceMappingURL=\S+\s*$/, "\n");
  const asm = dropMap(await runtimeText("pyodide.asm.mjs"))
    .replace(/export\s+default\s+_createPyodideModule;?\s*$/, "\n")
    .replace(/import\.meta\.url/g, "self.location.href");
  const mjs = dropMap(await runtimeText("pyodide.mjs"));
  const m = mjs.match(/export\s*\{([^}]*)\};?/);
  if (!m || /import\.meta/.test(mjs)) throw new Error("unexpected pyodide.mjs module form");
  const ret = m[1].split(",").map((s) => { const [a, b] = s.trim().split(/\s+as\s+/); return `${b || a}: ${a}`; }).join(", ");
  return `"use strict";\n${asm}\nconst __pyodide = (() => {\n${mjs.replace(m[0], `return { ${ret} };`)}\n})();\n${textOf("proto/worker.js")}`;
}
let workerUrl = null;
async function workerBlobUrl() {
  if (!workerUrl) workerUrl = URL.createObjectURL(new Blob([await workerSource()], { type: "text/javascript" }));
  return workerUrl;
}
function runtimeCopies() {   // inline builds hand each worker its own copy of the runtime bytes
  const runtime = {}, transfer = [];
  for (const c of manifest.components) if (c.role === "runtime") {
    const b = bytesOf(c.path).slice(); runtime[c.path.slice(8)] = b.buffer; transfer.push(b.buffer); byteCache.delete(c.path);
  }
  return { runtime, transfer };
}
async function startWorker() {
  setStatus("Preparing the runtime…");
  const url = await workerBlobUrl();
  worker = new Worker(url, { name: "proto-python" });
  worker.onmessage = (ev) => {
    const d = ev.data;
    if (d.id !== undefined && pending.has(d.id)) {
      const p = pending.get(d.id); pending.delete(d.id);
      d.ok ? p.resolve(d.result) : p.reject(new Error(d.error));
    } else if (d.type === "progress") setStatus(d.text);
    else if (d.type === "log") console.debug(`[python ${d.stream}]`, d.text);
    else if (d.type === "fatal") fatal(d.error);
  };
  const project = {}, { runtime, transfer } = linked ? { runtime: {}, transfer: [] } : runtimeCopies();
  for (const c of manifest.components) {
    if (c.path.startsWith("project/")) { const b = bytesOf(c.path).slice(); project[c.path.slice(8)] = b.buffer; transfer.push(b.buffer); }
  }
  const ready = new Promise((resolve, reject) => {
    const prev = worker.onmessage;
    worker.onmessage = (ev) => { if (ev.data.type === "ready") resolve(ev.data); else prev(ev); };
    worker.onerror = (e) => reject(new Error(e.message || "worker failed to start"));
    const pylib = Object.fromEntries(manifest.components.filter((c) => c.path.startsWith("pylib/")).map((c) => [c.path.slice(6), bytesOf(c.path).slice().buffer]));
    call("init", { runtimeBase: linked ? new URL(manifest.runtime.base, location.href).href : null, runtime: linked ? null : runtime,
      project, pylib, graph, packages: manifest.packages, env: manifest.env }, transfer).catch(reject);
  });
  const info = await ready;
  state.python = info.python;
  state.timings = info.timings;
  state.startup = performance.now() / 1000;
  setStatus(`Python ${info.python} ready in ${info.timings.total.toFixed(1)} s`);
}

// ------------------------------------------------------------------ datasets
// Each dataset is a read-only WORKERFS mount in the worker. Sources: the dev server
// (linked builds, HTTP-cached), bytes embedded in the page, or a file the viewer picks.
// Any file dataset can be swapped for another file. Every loaded dataset has a key that
// identifies its bytes (state.data[name].key): the recorded sha256 for the original, a
// swapped file's sha256, or a format adapter's fingerprint. The graph caches by it and run
// files record it (blocks.runs), so two runs read the same data exactly when keys match.
async function mountDataset(name, entries, info) {
  const d = datasets[name];
  state.data[name] = { ...info, status: "loading" };
  refresh();
  try {
    let res = await call("mount", { name, kind: d.kind, entries, targets: d.targets });
    if (res.unreadable) {
      // This browser's worker cannot read the files in place (WebKit on file://): send their bytes.
      const bufs = await Promise.all(entries.map((e) => e.blob.arrayBuffer()));
      res = await call("mount", { name, kind: d.kind, entries: entries.map((e, i) => ({ rel: e.rel, buf: bufs[i] })), targets: d.targets }, bufs);
    }
    state.data[name] = { ...info, status: "mounted", size: res.size, root: res.mounted,
      ...(res.inMemory ? { inMemory: true } : {}) };
  } catch (e) {
    state.data[name] = { ...info, status: "error", note: e.message };
  }
  if (state.data[name].status === "mounted") {
    // What the data holds (rows, columns; a directory's files), for the report.
    try { state.data[name].profile = await call("profile", { path: d.targets[0] }); }
    catch (e) { state.data[name].profile = { error: errorLine(e) }; }
    refresh();
    await checkSchema(name);
  }
  refresh();
}
// ---- a dataset against the schema the node that reads it declares (SCHEMA; blocks.schema),
// checked as soon as it is loaded or swapped.
async function checkSchema(name) {
  const d = datasets[name];
  if (!d.schema || (state.data[name] || {}).status !== "mounted") return null;
  state.data[name].check = { status: "checking" };
  refresh();
  try { state.data[name].check = { status: "done", result: await call("validate", { path: d.targets[0], schema: d.schema }) }; }
  catch (e) { state.data[name].check = { status: "error", error: errorLine(e) }; }
  refresh();
  return state.data[name].check;
}
const schemaProblems = (r) => (r.problems || []).length + (r.fields || []).reduce((s, f) => s + f.problems.length, 0);
// A few words on a dataset's check, or null when it has no schema or is not loaded.
function schemaNote(name) {
  const c = (state.data[name] || {}).check;
  if (!c) return null;
  if (c.status === "checking") return { text: "checking schema…", cls: "" };
  if (c.status === "error" || c.result.ok === null) return { text: "schema not checked", cls: c.status === "error" ? "error" : "" };
  const n = schemaProblems(c.result);
  return n ? { text: `${n} schema problem${n > 1 ? "s" : ""}`, cls: "error" } : { text: "matches its schema", cls: "done" };
}
// ---- datasets with a `format`: converted from the viewer's file by an adapter
// (proto/adapters, packed as a component) in a short-lived ingest worker, then mounted
// like any other dataset. The conversion is cached in the origin-private file system by
// the adapter's fingerprint, so a served app converts a given file once; file:// pages have
// no such storage and convert on every visit. See docs/dataset-adapters.md.
const CACHE_DIR = "blocks-datasets";
// Up-front estimate, measured on a 1 GiB feature class in a 5.3 GiB zip (docs/dataset-adapters.md):
// about 12 s to start the ingest worker and load its packages, then about 20 MB/s of table.
// Once rows arrive, the estimate is replaced by the measured rate.
const INGEST_RATE = 20e6;
const INGEST_START = 12;
const ingestJobs = {};   // name -> progress shown in state.data[name].progress (plain data)
const ingestCtl = {};    // name -> {worker, fail, cancelled}
const cacheKey = (name, fp) => `${manifest.name}.${name}.${fp.slice(0, 32)}`;
async function cacheLookup(key) {
  try {
    const dir = await (await navigator.storage.getDirectory()).getDirectoryHandle(CACHE_DIR);
    const meta = JSON.parse(await (await (await dir.getFileHandle(`${key}.json`)).getFile()).text());
    const file = await (await dir.getFileHandle(`${key}.data`)).getFile();
    return file.size === meta.size ? { file, meta } : null;
  } catch { return null; }   // no entry, or no storage (file://)
}
const estimateSeconds = (d, bytes) => INGEST_START + (bytes || (d.estimate || {}).bytes || d.size) / INGEST_RATE;
function ingestProgress(name, ev) {
  const job = ingestJobs[name];
  if (!job) return;
  const now = performance.now() / 1000;
  if (ev.phase === "converting" && job.phase !== "converting") job.convertStart = now;
  Object.assign(job, { phase: ev.phase, done: ev.done, total: ev.total || job.total });
  if (job.phase === "converting" && job.done > 0 && now > job.convertStart) {
    job.rate = job.done / (now - job.convertStart);
    job.eta = (job.total - job.done) / job.rate;
  } else if (job.phase === "loading") job.eta = estimateSeconds(datasets[name], job.bytes) - (now - job.started);
  if (now - (job.drawn || 0) > 0.25 || ev.phase === "done") { job.drawn = now; refresh(); }
}
function ingestWorker(name) {
  return workerBlobUrl().then((url) => {
    const w = new Worker(url, { name: `proto-ingest-${name}` });
    const waiting = new Map();
    let n = 0;
    const ctl = ingestCtl[name];
    ctl.worker = w;
    ctl.fail = (err) => { for (const p of waiting.values()) p.reject(err); waiting.clear(); };
    if (ctl.cancelled) { w.terminate(); throw new Error("cancelled"); }
    w.onmessage = (ev) => {
      const d = ev.data;
      if (d.id !== undefined && waiting.has(d.id)) { const p = waiting.get(d.id); waiting.delete(d.id); d.ok ? p.resolve(d.result) : p.reject(new Error(d.error)); }
      else if (d.type === "ingest-progress") ingestProgress(name, d);
      else if (d.type === "fatal") ctl.fail(new Error(d.error));
    };
    w.onerror = (e) => ctl.fail(new Error(e.message || "the ingest worker failed"));
    return (type, args = {}, transfer = []) => new Promise((resolve, reject) => {
      const id = ++n; waiting.set(id, { resolve, reject }); w.postMessage({ id, type, ...args }, transfer);
    });
  });
}
async function ingestDataset(name, file, info) {
  const d = datasets[name];
  const job = ingestJobs[name] = { phase: "starting", done: 0, total: (d.estimate || {}).total || 0, unit: d.adapter.unit,
    bytes: (d.estimate || {}).bytes, started: performance.now() / 1000, eta: estimateSeconds(d) };
  const ctl = ingestCtl[name] = {};
  state.data[name] = { ...info, status: "converting", file: info.file, progress: job };
  refresh();
  const t0 = performance.now();
  try {
    const icall = await ingestWorker(name);
    const { runtime, transfer } = linked ? { runtime: null, transfer: [] } : runtimeCopies();
    await icall("init", { role: "ingest", runtimeBase: linked ? new URL(manifest.runtime.base, location.href).href : null, runtime,
      packages: [], env: manifest.env }, transfer);
    job.phase = "reading"; refresh();
    const src = { name, adapter: textOf(d.adapter.path), adapterPath: d.adapter.path };
    if ((await icall("ingestSource", { ...src, file })).unreadable) {
      // The ingest worker cannot read the file in place (WebKit on file://): send its bytes.
      const buf = await file.arrayBuffer();
      await icall("ingestSource", { ...src, buf, file: { name: file.name } }, [buf]);
    }
    const found = await icall("inspect", { options: d.options });
    Object.assign(job, { total: found.total, bytes: found.bytes, eta: estimateSeconds(d, found.bytes) });
    const key = cacheKey(name, found.fingerprint);
    let out = await cacheLookup(key);
    out = out ? { ...out.meta, file: out.file, cached: true, store: "opfs" }
      : await icall("convert", { options: d.options, packages: d.adapter.packages, key, prefix: `${manifest.name}.${name}.` });
    const original = found.fingerprint === d.sha256;
    if (ctl.cancelled) throw new Error("cancelled");
    await mountDataset(name, [{ rel: d.adapter.output, blob: out.file }], { ...info, original, key: found.fingerprint, rows: out.rows, cached: !!out.cached,
      store: out.store, seconds: (performance.now() - t0) / 1000, layer: found.layer,
      note: original ? (info.original ? null : "identical to the recorded dataset (fingerprint)") : "differs from the recorded dataset: runs are modified" });
  } catch (e) {
    if (ingestJobs[name] === job) {   // a job replaced by a newer one (another file picked) reports nothing
      state.data[name] = ctl.cancelled ? { ...info, status: "waiting", note: "conversion cancelled" }
        : { ...info, status: "error", note: errorLine(e) };
      refresh();
    }
  } finally {
    if (ctl.worker) ctl.worker.terminate();   // the ingest worker's heap and packages go with it
    if (ingestJobs[name] === job) { delete ingestJobs[name]; delete ingestCtl[name]; }
  }
  return state.data[name];
}
// The line of a (Python) error worth showing: the exception, not the stack around it.
function errorLine(e) {
  const lines = String((e && e.message) || e).split("\n").map((l) => l.trim()).filter(Boolean);
  const exc = lines.filter((l) => /^[A-Za-z_.]*(Error|Exception|Exit)\b:/.test(l) && !/^PythonError/.test(l)).pop();
  return (exc || lines[0] || "failed").replace(/^(ValueError|RuntimeError): /, "");
}
function cancelIngest(name) {
  const ctl = ingestCtl[name];
  if (!ctl) return false;
  ctl.cancelled = true;
  if (ctl.worker) ctl.worker.terminate();
  if (ctl.fail) ctl.fail(new Error("cancelled"));
  return true;
}
async function loadFormatted(name) {
  const d = datasets[name];
  const hit = await cacheLookup(cacheKey(name, d.sha256));   // a served app converts a given file once
  if (hit) return mountDataset(name, [{ rel: d.adapter.output, blob: hit.file }],
    { original: true, key: d.sha256, source: d.source, rows: hit.meta.rows, cached: true, store: "opfs", seconds: 0 });
  let entries;
  try { entries = await originalEntries(d); } catch (e) { state.data[name] = { status: "error", note: e.message }; refresh(); return; }
  if (!entries) { state.data[name] = { status: "waiting", note: "provide this file to run" }; refresh(); return; }
  await ingestDataset(name, new File([entries[0].blob], d.files[0].rel), { original: true, source: d.source });
}

async function originalEntries(d) {
  if (d.source === "server") {
    return Promise.all(d.files.map(async (f) => {
      const r = await fetch(d.url + f.rel.split("/").map(encodeURIComponent).join("/"), { cache: "no-cache" });
      if (!r.ok) throw new Error(`${d.name}/${f.rel}: HTTP ${r.status}`);
      return { rel: f.rel, blob: await r.blob() };
    }));
  }
  if (d.source === "embedded") return d.files.map((f) => ({ rel: f.rel, blob: new Blob([bytesOf(`data/${d.name}/${f.rel}`)]) }));
  return null;   // "user": the viewer must provide it
}
async function loadOriginal(name) {
  const d = datasets[name];
  if (d.format) return loadFormatted(name);
  let entries;
  try { entries = await originalEntries(d); } catch (e) { state.data[name] = { status: "error", note: e.message }; refresh(); return; }
  if (!entries) { state.data[name] = { status: "waiting", note: "provide this file to run" }; refresh(); return; }
  await mountDataset(name, entries, { original: true, key: d.sha256, source: d.source });
}
async function provideFile(name, file) {
  const d = datasets[name];
  if (d.kind !== "file") throw new Error(`${name} is a directory dataset; only file datasets can be swapped`);
  dataChanged(name);   // results from the old data are stale at once, before the new data is there
  if (d.format) {
    cancelIngest(name);
    const res = await ingestDataset(name, file, { original: false, file: file.name, source: d.source === "user" ? "user" : "file" });
    if (res.status !== "mounted") throw new Error(res.note);
    refresh();
    return res;
  }
  const entry = { rel: d.files[0].rel, blob: file };
  await mountDataset(name, [entry], { original: false, file: file.name, source: "file", note: "checking sha256…" });
  if (state.data[name].status !== "mounted") throw new Error(state.data[name].note);
  // Its key: hashed in the worker, reading the mounted file in chunks (never loaded whole).
  const sha = await call("sha256", { path: `${state.data[name].root}/${entry.rel}` });
  const original = sha === d.files[0].sha256;
  state.data[name] = { ...state.data[name], original, key: original ? d.sha256 : sha,
    note: original ? "identical to the recorded dataset (sha256)" : "differs from the recorded dataset: runs are modified" };
  refresh();
  return state.data[name];
}
async function restoreData(name) {
  dataChanged(name);
  await loadOriginal(name);
  refresh();
}

// ------------------------------------------------------------------ running
// The worker runs the graph: every node whose key (its code, settings and inputs) changed,
// cached ones reported as such, and returns the run file of the graph as it now stands
// (blocks.runs). Nothing runs until Run is pressed (or an agent runs): a change only makes
// what it reaches stale. Run runs what is stale, or, when everything is current, everything.
async function runGraph(source = "ui", rerunAll = false) {
  if (!state.ready || !dataReady()) return { ok: false, error: !state.ready ? "runtime not ready" : "datasets not loaded" };
  if (state.busy) return { ok: false, error: "already running" };
  state.busy = true;
  state.hasRun = true;
  for (const n of order) if (state.node[n].status !== "done") state.node[n] = { ...state.node[n], status: "running" };
  renderHeader(); renderGraph();
  setStatus("Running…");
  let res;
  try { res = await call("run", { settings: state.settings, data: dataRecord(), only: rerunAll ? order : null, source }); }
  catch (e) { res = { nodes: Object.fromEntries(order.map((n) => [n, { status: "error", error: errorLine(e) }])), record: null }; }
  for (const n of order) state.node[n] = { ...res.nodes[n], data: Object.fromEntries(nodeData(n).map((d) => [d.name, dataStatus(d)])) };
  state.current = res.record;
  state.busy = false;
  const failed = order.find((n) => state.node[n].status === "error") || null;
  const computed = res.record ? res.record.ran : [];
  let run = null;
  if (res.record && res.record.complete && computed.length) run = await keepRun(res.record);
  await compareRuns();
  setStatus(progress());
  refresh();
  return { ok: !failed, failed, computed, run };
}
const progress = () => `${order.filter((n) => state.node[n].status === "done").length}/${order.length} nodes current`;
// A change of settings or data: what it reaches is stale until the next run.
function markStale(names) {
  for (const n of descendants(names)) if (["done", "error", "blocked"].includes(state.node[n].status)) state.node[n] = { ...state.node[n], status: "stale" };
  if (state.hasRun) setStatus(progress());
  renderGraph(); notifyViews();
}
const dataChanged = (name) => markStale(order.filter((n) => nodeData(n).some((x) => x.name === name)));
async function setSettings(values) {
  const warnings = [], touched = new Set();
  for (const [k, v] of Object.entries(values)) {
    if (!(k in settingSpec)) throw new Error(`unknown setting ${k} (have: ${Object.keys(settingSpec).join(", ")})`);
    const val = typeof defaults[k] === "number" && typeof v !== "number" ? Number(v) : v;
    const check = validate(k, val);
    if (check.level === "err") throw new Error(`${k}: ${check.text}`);
    if (check.level === "warn") warnings.push(`${k}: ${check.text}`);
    if (same(state.settings[k], val)) continue;
    state.settings[k] = val;
    touched.add(k.split(".")[0]);
  }
  if (touched.size) markStale([...touched]);
  return warnings;
}
async function resetAll() {
  await setSettings({ ...defaults });
  for (const name of swappedData()) await loadOriginal(name);
}

// ------------------------------------------------------------------ this run
// The data a run reads, by key (blocks.runs): the same key the graph's cache uses.
function dataRecord() {
  return Object.fromEntries(manifest.datasets.map((d) => { const x = state.data[d.name] || {};
    return [d.name, { key: x.key || null, original: !!x.original, ...(x.original ? {} : { file: x.file || null }) }]; }));
}
// Every node done and current: the run file records a complete run.
const current = () => state.ready && !state.busy && !!state.current && order.every((n) => state.node[n].status === "done");
const ran = (n) => state.node[n].status === "done" || state.node[n].status === "stale" && !!state.node[n].blocks;
function runFile(name) {
  if (!current()) throw new Error("run the whole graph first: a run file records a complete, current run");
  return name ? { ...state.current, name } : state.current;
}
// A node's output, as JSON (views, agents): this session's; a previous run keeps blocks, not outputs.
async function readOutput(name) {
  if (!(name in nodes)) throw new Error(`no node ${name}`);
  if (!ran(name)) throw new Error(`${name} has not run yet`);
  return call("output", { name });
}
