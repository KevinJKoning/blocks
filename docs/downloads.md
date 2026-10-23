# Downloads: the files a run makes

A run's results are for looking at (blocks) and comparing (runs, `docs/runs.md`); its
**downloads** are what a viewer takes away: the input data with the results appended, a
report with the fitted equation, a table to open elsewhere. They are separate from runs:
an app without runs (`ui: {runs: false}`) still offers them.

## A node's `downloads(out)`

Like `view(out)`, an optional function of the node's output, returning files:

```python
# projects/sensor-calibration/nodes/calibrated.py
def downloads(out):
    return [ui.file("calibrated.csv", out["table"], title="every reading with its calibrated value"),
            ui.file("calibration.md", report_text(out), title="the curve's equation and quality")]
```

`ui.file(name, value, title=None)` (`blocks/ui.py`): by the name's extension, a table
(DataFrame, pyarrow Table, `{column: values}`, a list of dicts) as `.csv`, `.tsv`,
`.parquet` or `.json` (missing values are empty CSV cells); text as any file; other
JSON-able values as `.json`; bytes as they are. Names are letters, digits, `.`, `-`, `_`,
unique within the node.

Like a view, `downloads` never changes results: it is left out of `code_sha`, so changing
it never makes the baseline stale.

## When files are made

After a node runs, `blocks.graph` calls its `downloads(out)` and keeps the files with the
output; the node's result (and its run file) names them. The bytes are made in the worker
only when a viewer downloads a file: they are never part of a run file, which keeps blocks,
not outputs. A failing `downloads` is reported on the node's page, never fails the node.

## In the app (`app/downloads.js`)

- The header's **Download** is the one place for downloads. It opens every node's files:
  each one alone, or **Download all (.zip)**: every file and `run.json`, the run file of
  the run they come from, so a download always carries its provenance; and the active
  run's file alone (`run.json`) and this session's runs (`runs.json`).
- A node's results list its files too.
- Files come from the active run's results while the worker holds them, current: a stale
  node's wait for Run, and so do a run's kept results (`docs/runs.md`: a run file keeps
  results, not files). The zip waits for all of them.
- Agents: `list_files`, `read_file({node, name})` (text back, or the size), `download_all`.
