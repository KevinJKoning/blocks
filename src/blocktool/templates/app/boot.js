// boot.js: the integrity check and start-up.

// ------------------------------------------------------------------ integrity
async function checkIntegrity() {
  if (!(crypto && crypto.subtle)) { state.integrity = { ok: 0, bad: [], unavailable: true }; return; }
  const bad = [];
  let ok = 0;
  for (const c of manifest.components) {
    const el = findComponent(c.path);
    const bytes = c.role === "style" ? new TextEncoder().encode(el ? el.textContent : "") : bytesOf(c.path);
    (await sha256Hex(bytes)) === c.sha256 ? ok++ : bad.push(c.path);
    if (c.role === "runtime") byteCache.delete(c.path);
  }
  state.integrity = { ok, bad };
}

// ------------------------------------------------------------------ boot
window.blocksApp = { manifest, graph, state, tools: {}, whenReady: null, provideFile, cancelIngest };
async function boot() {
  for (const t of tools) window.blocksApp.tools[t.name] = (a) => t.run(a || {});
  buildShell();
  registerWebMCP();
  await checkIntegrity();
  if (state.integrity.bad.length) { fatal(`Integrity check failed for: ${state.integrity.bad.join(", ")}. Refusing to start the runtime.`); return; }
  loadShippedRuns();   // previous runs the app ships (compared after a run)
  mountDataViews();
  showReportViews();
  if (manifest.datasets.some((d) => d.source === "user")) openModal("data");
  await loadRuns();
  try { await startWorker(); } catch (e) { fatal((e && e.stack) || String(e)); return; }
  state.ready = true;
  refresh();
  await Promise.all(manifest.datasets.map((d) => loadOriginal(d.name)));
  refresh();
  if (!dataReady()) openModal("data");
  // Nothing runs until the viewer presses Run (or an agent calls the run tool).
}
window.blocksApp.whenReady = new Promise((resolve) => {
  const go = () => boot().then(resolve, (e) => { fatal(String(e)); resolve(); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go); else go();
});
