"""Annotations on a node's settings (keyword-only parameters):

    *, degree: Annotated[int, Range(1, 8)] = 3
    *, alpha: Annotated[float, Range(0.0001, 10, log=True), Note("ridge penalty")] = 0.1
    *, model: Annotated[str, Choices("ridge", "spline")] = "ridge"

The tooling reads them from the source (ast) to build the settings controls; at run time
they are plain metadata and change nothing.
"""
from __future__ import annotations


class Range:
    def __init__(self, min, max, step=None, log=False):
        self.min, self.max, self.step, self.log = min, max, step, log


class Choices:
    def __init__(self, *values):
        self.values = list(values)


class Note:
    def __init__(self, text: str):
        self.text = text
