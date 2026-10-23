// blocks worker: Pyodide, the graph (the blocks library), and read-only datasets.
//
// The app script appends this text after the two Pyodide modules to form one classic-worker
// script, so `_createPyodideModule` and `__pyodide.loadPyodide` are in scope here.
//
// Runtime files come from one of two places, never anywhere else:
//   * final (inline) builds: bytes embedded in the page, served from a reserved origin;
//   * experimental (linked) builds: the dev server's /_runtime/ cache on the page's own origin.
// Datasets arrive as Blob/File objects and are mounted with WORKERFS, so DuckDB and
// pandas read them in place; they are never copied into the Pyodide heap.

const EMBED = "https://embedded.invalid/pyodide/";
const files = new Map();
let base = EMBED;
const realFetch = globalThis.fetch.bind(globalThis);
const blocked = (what) => function () { throw new Error(`${what} is disabled in the worker`); };

globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : (input && (input.href || input.url)) || String(input);
  if (url.startsWith(EMBED)) {
    const name = decodeURIComponent(url.slice(EMBED.length).split("?")[0]);
    const data = files.get(name);
    if (!data) throw new Error(`runtime file not embedded: ${name}`);
    const type = name.endsWith(".wasm") ? "application/wasm" : "application/octet-stream";
    return new Response(data, { status: 200, headers: { "Content-Type": type } });
  }
  if (base !== EMBED && url.startsWith(base)) return realFetch(url, init);
  throw new Error(`network access outside the runtime is disabled in the worker (requested ${url})`);
};
globalThis.XMLHttpRequest = blocked("XMLHttpRequest");
globalThis.WebSocket = undefined;
globalThis.EventSource = undefined;
globalThis.importScripts = blocked("importScripts");

const ROOT = "/app";
let py = null;
let session = null;
const post = (msg) => self.postMessage(msg);
const log = (stream) => (text) => post({ type: "log", stream, text });

const GLUE = `
import sys
sys.path.insert(0, "/lib")   # the blocks library: what node files import, and the graph that runs them
from blocks.session import Session
_session = Session("/app", _GRAPH)
`;

// WORKERFS serves every read with one FileReaderSync call (about 1.5 ms each), and GDAL or
// DuckDB issue many small reads: 80,000 for a 52 MB geodatabase table. Each open file
// keeps a few windows; a read inside a window is a copy, a miss at or near a window's end
// (sequential reading) fetches the next window at twice the size, up to 4 MB, and any
// other miss fetches 64 KB. Several windows per file keep interleaved readers (DuckDB
// column chunks, a GDAL table and its index) from evicting each other.
const READAHEAD = { min: 64 << 10, max: 4 << 20, windows: 8 };
function installReadahead() {
  const ops = py.FS.filesystems.WORKERFS.stream_ops, direct = ops.read;
  ops.read = function (stream, buffer, offset, length, position) {
    const node = stream.node;
    if (length >= READAHEAD.max) return direct.call(this, stream, buffer, offset, length, position);
    if (position >= node.size) return 0;
    const wins = stream.readahead || (stream.readahead = []);
    let w = wins.find((x) => position >= x.start && position + length <= x.start + x.bytes.length);
    if (!w) {
      const prev = wins.find((x) => position >= x.start && position <= x.start + x.bytes.length + READAHEAD.min);
      const want = Math.max(length, prev ? Math.min(READAHEAD.max, prev.bytes.length * 2) : READAHEAD.min);
      const end = Math.min(node.size, position + want);
      w = { start: position, bytes: new Uint8Array(new FileReaderSync().readAsArrayBuffer(node.contents.slice(position, end))) };
      if (prev) wins.splice(wins.indexOf(prev), 1);
      wins.unshift(w);
      if (wins.length > READAHEAD.windows) wins.pop();
    } else if (wins[0] !== w) { wins.splice(wins.indexOf(w), 1); wins.unshift(w); }
    const n = Math.min(length, w.start + w.bytes.length - position);
    buffer.set(w.bytes.subarray(position - w.start, position - w.start + n), offset);
    return n;
  };
}

function mkdirs(path) { py.FS.mkdirTree(path); }
function writeTree(root, tree) {
  for (const [path, buf] of Object.entries(tree)) {
    const full = `${root}/${path}`;
    mkdirs(full.slice(0, full.lastIndexOf("/")));
    py.FS.writeFile(full, new Uint8Array(buf));
  }
}
function exists(p) { try { py.FS.lstat(p); return true; } catch { return false; } }

