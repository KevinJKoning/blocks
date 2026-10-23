# Views: an app's own presentation, sandboxed

Builds on `docs/plugins.md`. A view is how an app's own plugin shows something blocks
(`docs/blocks.md`) do not: an interactive chart, a map, a preview of the data that queries
it, a control a reader drags.

## Views are code, outputs are data

A view's code (`.js`, `.css` in its plugin) is app source, read at build time, listed in
the manifest and pinned in the CSP; its data comes from datasets and nodes' outputs,
handed to it at run time over a message bridge. Nothing a node returns ever runs as code.

## Declaration (`plugin.yaml`)

```yaml
# projects/sensor-calibration/plugins/calibration-views/plugin.yaml
views:
  preview:                         # reads a dataset: shown before any run
    at: node:prepare
    title: The measurements
    code: [plot.js, preview.js]    # run in this order; paths inside the plugin
    css: [views.css]
    reads: [measurements]          # a dataset (queried with DuckDB)
    can: [query]
  residuals:                       # reads a node: shown once it has run
    at: node:evaluate
    code: [plot.js, residuals.js]
    reads: [evaluate]              # a node: bridge.read("evaluate") is its output as JSON
```

`at` is `data` (the Data modal), `overview`, `node:<name>` or `group:<name>`. What a view
reads says when it is shown. Checked when the app is loaded:

- every `code`/`css` file exists inside the plugin;
- a view reads datasets (shown **before any run**; every Data modal view does) or nodes'
  outputs (shown once they have run), not both;
- `can` ⊆ `{params, query, download}` in the Data modal, `{query, download}` elsewhere;
- view names are unique across the app's plugins.

A view's frame sits where its page has a `views` block: on a node's page after its
results, before the folded reference material.

## When a view exists

Data modal views mount at start-up, a view of datasets the first time its page is shown,
and a view of nodes once every node it reads has run. A frame is never moved (moving an iframe
reloads it): the report keeps one slot for view frames and only hides and shows them.

## Composing a view document (`app/views.js`)

The host builds each view's `srcdoc` from component bytes, after the integrity check
passes:

```html
<!doctype html><html data-theme="…" data-mode="light|dark"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="…per-view policy…">
<style>{themes.css}</style><style>{view-base.css}</style><style>{each css}</style>
</head><body><div id="view"></div>
<script>{view-bridge.js}</script><script>{each code file}</script>
</body></html>
```

Mounted as `<iframe sandbox="allow-scripts" srcdoc="…">`, never with `allow-same-origin`
(together the two flags would let the frame remove its own sandbox).

### Why this holds under the CSP

1. **Inherited policy.** An about:srcdoc document inherits the parent's CSP, and sandboxing
   does not change that. Each inline script and style in the frame runs only if its hash is
   in the parent's policy, which the build guarantees for exactly the declared files.
2. **Per-view tightening (required).** The frame's `<meta>` CSP adds a second policy, and
   both are enforced, so a frame can only get stricter. It allows only the bridge and *this*
   view's hashes (view A's code cannot run in view B's frame) and sets `connect-src 'none'`.
   This is not optional: in a linked build, Chromium lets a frame under the inherited
   `connect-src 'self'` send requests to the dev server (with `Origin: null`).
3. **Opaque origin.** The view cannot read the parent DOM, the manifest,
   `window.blocksApp`, other components, or storage. It sees only what the bridge hands it.
4. **Shared hash allowlist.** The parent's `script-src` also lists view hashes, so the
   parent *could* run a view script if an exact copy were injected into its DOM. The app
   builds its DOM with `h()` and has no `innerHTML`, `insertAdjacentHTML` or script
   creation, so there is no injection point. Keep it that way.

## The bridge (`window.bridge`)

A `MessageChannel`: when the frame loads, the host posts `{type: "bridge-init"}` with a port;
the bridge accepts the first init whose `event.source === parent`. All traffic then goes
over the port, and the host checks every request against the view's declaration.

| call | needs | does |
|---|---|---|
| `bridge.view` | — | `{name, title, at, reads, can}` |
| `bridge.ready(summary?)` | — | required; call once the first state is **drawn** |
| `bridge.describe(obj)` | — | optional JSON summary of what is on screen, for agents and harvest |
| `bridge.on("update", fn)` | — | new state: per node `status`, `cached`, `metrics`, `shown`, `compare`; per dataset `status`, `original`, `path`, `profile`, `schema`; `reference` and `runs`; `settings`; `headline`. Return a promise that settles when the drawing is done |
| `bridge.on("theme", fn)` | — | theme or mode changed |
| `bridge.read(name)` | in `reads` | a node's output as JSON (numpy arrays as lists, tables as `{columns, rows}`), or a dataset's bytes (up to 64 MB) |
| `bridge.settings()` | — | current settings and their ranges (read-only) |
| `bridge.setSettings(values)` | `can: params` (Data modal only) | same validation as Settings; a change makes what it reaches stale, as any change does |
| `bridge.query(sql, limit)` | `can: query` | DuckDB in the worker on a connection locked to the datasets the view reads |
| `bridge.download(name, data, type)` | `can: download` | the host's download (the sandbox blocks the frame's own) |

The bridge forwards `error`, `unhandledrejection` and `securitypolicyviolation` events, and
reports its size through a `ResizeObserver`.

Answers come from the graph: to compute something for the viewer, make the input a
setting of a node and let it run, rather than re-implementing the node in JS.

## Checks

| check | where | covers views by |
|---|---|---|
| static integrity | `blocks check` / `build.check` | the page's CSP must equal, directive by directive, the policy `build.csp()` writes for its live scripts, styles and view code; each view's own CSP must equal `view_csp()` |
| runtime integrity | `checkIntegrity()` at boot | views are components; srcdocs are composed only after it passes |
| browser enforcement | CSP | an unhashed or altered script in a frame does not run |
| view health | `harvest.drive` | after the run, every view is opened and must be **settled** (ready, and drawn the latest numbered state) with no errors or CSP violations |
| build | `blocks build` | every view healthy, from `file://` with the network blocked |

Every view file must be storable verbatim (no `</script`, `</style`, `<!--`, NUL or CR),
because a CSP hash matches an element's exact text. Vendor libraries into the plugin (the
built app is offline).

## Evidence (spike, 2026-10-20, Playwright 1.64; Chromium 1248, WebKit 2370)

| question | Chromium | WebKit |
|---|---|---|
| srcdoc frame loads under `frame-src 'none'` | yes | yes |
| blob: frame loads under `frame-src 'none'` | no | no |
| frame inherits the parent CSP: hashed script/style apply, unhashed are blocked | yes | yes |
| per-view meta CSP tightens: a script hashed in the parent but not in the frame's meta is blocked | yes | yes |
| frame origin is opaque; `parent.document` and `localStorage` throw `SecurityError` | yes | yes |
| `MessageChannel` handshake | works | works |
| linked build, frame without a meta CSP: `fetch('/ping')` under the inherited `'self'` | **sent** | blocked |
| linked build, frame with meta `connect-src 'none'` | blocked | blocked |
| frame CSP violations visible to Playwright's console | yes | yes |
| removing an iframe and inserting it again reloads it | yes | yes |
