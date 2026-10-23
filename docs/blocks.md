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
3. its **results** in the active run (`docs/runs.md`): whether they are current (stale,
   kept in the run file, from the cache, failed, blocked) and the blocks its view made
   ("Not run yet" until it has run), then its log;
4. its **comparison** with the runs selected in the run log (when there are some);
5. its views (`docs/views.md`);
6. **About this node**, folded: a card for each dataset it reads (source, size, rows and
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

A block's `id` (by default its type and its place among the blocks of that type: `chart-1`,
`chart-2`) is how another run's version of it is found: give a block an id when its view
may change. A node without a view shows its metrics (and its output, if it is a table).

## The overview and a group

The overview: the question and description; the active run's headline metrics; their
comparison with the selected runs (and what changed); blocks taken from nodes' views
(`app.yaml overview: [{node, block}]`, e.g. the calibration curve from `evaluate`); its
views; how many runs there are, the active one and those compared, linking to the run log; the app's
docs (`docs:`); then **About this app**, folded: the datasets and the contents. The run
log is one block, every run (`docs/runs.md`). A group: its `doc`
(app.yaml `groups:`), then its nodes with their state and declared metrics.

## Comparison: one block

Result blocks draw one run, the active one. Comparing runs is the **comparison** block's
alone (`ui.comparison()`, placed by the page on the overview and each node's page when the
app has runs): the active run against each run selected in the run log, as the worker
compares them (`blocks.runs.compare`). It pairs a node's blocks across runs by node and id:
metrics side by side with Δ (better or worse by each metric's goal), charts with each
selected run's series dashed underneath. Leaving runs out (`ui: {runs: false}`) leaves it
out; nothing else changes.
