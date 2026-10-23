# Blocks: the UI on top of the graph

The page is the graph as a DAG next to a report. The DAG is the report's table of
contents: the app's **overview**, each **group**, each **node**. Each is one page, a list
of **blocks** read top to bottom and drawn by one renderer (`templates/app/blocks.js`).
The list comes with the page (`blocktool/docs.py`); some blocks are live, filled from this
session: a dataset's state and check, the settings as controls, a node's results.

## A node's page

1. its docstring: what it does and why;
2. its **settings as live controls** (changing one makes what it reaches stale; Run, and
   its results below change);
3. its **results**: whether they are current (stale, from the cache, failed, blocked), the
   switch to the reference run's results, and the blocks its view made ("Not run yet"
   until it has run), then its log;
4. its views (`docs/views.md`);
5. **About this node**, folded: a card for each dataset it reads (source, size, rows and
   columns, the schema it declares with the data's check), what it reads and what reads
   it, its code. A fold stays open across pages once opened.

Its declared metrics are not listed separately: its results show them, labelled and
declared first, and the DAG shows them from the start.

## A node's results: its view

`view(out)` returns blocks made with `blocks.ui`. It is a pure function of the node's
output, run from the cached output, so changing it never re-runs the node.

| call | block |
|---|---|
| `ui.metrics(values=None, title="Metrics", id="metrics")` | without values: the node's METRICS read from its output, declared first (labels and goals), the other numbers folded under "Other metrics"; with `{label: number}`: those |
| `ui.markdown(text, id=None)` | Markdown |
| `ui.table(rows, columns=None, title=None, id=None)` | a DataFrame, a pyarrow Table, `{column: values}`, a list of dicts or rows; at most 200 rows shown, the total kept |
| `ui.chart(x, series, title=None, x_label=None, y_label=None, kind="line", id=None)` | `series` is `{name: ys}`; `kind` is `line`, `scatter` or `{name: kind}`; at most 5,000 points a series |
| `ui.data(value, title=None, id=None)` | a data card: rows, columns and their types, the first rows (a table) or a file's profile (a path) |
| `ui.figure(image, caption=None, id=None)` | SVG text or PNG bytes (e.g. matplotlib's `savefig` into a `BytesIO`) |

A block's `id` (by default its type and position) is how a previous run's version of it is
found. A node without a view shows its metrics (and its output, if it is a table).

## The overview and a group

The overview: the question and description; the headline metrics (against the reference
run, with Δ); what changed since the reference; blocks taken from nodes' views
(`app.yaml overview: [{node, block}]`, e.g. the calibration curve from `evaluate`); its
views; the app's docs (`docs:`); the trend over previous runs and this session's runs;
then **About this app**, folded: the datasets and the contents. A group: its `doc`
(app.yaml `groups:`), then its nodes with their state and declared metrics.

## Comparison: one rule

A block of a node's results also shows the reference run's block with the same node and
id: metrics add the reference's values and Δ (better or worse by each metric's goal),
charts draw its series dashed underneath, DAG metric lines add Δ. A node's results can
also switch to show the reference's blocks instead. Previous runs keep blocks, not outputs,
so views that read outputs (`docs/views.md`) show this session's run only.
