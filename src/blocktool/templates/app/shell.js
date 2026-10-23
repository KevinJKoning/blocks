// shell.js: the page layout, the resizable report, themes and the header.

// ------------------------------------------------------------------ layout
const root = document.getElementById("app");
const ui = {};
// The runtime's progress is kept for agents and the Run button's tooltip; the header shows only the button.
function setStatus(t) { state.statusText = t; if (ui.runBtn) ui.runBtn.title = t; }
function fatal(msg) {
  setStatus("Runtime failed to start");
  state.fatal = msg;
  refresh();
}
function buildShell() {
  root.replaceChildren();
  ui.top = h("header", { class: "top" });
  ui.graph = h("div", { class: "graph-wrap" });
  ui.zoomLabel = h("button", { class: "zoom-label", "aria-label": "Fit to window", title: "Fit to window", "data-action": "zoom-fit",
    onclick: () => { state.zoom = "fit"; applyZoom(); ui.graph.scrollTo(0, 0); } }, "Fit");
  ui.zoom = h("div", { class: "zoom glass", role: "group", "aria-label": "Zoom" },
    h("button", { "aria-label": "Zoom out", title: "Zoom out", "data-action": "zoom-out", onclick: () => zoomBy(1 / 1.25) }, "−"),
    ui.zoomLabel,
    h("button", { "aria-label": "Zoom in", title: "Zoom in", "data-action": "zoom-in", onclick: () => zoomBy(1.25) }, "+"));
  ui.graph.addEventListener("wheel", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey)) return;     // plain wheel/trackpad scroll pans; pinch or ⌘/Ctrl zooms
    ev.preventDefault();
    zoomBy(Math.exp(-ev.deltaY * 0.01), { x: ev.clientX, y: ev.clientY });
  }, { passive: false });
  // A click on the drawing's background (not a node or group) shows the app's overview.
  ui.graph.addEventListener("click", (ev) => { if (!ev.target.closest(".node, .pele-cluster-label")) select({ kind: "overview" }, false); });
  enablePan(ui.graph);
  ui.legend = h("div", { class: "legend", "aria-hidden": "true" },
    [["○", "not run", "var(--muted)"], ["…", "running", "var(--run)"], ["✓", "done", "var(--ok)"], ["↻", "stale", "var(--warn)"],
      ["✕", "failed", "var(--err)"], ["–", "blocked", "var(--muted)"]]
      .map(([g, t, c]) => h("span", { cssvars: { "--c": c } }, h("b", {}, g), t)));
  ui.report = h("aside", { class: "report", "aria-label": "Report" });
  ui.splitter = h("div", { class: "splitter", role: "separator", "aria-orientation": "vertical", "aria-label": "Resize report",
    tabindex: 0, title: "Drag to resize · double-click to reset", "data-action": "resize-report" });
  ui.body = h("div", { class: "body" },
    h("section", { class: "graph-pane", "aria-label": "Pipeline" }, ui.graph, ui.zoom, ui.legend),
    ui.splitter, ui.report);
  root.append(h("div", { class: "shell" }, ui.top, ui.body));
  buildModals();
  enableSplitter();
  setReportShown(stored(reportKey, true), false);
  buildHeader(); renderGraph(); renderReport();
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { setReportWidth(state.reportWidth, false); renderGraph(); }, 120);
  });
}
// ---- the report: shown or hidden, and resizable (both remembered in this browser).
const REPORT_DEFAULT = 480, REPORT_MIN = 300, GRAPH_MIN = 320;
const widthKey = "blocks-report-width", reportKey = "blocks-report-shown";
function reportMax() { return Math.max(REPORT_MIN, (ui.body ? ui.body.clientWidth : window.innerWidth) - GRAPH_MIN); }
function setReportShown(on, save = true) {
  state.reportShown = !!on;
  ui.body.classList.toggle("no-report", !on);
  ui.report.hidden = !on;
  ui.splitter.hidden = !on;
  if (ui.reportBtn) { ui.reportBtn.setAttribute("aria-pressed", String(!!on)); ui.reportBtn.title = on ? "Hide the report" : "Show the report"; }
  if (save) store(reportKey, !!on);
  if (ui.drawing) { if (state.zoom === "fit") sizeDrawing(); refreshZoomUi(); }
}
function setReportWidth(w, save) {
  if (w == null) { state.reportWidth = null; ui.body && ui.body.style.removeProperty("--report-w"); }
  else {
    state.reportWidth = Math.round(Math.min(reportMax(), Math.max(REPORT_MIN, w)));
    ui.body.style.setProperty("--report-w", `${state.reportWidth}px`);
  }
  const now = state.reportWidth || REPORT_DEFAULT;
  ui.splitter.setAttribute("aria-valuemin", REPORT_MIN);
  ui.splitter.setAttribute("aria-valuemax", Math.round(reportMax()));
  ui.splitter.setAttribute("aria-valuenow", Math.min(now, Math.round(reportMax())));
  if (save) store(widthKey, state.reportWidth == null ? undefined : state.reportWidth);
  if (state.zoom === "fit" && ui.drawing) { sizeDrawing(); refreshZoomUi(); } else if (ui.drawing) refreshZoomUi();
}
function enableSplitter() {
  const sp = ui.splitter;
  setReportWidth(Number(stored(widthKey, 0)) || null, false);
  let drag = null, frame = 0;
  sp.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    drag = { id: ev.pointerId };
    sp.setPointerCapture(ev.pointerId);
    sp.classList.add("dragging");
    document.body.classList.add("resizing");
  });
  sp.addEventListener("pointermove", (ev) => {
    if (!drag || ev.pointerId !== drag.id) return;
    const right = ui.body.getBoundingClientRect().right;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => setReportWidth(right - ev.clientX, false));
  });
  const end = (ev) => {
    if (!drag || ev.pointerId !== drag.id) return;
    drag = null;
    sp.classList.remove("dragging");
    document.body.classList.remove("resizing");
    setReportWidth(state.reportWidth, true);
  };
  sp.addEventListener("pointerup", end);
  sp.addEventListener("pointercancel", end);
  sp.addEventListener("dblclick", () => setReportWidth(null, true));
  sp.addEventListener("keydown", (ev) => {
    const cur = state.reportWidth || REPORT_DEFAULT, step = ev.shiftKey ? 96 : 24;
    const next = { ArrowLeft: cur + step, ArrowRight: cur - step, Home: reportMax(), End: REPORT_MIN }[ev.key];
    if (next !== undefined) { ev.preventDefault(); setReportWidth(next, true); }
    else if (ev.key === "Enter") { ev.preventDefault(); setReportWidth(null, true); }
  });
}
// ---- themes: the build picks one, in the system's light or dark mode; the viewer may
// pick another theme and mode in Settings (remembered in this browser).
const themeKey = "blocks-theme";
const themeNames = manifest.ui.themes.map((t) => t.name);
const currentTheme = () => ({ name: document.documentElement.getAttribute("data-theme") || manifest.ui.theme,
  mode: document.documentElement.getAttribute("data-mode") });
