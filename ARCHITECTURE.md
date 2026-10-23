# Architecture

## What this makes

An **app**: a problem decomposed into a graph of Python functions (nodes), with UI blocks
on top, run in the browser (Pyodide) and shipped as one offline HTML file. It is meant to
be iterated in conversation with an agent: the core is code (the nodes and their
documentation), and everything shown is a layer of blocks over their outputs.

## Principles

- **A node is a function in a file** (`docs/nodes.md`). Its positional parameters are what
  it reads (nodes, datasets), its keyword-only parameters its settings, its return value its
  output; its docstring, `METRICS`, `SCHEMA` and `GROUP` document and declare it; `view(out)`
  presents it. The graph comes from the signatures, read with `ast`, never run natively.
- **Values pass in memory and are cached by key**: a hash over a node's code, settings and
  inputs' keys. A change re-runs only what it reaches; with Auto on it runs at once. Views
  render from cached outputs and never re-run a node.
- **Every page is a list of blocks** (`docs/blocks.md`): the overview, each group and each
  node, read top to bottom. The list is built with the page; some blocks are live (the
  settings as controls, a node's results, made by its view). One renderer draws every block.
- **Comparison is one rule**: a block of this run shows the reference run's block with the
  same node and id. Runs are data (`docs/runs.md`): files that hold settings, metrics,
  output digests and blocks.
- **Plugins only for what cannot be a block**: dataset formats (Python adapters) and an
  app's own sandboxed views (`docs/plugins.md`). Nothing a plugin has runs in the page.
- **All app code runs in Pyodide.** Native Python only reads, packs, serves and drives a
  headless browser; even data conversion (`blocks convert`) and verification runs go
  through Pyodide in Chromium.
- **One page format, two builds**: a *linked* build (while an app is made) takes the
  runtime, pele and data from the dev server; an *inline* build (`blocks build`) embeds
  them and makes no network requests. Every component is hashed and checked at start-up;
  the app script is the only live script, pinned in the CSP.
- **Data is read in place**: datasets are WORKERFS mounts, read by DuckDB and pyarrow
  without copying; a dataset with a `format` is converted by an adapter first. Where the
  worker cannot read a Blob synchronously (WebKit on a `file://` page), the page sends the
  bytes and the dataset is a copy in the worker's memory instead.
- **Verification is the tooling's, never the page's**: `blocks run` and `blocks build`
  compare each node's metrics (within tolerance) and output digest with the baseline. The
  baseline is current while `code_sha` is: the nodes' code without views, docstrings and
  declarations, the helpers, the data, the packages.

## Layout

```
projects/<project>/
  app.yaml                 title, question, description, data, groups, plugins, overview, docs, runs, verify
  nodes/<name>.py          one node each
  lib/…, *.py              helpers the nodes import
  data/                    the project's datasets
  plugins/<name>/          the app's own plugins (views, formats)
  baseline.run.json        recorded by blocks baseline
  superseded/<name>/       earlier versions (blocks supersede), same shape, reading the project's data
src/blocks/                the library nodes import, and the graph that runs them (shipped into Pyodide)
src/blocktool/             the tooling: spec, docs, build, server, harvest, verify, cli, plugins, templates
```

## Modules

| module | role |
|---|---|
| `blocks/__init__.py`, `markers.py` | what a node imports: `Range`, `Choices`, `Note`, `ui` |
| `blocks/ui.py` | UI blocks a view returns |
| `blocks/graph.py` | the executor: loads nodes, keys, cache, runs, metrics, digests, views → blocks |
| `blocks/session.py` | what the worker calls: run, read an output, profile and validate data, DuckDB queries |
| `blocks/schema.py` | table schemas: check a declaration (natively), validate data (in Pyodide) |
| `blocktool/spec.py` | reads an app: nodes and the graph from signatures, settings, declarations, datasets, views, runs, `code_sha`, `ui_sha` |
| `blocktool/docs.py` | every page as a list of blocks |
| `blocktool/build.py` | packs a page: manifest (graph, pages, settings) + inert components, the app script live; `unpack`, `check` |
| `blocktool/server.py` | `blocks serve`: projects index, apps rebuilt per request, `/_runtime/`, `/_data/`, runs API |
| `blocktool/harvest.py`, `verify.py` | headless runs (baseline, regression, offline build), comparing run files |
| `blocktool/plugins.py`, `plugins/gdb-zip/` | plugins: formats and views |
| `blocktool/templates/app/*.js` | the app script: `base` (model), `runtime` (worker, datasets, running, run files), `runs` (previous runs, reference), `shell` (layout, header), `dag`, `blocks` (renderer), `report` (which blocks), `render`, `views`, `modals`, `tools`, `boot` |
| `blocktool/templates/worker.js` | the Pyodide worker: mounts with read-ahead, the session, ingest of formats |

## The page

- **Header**: the title (opens the overview), Data (datasets and previous runs), Settings
  (Graph: every node's settings; App: theme, report, plugins, earlier versions, this
  build), Run with its Auto switch, Download run, the report's show/hide switch.
- **DAG**: nodes in their groups, each with its state (`○ not run` from the start), the data
  it reads (rows, size, schema check) and its declared metrics (values and Δ after a run).
  A node selects that node, a group's label its group, the background the overview.
- **Report**: crumb, title, the page's blocks (a node: docstring, settings, results, views,
  then its data, links and code folded).

## Data flow of a run

1. The page starts a classic worker (Pyodide's modules + `worker.js`), writes the app's
   files to `/app` and the blocks library to `/lib`, and mounts the datasets (a `format`
   dataset converted first), profiling and checking each.
2. A run sends the settings and the datasets' keys; `blocks.graph` walks the nodes in
   order, reusing every output whose key is unchanged and calling the rest with their
   inputs' values and their settings, then makes each result: status, seconds, metrics,
   digest, blocks (its view, filled in: metric labels, data profiles).
3. The page draws the results; a run that computed something is logged (and posted to the
   dev server's run log unless the page was opened with `?harvest=1`).
