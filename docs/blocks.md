# Blocks: the UI on top of the graph

The page is the graph as a DAG next to a report. The DAG is the report's table of
contents: the app's **overview**, each **group**, each **node**. Each page has a
**Documentation** tab (there from the start) and a **Results** tab (once it has run), and
every page is a list of **blocks** drawn by one renderer (`templates/app/blocks.js`).

## A node's Results: its view

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

## Documentation: from the node's file

Built with the page (`blocktool/docs.py`):

- **node**: its docstring; a card for each dataset it reads (source, size, rows and
  columns, and the schema it declares with the data's check); the metrics it declares; its
  **settings as live controls** (changing one runs what it reaches); what it reads and what
  reads it; its code;
- **group**: its `doc` (app.yaml `groups:`) and its nodes;
- **overview**: the question and description, the datasets, the headline metrics, the
  app's docs (`docs:`), the contents.

## The overview's and a group's Results

The overview shows the headline metrics (against the reference run, with Δ), what changed
since the reference, blocks taken from nodes' views (`app.yaml overview: [{node, block}]`,
e.g. the calibration curve from `evaluate`), the trend over previous runs, and this
session's runs. A group shows its nodes' state and declared metrics.

## Comparison: one rule

A block of a node's Results also shows the reference run's block with the same node and
id: metrics add the reference's values and Δ (better or worse by each metric's goal),
charts draw its series dashed underneath, DAG metric lines add Δ. A node's Results can
also switch to show the reference's blocks instead. Previous runs keep blocks, not outputs,
so views that read outputs (`docs/views.md`) show this session's run only.
