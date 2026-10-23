# Runs as data

A run is something a viewer makes, keeps, and brings back: the app exports a run as a file
(Download run), and loads any number of earlier runs like any other data, to compare with.
There is no built-in "baseline" in the page; a baseline is just a run file named
`baseline`. Comparing results is a feature of each app, not of the repo.

## The run file (`blocks-run/1`)

| key | |
|---|---|
| `format` | `"blocks-run/1"` |
| `name` | its date and time (`2026-10-23T01-31-05`), unless given one |
| `app`, `project`, `title` | which app made it: `project`, or `project/name` for a superseded version |
| `made`, `code_sha`, `runtime` | when, from which code (compute, helpers, data, packages), on which Pyodide/Python/packages |
| `settings`, `changed_settings` | every setting (`node.param`), and those that differ from the defaults |
| `data` | per dataset: `{original: true, sha256}` or `{original: false, file}` |
| `nodes` | per node: `status`, `seconds`, `metrics` (its declared metrics and every number its output holds), `digest` (a hash over its output's value), `blocks` (its results) |
| `headline` | the headline metrics, `{node:key: value}` |

A run file holds blocks, not outputs: outputs can be large, and the blocks are what a viewer
sees. Non-finite numbers are written as `"NaN"` / `"Infinity"` strings.

## In the app (`app/runs.js`)

- **Loading.** The Data modal's Previous runs adds run files, each named after its file.
  Runs of another project are refused. An app may ship runs (`app.yaml runs:`): its own
  (`baseline.run.json` → "baseline") and its superseded versions'
  (`superseded/older/baseline.run.json` → "older/baseline").
- **The reference.** This run is compared with one previous run: the one picked in the
  Data modal, else the one named `baseline`, else the latest.
- **After a run**, a block of this run shows the reference's block with the same node and
  id (`docs/blocks.md`); a node's results say what changed and can switch to the
  reference's blocks; the overview shows the headline against it and the trend.
- **Agents**: `export_run`, `add_run`, `remove_run`, `set_reference`, `show_reference`,
  `get_overview().previous_runs`, `get_node().reference_metrics`.

## The run log

Every run that computed something is logged: the changed settings, swapped data, headline,
which nodes computed, seconds. Linked apps also POST it to the dev server (`runs.jsonl` in
the app's directory); `list_runs`, `apply_run` and `sweep` work from it.

## Verification (tooling only, `verify.py`)

The page never says whether a run "matches": a viewer compares runs; making an app
verifies it.

- `blocks baseline` runs the app headlessly at its defaults and writes the exported run
  file as `baseline.run.json`.
- `blocks run` (a regression test) and `blocks build` run it the same way and compare per
  node: every recorded metric within the app's tolerance (`verify:` in app.yaml), and the
  digest exactly: `match`, `differs`, `no-baseline` or `error`.
- The recorded baseline is used by the page only if the app ships it (`runs:`).