function setTheme(name, mode) {
  const el = document.documentElement;
  if (themeNames.includes(name)) el.setAttribute("data-theme", name);
  if (mode === "light" || mode === "dark") el.setAttribute("data-mode", mode);
}
function applyTheme(name, mode) {
  setTheme(name, mode);
  store(themeKey, currentTheme());
  renderGraph();
  themeViews();
}
(() => {
  setTheme(manifest.ui.theme, matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const saved = stored(themeKey, null);
  if (saved) setTheme(saved.name, saved.mode);
})();
function themePicker() {
  const t = currentTheme();
  const swatch = h("span", { class: "swatch", "aria-hidden": "true" },
    ["--dag-bg", "--report", "--accent", "--dag-line"].map((v) => h("i", { cssvars: { background: `var(${v})` } })));
  return h("label", { class: "cap select" }, swatch, h("select", { "aria-label": "Theme", "data-action": "theme",
    onchange: (e) => { const [name, mode] = e.target.value.split(":"); applyTheme(name, mode); } },
    manifest.ui.themes.flatMap((x) => ["light", "dark"].map((m) => h("option", { value: `${x.name}:${m}`, selected: x.name === t.name && m === t.mode },
      `${x.label} · ${m === "light" ? "Light" : "Dark"}`)))));
}

// ---- header: the app (its title opens the overview), Data, Settings, Run with its Auto
// switch, Download run, and the report's show/hide switch. Nothing moves while the app loads.
function runLabel() {
  if (state.fatal) return "Unavailable";
  if (!state.ready) return "Loading";
  if (!dataReady()) return "Needs data";
  return state.busy ? "Running…" : "Run";
}
const needsViewerData = () => manifest.datasets.some((d) => ["waiting", "error"].includes((state.data[d.name] || {}).status));
const canRun = () => state.ready && !state.busy && !state.fatal && dataReady();
function runClicked() {
  // Run what is stale or not yet run; if everything is current, run every node again.
  runGraph("ui", order.every((n) => state.node[n].status === "done"));
}
const REPORT_ICON = () => h("svg:svg", { viewBox: "0 0 16 16", width: 16, height: 16, "aria-hidden": "true", class: "icon" },
  h("svg:rect", { x: 1.5, y: 2.5, width: 13, height: 11, rx: 2, fill: "none", stroke: "currentColor", "stroke-width": 1.3 }),
  h("svg:rect", { x: 9.5, y: 3, width: 4.5, height: 10, rx: 1, fill: "currentColor", "fill-opacity": .55 }));
function buildHeader() {
  const open = (name) => h("button", { class: "cap", "data-action": `open-${name}`, onclick: () => openModal(name) }, modals[name].label);
  ui.dataBtn = manifest.datasets.length ? open("data") : null;
  ui.runBtn = h("button", { class: "cap primary", "data-action": "run", title: state.statusText || "", onclick: runClicked });
  ui.autoBox = h("input", { type: "checkbox", "data-action": "auto", checked: state.auto, onchange: (e) => { state.auto = e.target.checked; } });
  ui.auto = h("label", { class: "cap auto", title: "Run what a change makes stale as soon as it is made" }, ui.autoBox, "Auto");
  ui.resultsBtn = h("button", { class: "cap", "data-action": "download-run", title: "This run as a run file: settings, data, and every node's metrics and blocks",
    onclick: () => { try { downloadRun(); } catch (e) { ui.resultsBtn.title = `Download failed: ${e.message}`; } } }, "Download run");
  ui.reportBtn = h("button", { class: "cap icon-only", "data-action": "toggle-report", "aria-label": "Report",
    "aria-pressed": String(state.reportShown), title: state.reportShown ? "Hide the report" : "Show the report",
    onclick: () => setReportShown(!state.reportShown) }, REPORT_ICON());
  ui.top.replaceChildren(
    h("h1", { class: "grow" }, h("button", { class: "title-link", "data-action": "overview", title: "The app's overview",
      onclick: () => { select({ kind: "overview" }); setReportShown(true); } }, manifest.title),
      manifest.version ? h("span", { class: "pill" }, `superseded: ${manifest.version}`) : null,
      linked ? null : h("span", { class: "pill" }, "offline file")),
    h("nav", { class: "pills", "aria-label": "App" }, ui.dataBtn, open("settings")),
    h("div", { class: "pills" }, ui.runBtn, ui.auto, ui.resultsBtn, ui.reportBtn));
  renderHeader();
}
function renderHeader() {
  if (!ui.runBtn) return;
  ui.runBtn.textContent = runLabel();
  ui.runBtn.disabled = !canRun();
  // Every button keeps its place from the start; Download run waits, disabled, for a complete run.
  ui.resultsBtn.disabled = !current();
  ui.autoBox.checked = state.auto;
  // Data asks for attention only when the viewer must act (a file to provide, or one that
  // failed), never while datasets are still loading.
  if (ui.dataBtn) ui.dataBtn.classList.toggle("attention", needsViewerData());
}
// Redraw everything that shows state.
function refresh() { renderHeader(); renderGraph(); renderReport(); renderModals(); notifyViews(); }
