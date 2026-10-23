"""UI blocks: what a node's view(out) returns (docs/blocks.md).

Every block is a plain dict ({"type": ..., "id": ...}); the page draws them. A view is a
pure function of the node's output, so changing it never re-runs the node.

    def view(out):
        return [
            ui.metrics(),                                   # the node's METRICS, filled from out
            ui.markdown(f"{out['n']} rows held out."),
            ui.chart(out["x"], {"reference": out["y"], "predicted": out["p"]},
                     kind={"reference": "scatter"}, title="Calibration curve"),
            ui.data(out["table"], title="Held-out rows"),
        ]

A block's id (by default its type and position) is how a previous run's version of the same
block is found, to compare with.
"""
from __future__ import annotations

import base64

MAX_ROWS = 200        # a table shows at most this many rows (the total is kept)
MAX_POINTS = 5000     # a chart series keeps at most this many points


def plain(v):
    """numpy, pandas and pyarrow values as plain Python (JSON) values."""
    if hasattr(v, "to_pylist"):            # pyarrow arrays
        return v.to_pylist()
    if hasattr(v, "tolist"):               # numpy arrays and scalars, pandas series
        return v.tolist()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        return v.item()
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


def _block(kind: str, **fields) -> dict:
    return {"type": kind, **{k: v for k, v in fields.items() if v is not None}}


def markdown(text: str, id: str | None = None) -> dict:
    return _block("markdown", text=str(text), id=id)


def metrics(values: dict | None = None, title: str | None = "Metrics", id: str = "metrics") -> dict:
    """The node's metrics. Without values: what its METRICS declares, read from its output
    (labels and goals included); with values {label: number}: those."""
    return _block("metrics", values=plain(values) if values is not None else None, title=title, id=id)


def table(rows, columns=None, title: str | None = None, id: str | None = None) -> dict:
    """rows: a pandas DataFrame, a pyarrow Table, a list of dicts, or a list of rows (with columns)."""
    columns, data = tabulate(rows, columns)
    return _block("table", title=title, columns=columns, rows=plain(data[:MAX_ROWS]), total=len(data), id=id)


def chart(x, series: dict, title: str | None = None, x_label: str | None = None, y_label: str | None = None,
          kind="line", id: str | None = None) -> dict:
    """series: {name: ys} over the shared x; kind: line, scatter, or {name: kind}."""
    if kind not in ("line", "scatter") and not isinstance(kind, dict):
        raise ValueError("ui.chart: kind is line, scatter, or {series: kind}")
    out = [{"name": str(n), "y": plain(list(ys))[:MAX_POINTS],
            "kind": kind.get(n, "line") if isinstance(kind, dict) else kind} for n, ys in series.items()]
    return _block("chart", title=title, x=plain(list(x))[:MAX_POINTS], series=out, x_label=x_label, y_label=y_label, id=id)


def data(value, title: str | None = None, id: str | None = None) -> dict:
    """A data card: a table (DataFrame, pyarrow Table, {column: values}) or a file path. The
    runner describes it: rows, columns and their types, a few rows."""
    return _block("data", title=title, value=value, id=id)


def figure(image, caption: str | None = None, id: str | None = None) -> dict:
    """An image: SVG text, or PNG bytes (e.g. from matplotlib's savefig to a BytesIO)."""
    if isinstance(image, (bytes, bytearray)):
        return _block("figure", media="image/png", data=base64.b64encode(bytes(image)).decode(), caption=caption, id=id)
    return _block("figure", media="image/svg+xml", data=str(image), caption=caption, id=id)


def tabulate(rows, columns=None) -> tuple[list[str], list[list]]:
    """(columns, rows) of anything table-like."""
    if hasattr(rows, "to_pydict") and hasattr(rows, "column_names"):     # pyarrow
        d = rows.to_pydict()
        columns = list(d)
        return columns, [list(r) for r in zip(*(d[c] for c in columns))]
    if hasattr(rows, "itertuples") and hasattr(rows, "columns"):          # pandas
        return [str(c) for c in rows.columns], [list(r) for r in rows.itertuples(index=False)]
    if isinstance(rows, dict):                                            # {column: values}
        columns = [str(c) for c in rows]
        cols = [plain(list(v)) for v in rows.values()]
        return columns, [list(r) for r in zip(*cols)]
    rows = list(rows)
    if rows and isinstance(rows[0], dict):
        columns = columns or list(dict.fromkeys(k for r in rows for k in r))
        return [str(c) for c in columns], [[r.get(c) for c in columns] for r in rows]
    data = [list(r) for r in rows]
    return list(columns or [f"c{i + 1}" for i in range(len(data[0]) if data else 0)]), data
