// downloads.js: the files a run makes (docs/downloads.md), apart from runs.
//
// A node's downloads(out) offers files made from its output: the durable artifacts of a
// run, such as the input data with the results appended, or a report with the fitted
// equation. Each node's result names them (blocks.graph); the bytes are made in the worker
// only when the viewer downloads one, or all of them as a zip with the run file they come
// from (run.json). The header's Download opens them all; a node's results list its own.

const offering = order.filter((n) => nodes[n].downloads);
// A node's files can be downloaded while its results are this session's and current.
const filesReady = (n) => state.node[n].status === "done" && !viewed();
async function downloadFile(n, f) {
  const bytes = await call("file", { node: n, name: f.name });
  download(f.name, bytes, f.media);
  return { node: n, name: f.name, bytes: bytes.length };
}
async function downloadAll() {
  if (!current()) throw new Error("run the whole graph first: the zip holds one complete, current run");
  const name = `${manifest.name}-${state.current.name}.zip`;
  const bytes = await call("bundle", { record: state.current, zipName: name });
  download(name, bytes, "application/zip");
  return { name, bytes: bytes.length };
}
// A node's files as links (in its results, and in the Download modal).
function fileLinks(n) {
  const s = state.node[n], files = s.files || [];
  if (s.files_error) return h("div", { class: "card err" }, h("strong", {}, "downloads(out) failed"), h("pre", { class: "log" }, s.files_error));
  if (!files.length) return null;
  const ready = filesReady(n);
  return h("ul", { class: "files", "data-files": n }, files.map((f) => h("li", {},
    h("button", { class: "btn link mono", "data-file": f.name, disabled: !ready, title: ready ? `Download ${f.name}` : "Run it first: files are made from current results",
      onclick: () => downloadFile(n, f).catch((e) => console.error(e)) }, f.name),
    h("span", { class: "size" }, [f.title, f.media].filter(Boolean).join(" · ")))));
}
function renderDownload(top, rest, m) {
  put(top, h("p", { class: "small muted" }, "Files this app makes from a run's results, each when you download it. ",
    "Download all puts them in one zip with run.json, the record of the run they come from."));
  if (viewed()) put(top, h("p", { class: "small hint warn" }, `The report shows run ${viewed().name}; files are made from this session's results.`));
  for (const n of offering) {
    const s = state.node[n];
    put(top, h("section", { class: "download-node", "data-download-node": n },
      h("h3", {}, n, " ", h("span", { class: `pill ${s.status}` }, stateLabel(n))),
      s.status === "pending" ? h("p", { class: "small muted" }, "Not run yet.")
        : s.status === "stale" ? [h("p", { class: "small hint warn" }, "A setting or input changed: Run to make its files again."), fileLinks(n)]
          : fileLinks(n)));
  }
  put(rest, h("button", { class: "btn", "data-action": "download-all", disabled: !current() || viewed(),
    title: current() ? "Every file and run.json, as a zip" : "Run the whole graph first",
    onclick: () => downloadAll().catch((e) => { m.note.textContent = `Not downloaded: ${e.message}`; }) }, "Download all (.zip)"));
  m.note.textContent = current() ? "" : !state.hasRun ? "Press Run to make the files." : "Run what is stale to make every file current.";
}
