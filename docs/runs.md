# Runs as data

A run is something a viewer makes, keeps, and brings back: every run is a run file, and
the page keeps a list of them (this session's, earlier ones, loaded ones) to compare with.
There is no built-in "baseline" in the page; a baseline is just a run file named
`baseline`.

**One record, one rule** (`blocks/runs.py`, in the runtime library): `record` makes the run
file of a run, `compare` compares two, `summarize` compares many with a reference. The
page's worker calls them after every run; the tooling verifies with the same `compare`.
Nothing else makes or compares runs.

## The run file (`blocks-run/1`)

| key | |
|---|---|
| `format` | `"blocks-run/1"` |
| `name` | its date and time (`2026-10-23T01-31-05`), unless given one |
| `app`, `project`, `title` | which app made it: `project`, or `project/name` for a superseded version |
| `made`, `code_sha`, `runtime` | when, from which code (compute, helpers, data, packages), on which Pyodide/Python/packages |
| `source`, `ran`, `seconds`, `complete` | who ran it (`ui`, `agent`, `sweep`), the nodes it computed (the rest came from the cache), their seconds, whether every node is done |
| `settings`, `changed_settings` | every setting (`node.param`), and those that differ from the defaults |
| `data` | per dataset: `{key, original, file}`. `key` identifies the bytes: the recorded sha256, a swapped file's sha256, or a format adapter's fingerprint; the graph's cache uses the same key, so two runs read the same data exactly when their keys are equal |
| `nodes` | per node: `status`, `seconds`, `metrics` (its declared metrics and every number its output holds), `digest` (a hash over its output's value), `blocks` (its results) |
| `headline` | the headline metrics, `{node:key: value}` |

A run file holds blocks, not outputs: outputs can be large, and the blocks are what a viewer
sees. Non-finite numbers are written as `"NaN"` / `"Infinity"` strings.

## Comparing (`compare`)

Per node: each of the reference's metrics as a cell (`value`, `ref`, `delta`, `differs`
beyond the app's tolerance, `better` by the metric's goal), each metrics block's items by
block id, and a verdict: `match` (every metric within tolerance and the same output digest),
`differs`, `no-baseline` (the reference has no result for it) or `error` (it did not run).
Also the headline's cells, and what differs between the runs' inputs (`changes`: the app,
each setting, each dataset by key).

## In the app (`app/runs.js`)

- **One list.** `state.runs` holds every run file the page knows, each with where it comes
  from: this session (every run that computed something and completed), the dev server's
  run log (`runs.jsonl`, linked builds), the app (`app.yaml runs:`: its own
  `baseline.run.json` → "baseline", a superseded version's
  `superseded/older/baseline.run.json` → "older/baseline"), and files loaded in the Data
  modal. Runs of another project are refused.
- **The reference.** This run is compared with one run: the one picked, else the one named
  `baseline`, else the latest that is not this session's.
- **After a run**, a block of this run shows the reference's block with the same node and
  id (`docs/blocks.md`); a node's results say what changed and can switch to the
  reference's blocks; the overview shows the headline against it and every run.
- **Agents**: `list_runs`, `apply_run`, `sweep`, `export_run`, `add_run`, `remove_run`,
  `set_reference`, `show_reference`, `get_overview().changes`, `get_node().comparison`.

## Verification (tooling only, with `blocks.runs.compare`)

The page never says whether a run "matches": a viewer compares runs; making an app
verifies it.

- `blocks baseline` runs the app headlessly at its defaults and writes the exported run
  file as `baseline.run.json`.
- `blocks run` (a regression test) and `blocks build` run it the same way and compare per
  node: every recorded metric within the app's tolerance (`verify:` in app.yaml), and the
  digest exactly: `match`, `differs`, `no-baseline` or `error`.
- The recorded baseline is used by the page only if the app ships it (`runs:`).
