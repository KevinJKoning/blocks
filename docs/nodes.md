# Nodes: the graph is Python functions

An app is a graph of nodes. A node is **one function in one file**, `nodes/<name>.py`,
named after the file:

```python
"""Closed-form ridge regression of the reference value on the standardized features.

The intercept is the training mean and is not penalized; `alpha` shrinks the coefficients.
"""
from typing import Annotated

import numpy as np
from blocks import Note, Range, ui

GROUP = "Modelling"
METRICS = {"train_rmse": {"label": "train RMSE", "goal": "min"}}


def train(featurize, *, alpha: Annotated[float, Range(0.0001, 10, log=True), Note("ridge penalty")] = 0.1):
    X, y = featurize["Xtr"], featurize["ytr"]
    ...
    return {"intercept": float(y_mean), "coef": w, "train_rmse": rmse}


def view(out):            # optional: its results (docs/blocks.md)
    return [ui.metrics(), ui.chart(...)]


def downloads(out):       # optional: the files it offers (docs/downloads.md)
    return [ui.file("fit.csv", out["table"])]
```

| in the file | means |
|---|---|
| positional parameters | what it reads: another node's output (by the node's name) or a dataset (by its name in app.yaml; the node gets the mounted file's path) |
| keyword-only parameters | its **settings**: literal defaults; `Annotated[type, Range(min, max, step, log=…)]`, `Choices(...)`, `Note("...")` for the controls |
| the return value | its **output**: any Python value (dicts, numpy arrays, pandas or pyarrow tables, dataclasses), kept in memory and passed to the nodes that read it |
| the module docstring | the top of its page (Markdown; the first line is its summary) |
| `METRICS = {key: {label, goal, headline, desc} \| "label"}` | the numbers its output holds (dotted keys into a dict, or attributes), shown before any run without values; `headline: True` ones answer the app's question |
| `SCHEMA = {dataset: {fields: [...]}}` | what a dataset it reads should hold (a subset of Frictionless Table Schema), checked as soon as the data loads |
| `GROUP = "..."` | the group it is drawn in (documented in app.yaml `groups:`) |
| `def view(out)` | how its output is shown: a list of UI blocks |
| `def downloads(out)` | the files it offers for download: a list of `ui.file(name, value)`, made only when downloaded |

The tooling reads all of this with `ast` and never runs node code natively: the graph,
settings and declarations are known before anything runs. Constants must be literals.
Helpers the nodes import can live anywhere in the app outside `nodes/` (e.g. `lib/`).

## Running

Every node runs in Pyodide, in the page's worker (`blocks.graph`). Each output is cached
by a **key**: a hash over the node's code, its helpers, its settings and the keys of its
inputs (a dataset's key is its fingerprint). So:

- changing a setting re-runs that node and what depends on it, nothing else;
- swapping a dataset re-runs the nodes that read it and what depends on them;
- a node whose key did not change comes from the cache;
- a view is rendered from the cached output, so it never re-runs the node.

Nothing runs by itself: a change makes what it reaches stale, and Run runs what is stale,
or, when everything is current, every node again. A failing node is reported with
its traceback, and what depends on it is blocked; a failing view is reported in the node's
results without failing the node.

## What makes the baseline stale

Verification (`docs/runs.md`) compares each node's metrics and the **digest** of its output
(a hash over the value itself, not over how it was made) with the baseline's. The baseline
is current while the app's `code_sha` is: the nodes' code **without** their views,
docstrings and declarations (METRICS, SCHEMA, GROUP), the helpers, the data and the
packages. Restyling a view, rewording a docstring or relabelling a metric never makes it
stale; changing a computation does.

## Agents

An agent iterating on an app edits node files and calls the page's tools
(`window.blocksApp.tools`, also WebMCP): `get_overview`, `get_node`, `set_settings`, `run`,
`read_output`, `sweep`, `list_runs`, `export_run`, `add_run`, `set_reference`,
`check_data`, `query_data`, `get_report`.
