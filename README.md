# blocks

Apps as a graph of Python functions, with UI blocks on top, run in the browser (Pyodide)
and shipped as one offline HTML file. Made to be iterated in conversation with an agent:
the core is code that solves the problem; the UI is a thin layer of blocks over its outputs.

```python
# projects/sensor-calibration/nodes/train.py
"""Closed-form ridge regression of the reference value on the standardized features."""
from typing import Annotated
import numpy as np
from blocks import Range, ui

METRICS = {"train_rmse": {"label": "train RMSE", "goal": "min"}}


def train(featurize, *, alpha: Annotated[float, Range(0.0001, 10, log=True)] = 0.1):
    ...                                   # reads featurize's output, in memory
    return {"coef": w, "intercept": b, "train_rmse": rmse}


def view(out):                            # optional: how its Results look
    return [ui.metrics(), ui.chart(...)]
```

- **The graph is the functions' signatures**: positional parameters are inputs (other
  nodes, datasets), keyword-only parameters are settings. No dvc.yaml, no params.yaml.
- **Reactive and cached**: changing `alpha` re-runs `train` and what reads it, in
  milliseconds; everything else comes from the cache. Views re-render without re-running.
- **The page is blocks**: the DAG is the table of contents; each node has a Documentation
  tab (its docstring, data and schema, live settings, code) and a Results tab (its view).
- **Runs are data**: export a run, load earlier ones (a superseded version's baseline), and
  every block shows the reference's next to this run's.
- **Verified**: `blocks build` writes the app as one file and checks, offline, that every
  node reproduces the baseline.

## Quick start

```sh
python3.13 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/playwright install chromium
.venv/bin/blocks serve                        # http://127.0.0.1:8765/
.venv/bin/blocks run                          # every app headlessly, against its baseline
.venv/bin/blocks build sensor-calibration     # -> dist/sensor-calibration.html, verified offline
.venv/bin/python -m pytest tests
```

## Commands

| command | does |
|---|---|
| `blocks serve [--port]` | dev server: projects at `/`, apps at `/<project>/`, rebuilt on every request |
| `blocks new PROJECT` | start a project (two nodes) |
| `blocks baseline [TARGET…]` | run headlessly and record `baseline.run.json` |
| `blocks run [TARGET…]` | run headlessly and verify against the baseline |
| `blocks build [TARGET…] [--no-verify] [--out F]` | one offline file in `dist/`, verified from `file://` with the network blocked |
| `blocks supersede PROJECT NAME` | keep a copy of the current app as `superseded/NAME` |
| `blocks check FILE.html` | static integrity check of a built page |
| `blocks convert SRC DEST.parquet [--format F -o KEY=VALUE]` | convert data to Parquet with DuckDB or a format adapter (in Pyodide) |

## Example projects

- `sensor-calibration`: five nodes (prepare → featurize → train, baseline → evaluate) over a
  small Parquet dataset with a schema; its own plugin adds a data preview that queries the
  dataset and a residual explorer with a threshold to drag.
- `parcels`: a zipped Esri file geodatabase, converted to GeoParquet in the browser by the
  `gdb-zip` plugin, then two nodes: parcel areas (slivers dropped) and the land-use summary.

## Docs

`ARCHITECTURE.md`, `AGENTS.md`, `docs/nodes.md`, `docs/blocks.md`, `docs/runs.md`,
`docs/plugins.md`, `docs/views.md`, `docs/dataset-adapters.md`.

Derived from `compress-final`: the page format, Pyodide worker, dataset mounts and
adapters, sandboxed views and verification carry over; the DVC-shaped pipeline, file-based
stages and fixed report layout are replaced by nodes, in-memory values and blocks.
