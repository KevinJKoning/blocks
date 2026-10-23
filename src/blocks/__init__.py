"""blocks: what a node file imports (docs/nodes.md).

A node is one function in one file, named after the file. Its positional parameters are
the nodes and datasets it reads; its keyword-only parameters are its settings, annotated
with Range / Choices / Note. Its docstring documents it, METRICS declares the numbers its
output holds, SCHEMA the datasets it reads, and an optional view(out) turns its output into
UI blocks (blocks.ui).

    from typing import Annotated
    from blocks import Range, ui

    def evaluate(model, features, *, alpha: Annotated[float, Range(0.0001, 10, log=True)] = 0.1):
        ...
        return {"rmse": rmse, "residuals": residuals}

    def view(out):
        return [ui.metrics(), ui.chart(out["x"], {"residual": out["residuals"]})]
"""
from . import ui
from .markers import Choices, Note, Range

__all__ = ["Choices", "Note", "Range", "ui"]
