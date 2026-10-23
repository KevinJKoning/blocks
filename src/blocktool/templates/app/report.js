// report.js: the report beside the DAG (docs/blocks.md). The DAG is its table of contents:
// the app's overview, a group, or a node. Each is one page, a list of blocks read top to
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
const pageOf = (sel) => sel.kind === "overview" ? manifest.pages.overview
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
  const title = sel.kind === "overview" ? manifest.title : sel.name;
  const status = sel.kind === "node" ? h("span", { class: `pill ${state.node[sel.name].status}` }, stateLabel(sel.name))
    : sel.kind === "group" ? h("span", { class: `pill ${groupStatus(sel.name)}` }, NODE_STATUS[groupStatus(sel.name)]) : null;
  return h("div", {},
    h("div", { class: "crumb small muted" }, sel.kind === "overview" ? "Overview" : [h("button", { class: "btn link", onclick: () => select({ kind: "overview" }) }, manifest.title), " / ",
      sel.kind === "node" && groupOf[sel.name] ? [groupLink(groupOf[sel.name]), " / "] : null, sel.kind === "group" ? "Group" : "Node"]),
    h("h2", {}, title, status));
}
// A node's results: its run state, then the blocks its view made (this run's, or the
// reference's), then its log.
function nodeResults(n, ctx) {
  const s = state.node[n];
  if (!ran(n) && s.status !== "error" && s.status !== "blocked")
    return h("p", { class: "small muted", "data-not-run": "" }, s.status === "running" ? "Running…" : "Not run yet: Run computes it, and what it reads.");
  const rec = shownRecord(n);
  return [runHeader(n), ran(n) ? renderBlocks(rec ? rec.blocks || [] : [], ctx) : null,
    s.log ? h("details", { class: "fold" }, h("summary", {}, "Log"), h("pre", { class: "log" }, s.log)) : null];
}
// A node's run state, and the previous run it is compared with (a switch to show that run's results).
function runHeader(n) {
  const s = state.node[n], out = [];
  if (s.status === "stale") out.push(h("p", { class: "small muted" }, "A setting or input of this node changed; its results are from before."));
  if (s.status === "error") out.push(h("div", { class: "card err" }, h("strong", {}, "Node failed"), h("pre", { class: "log" }, s.error)));
  if (s.status === "blocked") out.push(h("p", { class: "small muted" }, `Not run: ${s.error}.`));
  if (s.cached && s.status === "done") out.push(h("p", { class: "small muted", "data-cached": "" }, "From the cache: nothing it depends on changed since it last ran."));
  if (comparable(n)) {
    const r = reference(), side = shownSide(n);
    out.push(h("div", { class: "compare", role: "group", "aria-label": "Results shown" },
      h("span", { class: "small muted" }, "Showing"),
      [["run", "This run"], ["reference", runLabel_(r)]].map(([k, text]) => h("button", { class: `btn${side === k ? " on" : ""}`,
        "data-action": `show-${k}`, "aria-pressed": String(side === k), onclick: () => setShown(n, k === "reference") }, text)),
      side === "run" ? h("span", { class: "small muted" }, `charts show ${r.name} dashed`) : null), changesLine(r));
  }
  return out;
}
