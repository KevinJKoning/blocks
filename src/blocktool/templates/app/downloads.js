// downloads.js: the files a run makes (docs/downloads.md), apart from runs.
//
// A node's downloads(out) offers files made from its output: the durable artifacts of a
// run, such as the input data with the results appended, or a report with the fitted
// equation. Each node's result names them (blocks.graph); the bytes are made in the worker
// only when the viewer downloads one, or all of them as a zip with the run file they come
// from (run.json). The header's Download is the one place for every download: the active
// run's files and its run file, and this session's runs; a node's results list its own files.

const offering = order.filter((n) => nodes[n].downloads);
// A node's files can be made while the worker holds its output in the active run, current.
const filesReady = (n) => live(n);
async function downloadFile(n, f) {
  const bytes = await call("file", { node: n, name: f.name });
  download(f.name, bytes, f.media);
  return { node: n, name: f.name, bytes: bytes.length };
}
async function downloadAll() {
  if (!current()) throw new Error("run the whole graph first: the zip holds one complete, current run");
  const doc = activeDoc(), name = `${manifest.name}-${doc.name}.zip`;
  const bytes = await call("bundle", { record: doc, zipName: name });
  download(name, bytes, "application/zip");
  return { name, bytes: bytes.length };
}
function downloadRunFile() {
  const doc = runFile();
  download(`${manifest.name}-${doc.name}.run.json`, JSON.stringify(doc, null, 1), "application/json");
  return { name: doc.name };
}
const sessionRuns = () => state.runs.filter((r) => r.from === "session");
// A node's files as links (in its results, and in the Download modal): the worker's, while it
// holds the active run's output; else the names the run file keeps, to make by running.
function fileLinks(n) {
  const s = state.node[n], ready = filesReady(n);
  const files = ready ? s.files || [] : ((shownNode(n) || {}).files || []).map((name) => ({ name }));
  if (ready && s.files_error) return h("div", { class: "card err" }, h("strong", {}, "downloads(out) failed"), h("pre", { class: "log" }, s.files_error));
  if (!files.length) return null;
  return h("ul", { class: "files", "data-files": n }, files.map((f) => h("li", {},
    h("button", { class: "btn link mono", "data-file": f.name, disabled: !ready, title: ready ? `Download ${f.name}` : "Run it first: files are made from current results",
      onclick: () => downloadFile(n, f).catch((e) => console.error(e)) }, f.name),
    h("span", { class: "size" }, [f.title, f.media].filter(Boolean).join(" · ")))));
}
function renderDownload(top, rest, m) {
  const a = activeRun(), doc = activeDoc();
  put(top, h("p", { class: "small muted" }, "Files this app makes from the active run's results, each when you download it. ",
    "Download all puts them in one zip with run.json, the record of the run they come from."));
  for (const n of offering) {
    const st = shownStatus(n);
    put(top, h("section", { class: "download-node", "data-download-node": n },
      h("h3", {}, n, " ", h("span", { class: `pill ${st}` }, stateLabel(n))),
      st === "pending" ? h("p", { class: "small muted" }, "Not run yet.")
        : st === "stale" ? [h("p", { class: "small hint warn" }, "A setting or input changed: Run to make its files again."), fileLinks(n)]
          : st === "kept" ? [h("p", { class: "small hint warn" }, `Run ${runLabel_(a)} keeps these results, not their files: Run to make them.`), fileLinks(n)]
            : fileLinks(n)));
  }
  put(top, h("section", { class: "download-node", "data-download-node": "run" }, h("h3", {}, "Runs"),
    h("ul", { class: "files" },
      h("li", {}, h("button", { class: "btn link mono", "data-action": "download-run", disabled: !(doc && doc.complete),
        title: doc && doc.complete ? "The active run's record: its code, settings, data keys and results" : "Run the whole graph first",
        onclick: () => { try { downloadRunFile(); } catch (e) { m.note.textContent = `Not downloaded: ${e.message}`; } } }, "run.json"),
        h("span", { class: "size" }, a && a.name ? `run ${a.name}` : "the active run")),
      RUNS && sessionRuns().length ? h("li", {}, h("button", { class: "btn link mono", "data-action": "download-session",
        onclick: () => download(`${manifest.name}-runs.json`, JSON.stringify(sessionRuns().map((r) => r.doc), null, 1), "application/json") }, "runs.json"),
        h("span", { class: "size" }, `this session's ${fmtCount(sessionRuns().length, "run")}`)) : null)));
  put(rest, h("button", { class: "btn", "data-action": "download-all", disabled: !current(),
    title: current() ? "Every file and run.json, as a zip" : "Run the whole graph first",
    onclick: () => downloadAll().catch((e) => { m.note.textContent = `Not downloaded: ${e.message}`; }) }, "Download all (.zip)"));
  m.note.textContent = current() ? "" : !state.hasRun && !doc ? "Press Run to make the files." : "Run to make every file of the active run.";
}
