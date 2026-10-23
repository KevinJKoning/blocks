// report.js: the report beside the DAG (docs/blocks.md). The DAG is its table of contents:
// the app's overview, a group, or a node; the header's Run log opens the run log. Each is one page, a list of blocks read top to
// bottom (blocktool/docs.py): what it is, its settings, its results once it has run, its
// views, and a fold with the reference material. Blocks are drawn by blocks.js; this file
// draws the page around them and a node's results.
//
// The report is head | blocks before the views | view slot | blocks after, and the view
// slot is never rebuilt: view frames live in it, because moving an iframe reloads it.

const isRun = (n) => state.node[n].status !== "pending";
function resultsAvailable(sel) {
  if (sel.kind === "overview") return !!state.hasRun;
  if (sel.kind === "group") return groups[sel.name].nodes.some(isRun);
  return isRun(sel.name);
}
const pageOf = (sel) => sel.kind === "overview" ? manifest.pages.overview : sel.kind === "runs" ? manifest.pages.runs
  : sel.kind === "group" ? manifest.pages.groups[sel.name] : manifest.pages.nodes[sel.name];

function renderReport() {
  if (!ui.report) return;
  if (!ui.viewSlot) {
    ui.reportHead = h("div", { class: "report-head" }); ui.reportBody = h("div", {}); ui.viewSlot = h("div", { class: "view-slot" });
    ui.reportTail = h("div", {});
    ui.report.append(ui.reportHead, ui.reportBody, ui.viewSlot, ui.reportTail);
  }
  const sel = state.sel, list = pageOf(sel), at = list.findIndex((b) => b.type === "views");
  const ctx = sel.kind === "node" ? { node: sel.name, side: shownSide(sel.name) } : {};
  // A setting changed here re-renders the page: keep its focus.
  const active = ui.report.contains(document.activeElement) && document.activeElement.closest("[data-param]");
  const focus = active && { key: active.dataset.param, type: document.activeElement.type };
  const body = h("div", {});
  if (state.fatal) put(body, h("div", { class: "card err" }, h("strong", {}, "The runtime failed to start."), h("pre", { class: "log" }, state.fatal)));
  put(body, renderBlocks(at < 0 ? list : list.slice(0, at), ctx));
  const scroll = ui.report.scrollTop;
  ui.reportHead.replaceChildren(reportHead(sel));
  ui.reportBody.replaceChildren(body);
  ui.reportTail.replaceChildren(...renderBlocks(at < 0 ? [] : list.slice(at + 1), ctx).filter(Boolean));
  ui.report.dataset.kind = sel.kind;
  showReportViews();
  ui.report.scrollTop = scroll;
  if (focus) {
    const el = ui.report.querySelector(`[data-param="${CSS.escape(focus.key)}"] input[type="${focus.type}"], [data-param="${CSS.escape(focus.key)}"] select`);
    if (el) el.focus({ preventScroll: true });
  }
}
function reportHead(sel) {
  const title = sel.kind === "overview" ? manifest.title : sel.kind === "runs" ? "Run log" : sel.name;
  const status = sel.kind === "node" ? h("span", { class: `pill ${state.node[sel.name].status}` }, stateLabel(sel.name))
    : sel.kind === "group" ? h("span", { class: `pill ${groupStatus(sel.name)}` }, NODE_STATUS[groupStatus(sel.name)]) : null;
  const v = viewed();
  return h("div", {},
    h("div", { class: "crumb small muted" }, sel.kind === "overview" ? "Overview" : [h("button", { class: "btn link", onclick: () => select({ kind: "overview" }) }, manifest.title), " / ",
      sel.kind === "node" && groupOf[sel.name] ? [groupLink(groupOf[sel.name]), " / "] : null, { group: "Group", node: "Node", runs: "Run log" }[sel.kind]]),
    h("h2", {}, title, status),
    v ? h("div", { class: "viewing", "data-viewing": v.name }, h("span", {}, "Viewing run ", h("strong", { class: "mono" }, runLabel_(v)),
      h("span", { class: "muted" }, ": its results, not this session's.")),
      h("button", { class: "btn", "data-action": "back-to-run", onclick: () => viewRun(null) }, "Back to this run")) : null);
}
// A node's results: its run state, then the blocks its view made (this session's, or the
// viewed run's), the files its downloads(out) offers, then its log.
function nodeResults(n, ctx) {
  const s = state.node[n];
  if (viewed()) {
    const rec = shownRecord(n);
    return rec ? renderBlocks(rec.blocks || [], ctx) : h("p", { class: "small muted" }, `Run ${viewed().name} has no results for ${n}.`);
  }
  if (!ran(n) && s.status !== "error" && s.status !== "blocked")
    return h("p", { class: "small muted", "data-not-run": "" }, s.status === "running" ? "Running…" : "Not run yet: Run computes it, and what it reads.");
  const rec = shownRecord(n), files = nodes[n].downloads && ran(n) ? fileLinks(n) : null;
  return [runHeader(n), ran(n) ? renderBlocks(rec ? rec.blocks || [] : [], ctx) : null,
    files ? h("section", { class: "block block-files" }, h("h3", {}, "Files"), files) : null,
    s.log ? h("details", { class: "fold" }, h("summary", {}, "Log"), h("pre", { class: "log" }, s.log)) : null];
}
// A node's run state, and the run it is compared with.
function runHeader(n) {
  const s = state.node[n], out = [];
  if (s.status === "stale") out.push(h("p", { class: "small muted" }, "A setting or input of this node changed; its results are from before."));
  if (s.status === "error") out.push(h("div", { class: "card err" }, h("strong", {}, "Node failed"), h("pre", { class: "log" }, s.error)));
  if (s.status === "blocked") out.push(h("p", { class: "small muted" }, `Not run: ${s.error}.`));
  if (s.cached && s.status === "done") out.push(h("p", { class: "small muted", "data-cached": "" }, "From the cache: nothing it depends on changed since it last ran."));
  if (comparable(n)) out.push(changesLine(reference()), h("p", { class: "small muted" }, `Δ and dashed series: ${reference().name}.`));
  return out;
}
