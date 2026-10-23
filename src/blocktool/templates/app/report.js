// report.js: the report beside the DAG (docs/blocks.md). The DAG is its table of contents:
// the app's overview, a group, or a node. Each page has a Documentation tab (blocks that
// come with the page, some live) and a Results tab (once it has run). Every page is a list
// of blocks, drawn by blocks.js; this file only decides which.
//
// The report is head | blocks | view slot, and only head and blocks are rebuilt: view
// frames live in the slot, because moving an iframe in the DOM reloads it.

const isRun = (n) => state.node[n].status !== "pending";
function resultsAvailable(sel) {
  if (sel.kind === "overview") return !!state.hasRun;
  if (sel.kind === "group") return groups[sel.name].nodes.some(isRun);
  return isRun(sel.name);
}
const shownTab = () => state.tab === "results" && resultsAvailable(state.sel) ? "results" : "documentation";
// Whether the report shows something that depends on node n (so a run redraws it).
const reportShows = (n) => state.sel.kind === "overview" || (state.sel.kind === "node" && state.sel.name === n)
  || (state.sel.kind === "group" && groups[state.sel.name].nodes.includes(n));

// The blocks of a page, and the node and run they belong to.
function pageBlocks(sel, tab) {
  const pages = manifest.pages;
  if (tab === "documentation") {
    const list = sel.kind === "overview" ? pages.overview : sel.kind === "group" ? pages.groups[sel.name] : pages.nodes[sel.name];
    return { list, ctx: {} };
  }
  if (sel.kind === "overview") return { list: [{ type: "headline", title: headline.length ? "Headline metrics" : null }, { type: "changes" },
    ...(manifest.overview || []).map((o) => ({ type: "pick", node: o.node, block: o.block })),
    { type: "trend", title: state.prev.length ? "This run and previous runs" : null }, { type: "runs", title: `Runs this session (${state.runs.length})` }], ctx: {} };
  if (sel.kind === "group") return { list: [{ type: "nodes", nodes: groups[sel.name].nodes }], ctx: {} };
  const n = sel.name, rec = shownRecord(n);
  return { list: rec ? rec.blocks || [] : [], ctx: { node: n, side: shownSide(n) } };
}
function renderReport() {
  if (!ui.report) return;
  if (!ui.viewSlot) {
    ui.reportHead = h("div", { class: "report-head" }); ui.reportBody = h("div", {}); ui.viewSlot = h("div", { class: "view-slot" });
    ui.report.append(ui.reportHead, ui.reportBody, ui.viewSlot);
  }
  const sel = state.sel, tab = shownTab(), body = h("div", {});
  if (state.fatal) put(body, h("div", { class: "card err" }, h("strong", {}, "The runtime failed to start."), h("pre", { class: "log" }, state.fatal)));
  if (sel.kind === "node" && tab === "results") put(body, runHeader(sel.name));
  const { list, ctx } = pageBlocks(sel, tab);
  if (sel.kind !== "node" || tab !== "results" || ran(sel.name)) put(body, renderBlocks(list, ctx));
  const s = sel.kind === "node" && tab === "results" && state.node[sel.name];
  if (s && s.log) put(body, h("details", { class: "fold" }, h("summary", {}, "Log"), h("pre", { class: "log" }, s.log)));
  const scroll = ui.report.scrollTop;
  ui.reportHead.replaceChildren(reportHead(sel, tab));
  ui.reportBody.replaceChildren(body);
  ui.report.dataset.kind = sel.kind;
  ui.report.dataset.tab = tab;
  showReportViews();
  ui.report.scrollTop = scroll;
}
function reportHead(sel, tab) {
  const title = sel.kind === "overview" ? manifest.title : sel.name;
  const status = sel.kind === "node" ? h("span", { class: `pill ${state.node[sel.name].status}` }, stateLabel(sel.name))
    : sel.kind === "group" ? h("span", { class: `pill ${groupStatus(sel.name)}` }, NODE_STATUS[groupStatus(sel.name)]) : null;
  const tabBtn = (id, label, enabled) => h("button", { role: "tab", class: "tab", id: `tab-${id}`, "data-tab": id,
    "aria-selected": String(tab === id), disabled: !enabled, title: enabled ? null : "Results appear once this has run",
    onclick: () => { state.tab = id; renderReport(); } }, label);
  return h("div", {},
    h("div", { class: "crumb small muted" }, sel.kind === "overview" ? "Overview" : [h("button", { class: "btn link", onclick: () => select({ kind: "overview" }) }, manifest.title), " / ",
      sel.kind === "node" && groupOf[sel.name] ? [groupLink(groupOf[sel.name]), " / "] : null, sel.kind === "group" ? "Group" : "Node"]),
    h("h2", {}, title, status),
    h("div", { class: "tabs", role: "tablist", "aria-label": "Report" },
      tabBtn("documentation", "Documentation", true), tabBtn("results", "Results", resultsAvailable(sel))));
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
