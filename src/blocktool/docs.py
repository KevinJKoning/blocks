"""The Documentation of every page, as blocks (docs/blocks.md), built with the page.

A node's page comes from its file: its docstring, the datasets it reads (with the schema
it declares), the metrics it declares, its settings (live controls), what it reads and
what reads it, its code. A group's from app.yaml `groups:`; the overview's from app.yaml
and the app's docs. Blocks marked live are filled by the page: a dataset's state and check,
the current settings.
"""
from __future__ import annotations


def node_page(a: dict, n: str) -> list[dict]:
    g = a["graph"]
    node = g["nodes"][n]
    out = []
    if node["doc"]:
        out.append({"type": "markdown", "text": node["doc"]})
    for d in node["deps"]:
        if d["kind"] == "dataset":
            out.append({"type": "dataset", "dataset": d["name"], "title": "Data in"})
    if node["metrics"]:
        out.append({"type": "metrics", "title": "Metrics it reports", "declared": node["metrics"]})
    if node["settings"]:
        out.append({"type": "settings", "title": "Settings", "keys": [f"{n}.{k}" for k in node["settings"]]})
    reads = [{"node": d["name"]} if d["kind"] == "node" else {"dataset": d["name"]} for d in node["deps"]]
    if reads:
        out.append({"type": "links", "title": "Reads", "items": reads})
    users = [{"node": e["to"]} for e in g["edges"] if e["from"] == n]
    if users:
        out.append({"type": "links", "title": "Read by", "items": users})
    out.append({"type": "code", "title": "Code", "path": node["file"]})
    return out


def group_page(a: dict, name: str) -> list[dict]:
    gr = a["groups"][name]
    out = [{"type": "markdown", "text": gr["doc"]}] if gr["doc"] else []
    return out + [{"type": "contents", "title": "Nodes", "nodes": gr["nodes"]}]


def overview_page(a: dict) -> list[dict]:
    out = []
    if a["question"]:
        out.append({"type": "markdown", "text": f"**{a['question'].strip()}**"})
    if a["description"]:
        out.append({"type": "markdown", "text": a["description"]})
    for d in a["datasets"]:
        out.append({"type": "dataset", "dataset": d, "title": "Data in", "brief": True})
    headline = [m for m in a["metrics"] if m["headline"]]
    if headline:
        out.append({"type": "metrics", "title": "Headline metrics", "declared": headline})
    for doc in a["docs"]:
        out.append({"type": "markdown", "text": a["files"][doc].decode(), "doc": doc})
    out.append({"type": "contents", "title": "Contents", "nodes": a["graph"]["order"]})
    return out


def pages(a: dict) -> dict:
    return {"overview": overview_page(a),
            "groups": {g: group_page(a, g) for g in a["groups"]},
            "nodes": {n: node_page(a, n) for n in a["graph"]["order"]}}