function listFiles(path) {
  const out = [];
  const walk = (p, viaLink) => {
    let st;
    try { st = py.FS.lstat(p); } catch { return; }
    if (py.FS.isLink(st.mode)) {
      if (viaLink) return;
      let real; try { real = py.FS.stat(p); } catch { return; }
      if (py.FS.isDir(real.mode)) { out.push({ path: p.replace(/^\/project\//, ""), size: null, dataset: true }); return; }
      out.push({ path: p.replace(/^\/project\//, ""), size: real.size, dataset: true });
      return;
    }
    if (py.FS.isDir(st.mode)) {
      for (const n of py.FS.readdir(p)) if (n !== "." && n !== ".." && n !== "__pycache__") walk(`${p}/${n}`, viaLink);
    } else out.push({ path: p.replace(/^\/project\//, ""), size: st.size });
  };
  walk(path, false);
  return out;
}

async function init(msg) {
  const t0 = performance.now();
  let lock;
  if (msg.runtimeBase) {
    base = msg.runtimeBase;
    lock = await (await fetch(base + "pyodide-lock.json")).json();
  } else {
    for (const [name, buf] of Object.entries(msg.runtime)) files.set(name, new Uint8Array(buf));
    lock = JSON.parse(new TextDecoder().decode(files.get("pyodide-lock.json")));
  }
  post({ type: "progress", text: "Starting Python…" });
  py = await __pyodide.loadPyodide({
    indexURL: base,
    packageBaseUrl: base,
    stdLibURL: base + "python_stdlib.zip",
    lockFileContents: lock,
    createPyodideModule: _createPyodideModule,
    stdout: log("stdout"),
    stderr: log("stderr"),
    env: { HOME: "/home/pyodide", PYTHONHASHSEED: "0", MPLBACKEND: "Agg", ...(msg.env || {}) },
  });
  installReadahead();
  const t1 = performance.now();
  if (msg.role === "ingest") {   // a dataset ingest worker: no project, packages on demand
    const version = py.runPython("import sys; sys.version.split()[0]");
    post({ type: "ready", python: version, timings: { python: (t1 - t0) / 1000, total: (performance.now() - t0) / 1000 } });
    return;
  }
  post({ type: "progress", text: `Loading ${msg.packages.join(", ")}…` });
  await py.loadPackage(msg.packages, { messageCallback: () => {}, errorCallback: log("stderr") });
  const t2 = performance.now();
  writeTree(ROOT, msg.project);
  writeTree("/lib", msg.pylib || {});
  py.globals.set("_GRAPH", JSON.stringify(msg.graph));
  py.runPython(GLUE);
  session = py.globals.get("_session");
  files.clear();   // embedded runtime bytes are no longer needed
  const version = py.runPython("import sys; sys.version.split()[0]");
  post({ type: "ready", python: version, timings: { python: (t1 - t0) / 1000, packages: (t2 - t1) / 1000, total: (performance.now() - t0) / 1000 } });
}

// Can this worker read a Blob synchronously, as WORKERFS does? WebKit refuses for a page
// opened from file:// (an opaque origin): "Cannot load blob:null/…", then NotReadableError
// inside Pyodide, which is fatal. So check first; the page then sends the bytes instead.
function readable(blob) {
  try { new FileReaderSync().readAsArrayBuffer(blob.slice(0, Math.min(1, blob.size))); return true; } catch { return false; }
}
function rmTree(p) {
  if (!exists(p)) return;
  if (py.FS.isDir(py.FS.lstat(p).mode)) {
    for (const n of py.FS.readdir(p)) if (n !== "." && n !== "..") rmTree(`${p}/${n}`);
    py.FS.rmdir(p);
  } else py.FS.unlink(p);
}
// A dataset is a WORKERFS mount at /_data/<name> (or, from bytes, a copy at /_mem/<name>);
// each app path that uses it is a symlink into it. entries: [{rel, blob}] read in place,
// or [{rel, buf}] written into memory.
function mount({ name, kind, entries, targets }) {
  const at = `/_data/${name}`, mem = `/_mem/${name}`;
  if (!entries.some((e) => e.buf) && !entries.every((e) => readable(e.blob))) return { unreadable: true };
  for (const t of targets) { const p = `${ROOT}/${t}`; if (exists(p)) py.FS.unlink(p); }
  if (exists(at)) { try { py.FS.unmount(at); } catch { /* not mounted */ } } else mkdirs(at);
  rmTree(mem);
  let root = at, size = 0;
  if (entries.some((e) => e.buf)) {
    root = mem;
    for (const e of entries) {
      const full = `${mem}/${e.rel}`;
      mkdirs(full.slice(0, full.lastIndexOf("/")));
      py.FS.writeFile(full, new Uint8Array(e.buf));
      size += e.buf.byteLength;
    }
  } else {
    py.FS.mount(py.FS.filesystems.WORKERFS, { blobs: entries.map((e) => ({ name: e.rel, data: e.blob })) }, at);
    size = entries.reduce((s, e) => s + e.blob.size, 0);
  }
  for (const t of targets) {
    const p = `${ROOT}/${t}`;
    mkdirs(p.slice(0, p.lastIndexOf("/")) || ROOT);
    py.FS.symlink(kind === "dir" ? root : `${root}/${entries[0].rel}`, p);
  }
  return { mounted: root, size, inMemory: root === mem };
}

function readText(path, limit = 4e6) {
  const full = `${ROOT}/${path}`;
  const st = py.FS.stat(full);
  if (st.size > limit) return { truncated: true, size: st.size, text: "" };
  return { text: py.FS.readFile(full, { encoding: "utf8" }), size: st.size };
}

// ------------------------------------------------------------------ dataset ingest
// A dataset with a `format` is converted from the viewer's file by its adapter (a Python
// module from a plugin's `formats`, see docs/plugins.md) in a separate, short-lived worker in the "ingest" role: the
// conversion's packages and heap go away with it. The output goes to the origin-private
// file system (OPFS), which also caches it by fingerprint across visits, or, where OPFS is
// unavailable (file:// pages), to a Blob assembled from 32 MB parts, which Chromium keeps on
// disk when large.
const CACHE_DIR = "blocks-datasets";   // the same as app/runtime.js
const PART = 32 << 20;
async function cacheDir() {
  try { return await (await navigator.storage.getDirectory()).getDirectoryHandle(CACHE_DIR, { create: true }); }
  catch { return null; }   // file:// origins, private modes that refuse storage
}
async function openSink(key, prefix) {
  const dir = await cacheDir();
  if (dir) {
    // one cached conversion per dataset: drop earlier ones under the same prefix
    for await (const name of dir.keys()) if (name.startsWith(prefix) && !name.startsWith(key)) await dir.removeEntry(name).catch(() => {});
    await dir.removeEntry(`${key}.json`).catch(() => {});
    const fh = await dir.getFileHandle(`${key}.data`, { create: true });
    const h = await fh.createSyncAccessHandle();
    h.truncate(0);
    let pos = 0;
    return {
      store: "opfs",
      write(u8) {
        const n = h.write(u8, { at: pos });
        if (n !== u8.byteLength) throw new Error(`storage is full: wrote ${n} of ${u8.byteLength} bytes at ${pos}`);
        pos += n;
      },
      async close(meta) {
        h.flush(); h.close();
        const mf = await (await dir.getFileHandle(`${key}.json`, { create: true })).createSyncAccessHandle();
        mf.truncate(0); mf.write(new TextEncoder().encode(JSON.stringify({ ...meta, size: pos }))); mf.flush(); mf.close();
        return fh.getFile();
      },
      abort() { try { h.close(); } catch { /* closed */ } dir.removeEntry(`${key}.data`).catch(() => {}); },
    };
  }
  const parts = [];
  let chunks = [], held = 0;
  const flush = () => { if (held) { parts.push(new Blob(chunks)); chunks = []; held = 0; } };
  return {
    store: "memory",
    write(u8) { chunks.push(u8.slice()); held += u8.byteLength; if (held >= PART) flush(); },
    async close() { flush(); return new Blob(parts); },
    abort() { parts.length = 0; chunks = []; },
  };
}

const INGEST_GLUE = `
import json
from pyodide.ffi import to_js
_ad = {"__name__": "proto_adapter"}
exec(compile(_ADAPTER_SRC, _ADAPTER_PATH, "exec"), _ad)

class _Sink:
    """A write-only binary file over the worker's sink (for pyarrow.PythonFile)."""
    closed = False
    def __init__(self, js): self.js, self.n = js, 0
    def write(self, b):
        mv = memoryview(b).cast("B")
        if mv.nbytes:
            self.js.write(to_js(mv))
            self.n += mv.nbytes
        return mv.nbytes
    def tell(self): return self.n
    def flush(self): pass
    def close(self): self.closed = True
    def writable(self): return True
    def seekable(self): return False
    def readable(self): return False

def _inspect(path, opts):
    return json.dumps(_ad["inspect"](path, json.loads(opts)))

def _convert(path, opts, sink, progress):
    return json.dumps(_ad["convert"](path, json.loads(opts), _Sink(sink), lambda d, t, p: progress(int(d), int(t or 0), str(p))))
`;
const ingest = { path: null };
// file: the viewer's File, read in place; or buf: its bytes, when this worker cannot read it
// (see readable), written into memory.
function ingestSource({ name, file, buf, adapter, adapterPath }) {
  const rel = file && file.name && /^[^/\\]+$/.test(file.name) ? file.name : "source";
  if (buf) {
    const mem = `/_mem_src/${name}`;
    rmTree(mem); mkdirs(mem);
    py.FS.writeFile(`${mem}/${rel}`, new Uint8Array(buf));
    ingest.path = `${mem}/${rel}`;
  } else {
    if (!readable(file)) return { unreadable: true };
    const at = `/_src/${name}`;
    if (exists(at)) { try { py.FS.unmount(at); } catch { /* not mounted */ } } else mkdirs(at);
    py.FS.mount(py.FS.filesystems.WORKERFS, { blobs: [{ name: rel, data: file }] }, at);
    ingest.path = `${at}/${rel}`;
  }
  py.globals.set("_ADAPTER_SRC", adapter);
  py.globals.set("_ADAPTER_PATH", adapterPath);
  py.runPython(INGEST_GLUE);
  return { path: ingest.path };
}
async function ingestConvert({ options, packages, key, prefix }) {
  if (packages && packages.length) {
    post({ type: "ingest-progress", phase: "loading", done: 0, total: 0 });
    await py.loadPackage(packages, { messageCallback: () => {}, errorCallback: log("stderr") });
  }
  const sink = await openSink(key, prefix);
  const t0 = performance.now();
  try {
    const progress = (done, total, phase) => post({ type: "ingest-progress", phase, done, total });
    const res = JSON.parse(py.globals.get("_convert")(ingest.path, JSON.stringify(options), sink, progress));
    const file = await sink.close({ ...res, seconds: (performance.now() - t0) / 1000 });
    return { ...res, file, store: sink.store, seconds: (performance.now() - t0) / 1000 };
  } catch (e) { sink.abort(); throw e; }
}

const handlers = {
  init,
  mount,
  ingestSource,
  inspect: ({ options }) => JSON.parse(py.globals.get("_inspect")(ingest.path, JSON.stringify(options))),
  convert: ingestConvert,
  // the graph: every node whose key changed (or the named ones), cached ones reported as such
  run: ({ settings, data, only, source }) => JSON.parse(session.run(JSON.stringify(settings), JSON.stringify(data), JSON.stringify(only || null), source || "ui")),
  compare: ({ run, ref }) => JSON.parse(session.compare(JSON.stringify(run), JSON.stringify(ref || null))),
  summarize: ({ runs, ref }) => JSON.parse(session.summarize(JSON.stringify(runs), JSON.stringify(ref || null))),
  output: ({ name }) => JSON.parse(session.output(name)),
  readText: ({ path, limit }) => readText(path, limit),
  readBytes: ({ path }) => py.FS.readFile(`${ROOT}/${path}`),
  list: ({ path }) => listFiles(`${ROOT}/${path || ""}`.replace(/\/$/, "")),
  sha256: ({ path }) => session.sha256_file(path),
  profile: ({ path }) => JSON.parse(session.profile(path)),
  // a dataset checked against the schema the node that reads it declares (blocks.schema)
  validate: ({ path, schema }) => JSON.parse(session.validate(path, JSON.stringify(schema))),
  // allow is passed only when set: Pyodide turns a JS null into JsNull, not None.
  query: ({ sql, limit, allow }) => JSON.parse(allow ? session.query(sql, limit || 200, JSON.stringify(allow)) : session.query(sql, limit || 200)),
};

self.onmessage = async (ev) => {
  const { id, type, ...args } = ev.data;
  try {
    const result = await handlers[type](args);
    if (id !== undefined) post({ id, ok: true, result });
  } catch (err) {
    // WebKit's stack holds no message ("parse@[native code]"): always lead with it.
    const msg = err && err.message !== undefined ? `${err.name || "Error"}: ${err.message}` : String(err);
    const text = err && err.stack && !String(err.stack).includes(String(err.message)) ? `${msg}\n${err.stack}` : String((err && err.stack) || msg);
    post({ id, ok: false, error: text });
    if (type === "init") post({ type: "fatal", error: text });
  }
};
