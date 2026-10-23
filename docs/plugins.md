# Plugins

Most of what an app shows needs no plugin: a node's file documents it and its view makes
its Results (`docs/nodes.md`, `docs/blocks.md`); charts, tables, data cards, comparing runs
and schema checks are built in. A plugin is for what varies by app and cannot be a block:

- **dataset formats**: a Python adapter that turns what the viewer has into what nodes
  read (`docs/dataset-adapters.md`); built-in: `gdb-zip`;
- **views**: an app's own presentation in sandboxed frames, placed on a page
  (`docs/views.md`).

Nothing a plugin has runs in the page itself: adapters run in a worker, views in sandboxed
frames that reach the app only through a checked bridge.

```yaml
# app.yaml
plugins: [gdb-zip, calibration-views]
```

A name is looked up in the app's own `plugins/<name>/` first, then among the built-in
plugins (`src/blocktool/plugins/<name>/`). Each is a directory with a `plugin.yaml`:

| key | meaning |
|---|---|
| `title`, `description` | shown in Settings > App |
| `formats` | `{format: module}`: dataset adapters. A module runs natively (when the app is loaded) and in the ingest worker, so its module level uses the standard library only |
| `views` | `{name: {at, tab, title, code, css, reads, can}}`: sandboxed views |

Plugin files are components of the page like any other (hashed, checked at start-up, view
code pinned in the CSP). Views never change results, so they count in the app's `ui_sha`,
not its `code_sha`; an adapter decides what a dataset holds, so it is in `code_sha`.

Before writing a view, ask whether a block would do: `ui.chart`, `ui.table`, `ui.data` and
`ui.figure` cover most of what a view would draw, and need no JavaScript.
