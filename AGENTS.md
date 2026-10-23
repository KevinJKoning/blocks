# Working in this repo (for agents)

Read `ARCHITECTURE.md` and `docs/nodes.md` first. An app here is a graph of Python
functions with UI blocks on top, run in the browser (Pyodide), shipped as one offline
HTML file. Never run node code with native Python, and never add a native data step.

## Iterating on an app

The loop: edit node files, then look at the page or call its tools (`blocks serve`, open
`/<project>/`, `window.blocksApp.tools.<name>(args)` or WebMCP).

- `get_overview` first: question, nodes and their inputs, settings with ranges, datasets,
  headline metrics, previous runs.
- `set_settings({values, run: true})`; `run()` recomputes only what changed (`computed` in
  the answer says what ran); `sweep({grid})` for a grid.
- `get_node`, `read_output({node})`, `get_report` to see a result; `check_data`,
  `query_data` for the data; `list_runs`, `apply_run`, `export_run`, `add_run`,
  `set_reference` to compare.

## Writing nodes

- One function per file in `nodes/`, named after the file. Positional parameters: the
  nodes and datasets it reads, by name. Keyword-only parameters: settings, with literal
  defaults and `Annotated[..., Range(...), Choices(...), Note(...)]`.
- Return plain values: dicts of numbers and arrays, pandas or pyarrow tables, dataclasses.
  Numbers at the top level of a dict are its metrics; declare the ones that matter in
  `METRICS` (`headline: True` for the answer).
- The docstring is the node's Documentation: say what it does and why, in Markdown.
- `SCHEMA` on the node that reads a dataset; `GROUP` to group nodes (document groups in
  app.yaml `groups:`).
- `view(out)` returns `blocks.ui` blocks in the order a reader should see them: an input
  node its data and what it dropped, an output node its answer and its quality. Give a
  block an `id` when other pages refer to it (app.yaml `overview:`).
- Keep nodes small; one concern each. A helper used by several nodes goes outside `nodes/`.

## Making an app

1. `blocks new PROJECT`, or change the current app. Before a change worth comparing:
   `blocks supersede PROJECT NAME`, and ship its baseline with `runs:`.
2. `blocks baseline PROJECT` once it runs; `blocks run PROJECT` after every change (a
   regression test). Re-record the baseline only when results changed on purpose. Views,
   docstrings and METRICS labels never make it stale.
3. `blocks build PROJECT` writes `dist/<project>.html` and verifies it offline.

## Plugins and views

Reach for a plugin only when a block cannot do it (`docs/plugins.md`, `docs/views.md`): a
dataset format, or an interactive view (a control to drag, a map). A view uses
`window.bridge`: `await bridge.init`, `bridge.read(node)`, `bridge.query(sql)`,
`bridge.on("update", fn)` returning the drawing's promise, `bridge.ready()`,
`bridge.describe({...})`. Vendor libraries into the plugin; no inline `style="…"`; no
`</script`, `</style` or `<!--` in view files.

## Conventions

- Datasets live in `projects/<project>/data/`; prefer Parquet (`blocks convert`). Large
  files: `inline: false` (the viewer provides them, checked by sha256).
- Packages must have a Pyodide build (`runtime.lock.json` pins the version).
- Do not commit `runs.jsonl`, `build/` or `dist/`.
- Tests: `.venv/bin/python -m pytest tests` (`-m "not browser"` for the fast ones).
