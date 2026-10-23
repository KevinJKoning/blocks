// blocks view bridge: the first script in every view frame. A view frame is
// sandboxed (opaque origin) and reaches the app only through window.bridge, which talks to
// the host page over a MessageChannel port handed over once by the parent.
(() => {
  "use strict";
  let port = null;
  const queue = [];
  const handlers = { update: [], theme: [] };
  const replies = new Map();
  let seq = 0;
  // Every state the host sends has a number. The view reports which one it has finished
  // drawing: ready() for the first, and each update once its handlers' promises settle,
  // so a headless check can wait until what is on screen matches the app.
  let initSeq = 0, chain = Promise.resolve();
  let initDone;
  const init = new Promise((resolve) => { initDone = resolve; });

  function send(msg, transfer = []) {
    if (port) port.postMessage(msg, transfer); else queue.push([msg, transfer]);
  }
  function request(method, args = {}, transfer = []) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      replies.set(id, { resolve, reject });
      send({ type: "request", id, method, args }, transfer);
    });
  }
  function applyTheme(t) {
    if (!t) return;
    const el = document.documentElement;
    if (t.name) el.setAttribute("data-theme", t.name);
    if (t.mode) el.setAttribute("data-mode", t.mode);
  }
  function onMessage(ev) {
    const m = ev.data || {};
    if (m.type === "init") {
      Object.assign(api.view, m.view);
      api.state = m.state; api.theme = m.theme; initSeq = m.seq;
      applyTheme(m.theme);
      initDone(m.state);
    } else if (m.type === "reply" && replies.has(m.id)) {
      const r = replies.get(m.id); replies.delete(m.id);
      m.ok ? r.resolve(m.value) : r.reject(new Error(m.error));
    } else if (m.type === "update") {
      api.state = m.state;
      chain = chain.then(() => Promise.all(handlers.update.map((f) => f(m.state))))
        .catch((e) => send({ type: "error", message: `update handler: ${text(e)}` }))
        .then(() => send({ type: "rendered", seq: m.seq }));
    } else if (m.type === "theme") {
      api.theme = m.theme;
      applyTheme(m.theme);
      handlers.theme.forEach((f) => f(m.theme));
    }
  }
  // Accept the port once, and only from the parent page.
  window.addEventListener("message", (ev) => {
    if (port || ev.source !== window.parent || !ev.data || ev.data.type !== "bridge-init" || !ev.ports[0]) return;
    port = ev.ports[0];
    port.onmessage = onMessage;
    for (const [m, t] of queue.splice(0)) port.postMessage(m, t);
  });

  const text = (e) => String((e && (e.stack || e.message)) || e);
  window.addEventListener("error", (e) => send({ type: "error", message: text(e.error || e.message) }));
  window.addEventListener("unhandledrejection", (e) => send({ type: "error", message: `unhandled rejection: ${text(e.reason)}` }));
  // Keys typed in the frame never reach the page; Esc is passed on so a modal can close.
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") send({ type: "escape" }); });
  document.addEventListener("securitypolicyviolation", (e) =>
    send({ type: "violation", directive: e.violatedDirective, blocked: e.blockedURI }));
  let lastHeight = 0;
  function reportSize() {
    const h = Math.ceil(document.body ? document.body.scrollHeight : 0);
    if (h !== lastHeight) { lastHeight = h; send({ type: "resize", height: h }); }
  }
  document.addEventListener("DOMContentLoaded", () => {
    new ResizeObserver(reportSize).observe(document.body);
    reportSize();
  });

  const api = {
    view: {},
    state: null,     // {nodes: {name: {status, cached, shown: run|viewed, compare, metrics}}, data: {name: {status, original, file, path, profile, schema}},
                     //  reference, runs (previous runs loaded), settings, headline: [{id, label, goal, now, reference}], busy, ready}
    theme: null,
    init,            // resolves with the first state, once the host has connected
    on(event, fn) { if (handlers[event]) handlers[event].push(fn); return api; },
    // Call once the first state is drawn. Update handlers should return a promise that
    // settles when their drawing is done.
    ready(summary) { send({ type: "ready", seq: initSeq, summary: summary === undefined ? null : summary }); },
    describe(value) { send({ type: "describe", value }); },
    // read(name): a node's output as JSON (views of results), or a dataset's bytes (views shown
    // before a run, which mostly query instead). Only what the view `reads`.
    read: (name) => request("read", { name }),
    settings: () => request("settings"),
    setSettings: (values) => request("setSettings", { values }),   // Data modal views only (at: data, can: params)
    query: (sql, limit) => request("query", { sql, limit }),
    download: (name, data, type) => request("download", { name, data, type }),
  };
  window.bridge = api;
})();
