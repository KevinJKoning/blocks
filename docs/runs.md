# Runs as data

A run is something a viewer makes, keeps, and brings back: every run is a run file, a
snapshot of the run, and the page keeps a list of them (this session's, earlier ones, loaded
ones). The page shows one of them, the **active run**, as it was; any others can be
**compared** with it. There is no built-in "baseline" in the page; a baseline is just a run
file named `baseline`.

**One record, one rule** (`blocks/runs.py`, in the runtime library): `record` makes the run
file of a run, `compare` compares two (`compare_many`: one with several), `summarize`
compares many with one. The page's worker calls them after every run; the tooling verifies
with the same `compare`. Nothing else makes or compares runs.

**Runs are a block an app can leave out**: `ui: {runs: false}` in app.yaml removes the run
log, the selection and the comparison blocks (and their agent tools), for a finished app
where a viewer changes data, runs and downloads (`docs/downloads.md`). The active run is
then always the last one; every run still has its run file (Download carries it), and
making the app still verifies against `baseline.run.json`; it just ships no runs (`runs:`)
to compare with.

## The run file (`blocks-run/2`)

What is cheap is kept in full: the code, the settings, every node's results as the page
showed them. What is expensive is kept by hash: the data, large outputs.

| key | |
|---|---|
| `format` | `"blocks-run/2"` |
| `name` | its date and time (`2026-10-23T01-31-05`), unless given one |
| `app`, `project`, `title` | which app made it: `project`, or `project/name` for a superseded version |
| `made`, `code_sha`, `runtime` | when, from which code (compute, helpers, data, packages), on which Pyodide/Python/packages |
| `code` | the app's Python as it was, `{path: source}`: the nodes and the helpers |
| `source`, `ran`, `seconds`, `complete` | who ran it (`ui`, `agent`, `sweep`), the nodes it computed (the rest came from the cache), their seconds, whether every node is done |
| `settings`, `changed_settings` | every setting (`node.param`), and those that differ from the defaults |
| `data` | per dataset: `{key, original, file}`. `key` identifies the bytes: the recorded sha256, a swapped file's sha256, or a format adapter's fingerprint; the graph's cache uses the same key, so two runs read the same data exactly when their keys are equal |
| `nodes` | per node: `status`, `seconds`, `key` (the graph's cache key: its code, settings and inputs), `code` (the hash of what it computes: its file without views, downloads, docstrings and declarations), `metrics` (its declared metrics and every number its output holds), `digest` (a hash over its output's value), `output` (the output as JSON, when it is small: up to 256 KB and 50,000 values; else only the digest), `blocks` (its results), `files` (the names of what downloads(out) offered) |
| `headline` | the headline metrics, `{node:key: value}` |

Two runs of a node with the same `key` have the same output. Non-finite numbers are
written as `"NaN"` / `"Infinity"` strings. A run file of an older format is not read; an
older baseline counts as none until `blocks baseline` records it again.

## Comparing (`compare`)

Per node: a cell for every metric either run has (`value`, `ref`, `delta`, `differs`
beyond the app's tolerance, `better` by the metric's goal), each metrics block's items by
block id, and a verdict: `match` (every metric within tolerance and the same output digest),
`differs`, `no-baseline` (the other run has no result for it), `missing` (the other run has
a result for a node this one does not have: a removed node) or `error` (it did not run).
Also the headline's cells, and what differs between the runs' inputs (`changes`: the app,
its code (which nodes compute differently, which were added or removed), each setting,
each dataset by key).

## In the app (`app/runs.js`)

- **One list.** `state.runs` holds every run file the page knows, each with where it comes
  from: this session (every run that computed something and completed), the dev server's
  run log (`build/<project>/runs.jsonl`, linked builds), the app (`app.yaml runs:`: its own
  `baseline.run.json` → "baseline", a superseded version's
  `superseded/older/baseline.run.json` → "older/baseline"), and files loaded in the run
  log. Runs of another project are refused.
- **The active run.** The page shows one run: after Run, the run it made. **Making a run
  active** reinstates it: its settings (the others back to defaults) and, where it read
  the original data, the original data; every page, the DAG and the headline show its
  results as it kept them. A node's state says where they come from: `done` (current in
  the worker), `kept` (from the run file: the worker does not hold it; Run computes it
  again, with the app's code as it is now, and a line says when that code differs), or
  `stale` (a setting or input changed since). Views read its outputs from the worker, or
  from the run file where it keeps them.
- **Comparing.** Any number of runs can be selected to compare with the active run (the
  shipped baseline is, from the start). The **comparison** block (`docs/blocks.md`) draws
  it: on the overview, what changed and the headline metrics side by side; on a node's
  page, what changed that reaches the node, whether its output is the same, its metrics
  with Δ, and its charts with each selected run's series dashed underneath (a run's
  block with the same node and id). Result blocks themselves draw the active run alone.
- **One page.** The header's **Run log** (its tooltip names the active run and those
  compared) opens the run log: every run, newest first, with where it comes from, what
  differs from the active run, its headline metrics (the best of each marked), and two
  choices: **active** (one) and **compare** (any); remove a loaded one; Load run files….
  The overview shows how many runs there are and links here.
- **Downloads** are the header's alone (`docs/downloads.md`): the active run's files, its
  run file (`run.json`), and this session's runs (`runs.json`).
- **Agents**: `list_runs`, `activate_run`, `set_compare`, `sweep`, `export_run`, `add_run`,
  `remove_run`, `select({runs: true})`, `get_overview().changes`, `get_node().comparison`.

## Verification (tooling only, with `blocks.runs.compare`)

The page never says whether a run "matches": a viewer compares runs; making an app
verifies it.

- `blocks baseline` runs the app headlessly at its defaults and writes the exported run
  file as `baseline.run.json`.
- `blocks run` (a regression test) and `blocks build` run it the same way and compare per
  node: every recorded metric within the app's tolerance (`verify:` in app.yaml), and the
  digest exactly: `match`, `differs`, `missing`, `no-baseline` or `error`.
- `blocks supersede` keeps the baseline with the superseded copy as that version's run
  (`app: project/name`).
- The recorded baseline is used by the page only if the app ships it (`runs:`).
