// blocks browser app. An app is a graph of Python functions (nodes) run in Pyodide, with UI
// blocks on top: the page is the graph as a DAG next to a report, and the DAG is the
// report's table of contents (the overview, each group, each node). A node's page is its
// docstring, its settings as live controls, its results (the blocks its view made of its
// output), and a fold with its data and schema, its links and its code. Settings change
// the graph reactively: only the nodes downstream of a change run again, and a
// view re-renders from cached outputs. An app's own plugins add sandboxed views
// (views.js), never code in this page.
//
// The files in this directory are one script: build.app_script() concatenates them, in the
// order of build.APP_PARTS, inside one strict-mode function scope, so each sees the others'
// names. Top-level statements run in that order; functions are hoisted.
//
// base.js: DOM helpers, the page's components, and the model read from the manifest.

// ------------------------------------------------------------------ DOM helpers
const SVGNS = "http://www.w3.org/2000/svg";
function h(tag, attrs, ...kids) {
  const svg = tag.startsWith("svg:");
  const el = svg ? document.createElementNS(SVGNS, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.setAttribute("class", v);
    else if (k === "text") el.textContent = v;
    else if (k === "cssvars") for (const [n, val] of Object.entries(v)) el.style.setProperty(n, val);
    else if (!svg && k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const fmt = (v) => {
  if (typeof v !== "number") return v === undefined || v === null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v);
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e6)) return v.toExponential(3);
  return Number(v.toPrecision(4)).toString();
};
const put = (el, ...kids) => el.append(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
const fmtBytes = (n) => n == null ? "" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(2)} GB`;
const fmtSec = (s) => s == null ? "—" : s < 1 ? `${(s * 1000).toFixed(0)} ms` : `${s.toFixed(2)} s`;
const fmtCount = (n, unit) => n == null ? "" : `${n.toLocaleString("en-US")} ${unit}${n === 1 ? "" : "s"}`;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);   // params may be lists

// ------------------------------------------------------------------ components
const manifest = JSON.parse(document.getElementById("proto-manifest").textContent);
const elements = new Map();
const indexComponents = () => document.querySelectorAll("[data-path]").forEach((e) => elements.set(e.dataset.path, e));
const findComponent = (path) => elements.get(path) || (indexComponents(), elements.get(path));
const byteCache = new Map();
function fromBase64(s) {
  s = s.replace(/\s+/g, "");
  if (Uint8Array.fromBase64) return Uint8Array.fromBase64(s);
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function bytesOf(path) {
  if (!byteCache.has(path)) {
    const el = findComponent(path);
    if (!el) throw new Error(`component not found: ${path}`);
    const raw = el.textContent;
    byteCache.set(path, el.dataset.encoding === "base64" ? fromBase64(raw) : new TextEncoder().encode(raw));
  }
  return byteCache.get(path);
}
function toBase64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
async function sha256Hex(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}
const textOf = (path) => new TextDecoder().decode(bytesOf(path));
const has = (path) => manifest.components.some((c) => c.path === path);
const jsonOf = (path) => JSON.parse(textOf(path));
const linked = manifest.mode === "linked";
const query = new URLSearchParams(location.search);
const harvest = query.has("harvest");

// ------------------------------------------------------------------ model
const graph = jsonOf("proto/graph.json");
const order = graph.order;
const nodes = graph.nodes;
const settingSpec = manifest.settings || {};          // "node.param" -> {default, type, min, max, step, scale, choices, note}
const tol = manifest.verify;
const defaults = Object.fromEntries(Object.entries(settingSpec).map(([k, v]) => [k, v.default]));
const datasets = Object.fromEntries(manifest.datasets.map((d) => [d.name, d]));
const groups = manifest.groups || {};
const groupNames = Object.keys(groups);
const groupOf = {};
groupNames.forEach((g) => groups[g].nodes.forEach((n) => { groupOf[n] = g; }));
const state = {
  settings: { ...defaults },
  data: {},             // dataset name -> {status: waiting|loading|mounted|error, original, file, size, note, profile, check}
  node: Object.fromEntries(order.map((n) => [n, { status: "pending" }])),
  runs: [],
  // What the report shows: the app's overview, a group or a node; which of its folds are open.
  sel: { kind: "overview", name: null },
  open: {},
  auto: true,           // run what a change makes stale as soon as it is made
  ready: false,
  busy: false,
};
const children = (n) => graph.edges.filter((e) => e.from === n).map((e) => e.to);
const parents = (n) => graph.edges.filter((e) => e.to === n).map((e) => e.from);
function descendants(names) {
  const out = new Set(names);
  const stack = [...names];
  while (stack.length) for (const c of children(stack.pop())) if (!out.has(c)) { out.add(c); stack.push(c); }
  return order.filter((n) => out.has(n));
}
const changedSettings = () => Object.fromEntries(Object.keys(defaults).filter((k) => !same(state.settings[k], defaults[k])).map((k) => [k, state.settings[k]]));
const swappedData = () => Object.keys(state.data).filter((n) => state.data[n].status === "mounted" && !state.data[n].original);
const atDefaults = () => !Object.keys(changedSettings()).length && !swappedData().length;
const nodeSettings = (n) => Object.keys(settingSpec).filter((k) => k.startsWith(`${n}.`));
const nodeData = (n) => nodes[n].deps.filter((d) => d.kind === "dataset").map((d) => datasets[d.name]);
const nodeInputs = (n) => nodes[n].deps.filter((d) => d.kind === "node").map((d) => d.name);
const dataReady = () => manifest.datasets.every((d) => (state.data[d.name] || {}).status === "mounted");

// Metrics the nodes declare (METRICS in their files), shown before any run without values;
// the headline ones answer the app's question. A node's result holds them by key.
const metricDecls = manifest.metrics || [];
const headline = metricDecls.filter((m) => m.headline);
const declaredFor = (n) => metricDecls.filter((m) => m.node === n);
const metricValue = (rec, m) => rec && rec.metrics ? rec.metrics[m.key] : undefined;
const headlineOf = (recs) => Object.fromEntries(headline.map((m) => [m.id, metricValue((recs || {})[m.node], m)]));
const headlineNow = () => headlineOf(state.node);
const better = (m, a, b) => (m.goal === "min" ? a < b : a > b);

function validate(key, value) {
  const s = settingSpec[key] || {};
  if (typeof value === "number" && Number.isNaN(value)) return { level: "err", text: "not a number" };
  if (s.choices && !s.choices.some((c) => same(c, value))) return { level: "warn", text: `not one of ${s.choices.map(fmt).join(", ")}` };
  if ("min" in s && value < s.min) return { level: "warn", text: `below the suggested range ${fmt(s.min)} … ${fmt(s.max)}` };
  if ("max" in s && value > s.max) return { level: "warn", text: `above the suggested range ${fmt(s.min)} … ${fmt(s.max)}` };
  return { level: "ok", text: "min" in s ? `range ${fmt(s.min)} … ${fmt(s.max)}` : "" };
}
// Per-viewer conveniences kept in this browser (the report's width and visibility, the theme).
function stored(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } }
function store(key, value) { try { value === undefined ? localStorage.removeItem(key) : localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } }
