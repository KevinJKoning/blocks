"""Every page of the report as one list of blocks (docs/blocks.md), built with the page.

A page reads top to bottom: what it is (a docstring, the app's question), what changes it
(settings, live controls), what it found (`results`: the node's run, filled by the page),
where its views go (`views`), and a fold with the reference material (the data it reads
and its schema check, what it reads and what reads it, its code). Blocks marked live are
filled by the page from this session's state.
"""
from __future__ import annotations


def node_page(a: dict, n: str) -> list[dict]:
    g = a["graph"]
    node = g["nodes"][n]
    out = [{"type": "markdown", "text": node["doc"]}] if node["doc"] else []
    if node["settings"]:
        out.append({"type": "settings", "title": "Settings", "keys": [f"{n}.{k}" for k in node["settings"]]})
    out += [{"type": "results", "title": "Results"}, {"type": "views"}]
    about = [{"type": "dataset", "dataset": d["name"], "title": "Data in"} for d in node["deps"] if d["kind"] == "dataset"]
    reads = [{"node": d["name"]} if d["kind"] == "node" else {"dataset": d["name"]} for d in node["deps"]]
    if reads:
        about.append({"type": "links", "title": "Reads", "items": reads})
    users = [{"node": e["to"]} for e in g["edges"] if e["from"] == n]
    if users:
        about.append({"type": "links", "title": "Read by", "items": users})
    about.append({"type": "code", "title": "Code", "path": node["file"]})
    return out + [{"type": "fold", "id": "about-node", "title": "About this node", "blocks": about}]


def group_page(a: dict, name: str) -> list[dict]:
    gr = a["groups"][name]
    out = [{"type": "markdown", "text": gr["doc"]}] if gr["doc"] else []
    return out + [{"type": "nodes", "title": "Nodes", "nodes": gr["nodes"]}, {"type": "views"}]


def overview_page(a: dict) -> list[dict]:
    out = []
    if a["question"]:
        out.append({"type": "markdown", "text": f"**{a['question'].strip()}**"})
    if a["description"]:
        out.append({"type": "markdown", "text": a["description"]})
    if any(m["headline"] for m in a["metrics"]):
        out.append({"type": "headline", "title": "Headline metrics"})
    out.append({"type": "changes"})
    out += [{"type": "pick", "node": o["node"], "block": o["block"]} for o in a["overview"]]
    out.append({"type": "views"})
    out += [{"type": "markdown", "text": a["files"][doc].decode(), "doc": doc} for doc in a["docs"]]
    out += [{"type": "trend", "title": "This run and previous runs"}, {"type": "runs", "title": "Runs this session"}]
    about = [{"type": "dataset", "dataset": d, "title": "Data in", "brief": True} for d in a["datasets"]]
    about.append({"type": "contents", "title": "Contents", "nodes": a["graph"]["order"]})
    return out + [{"type": "fold", "id": "about-app", "title": "About this app", "blocks": about}]


def pages(a: dict) -> dict:
    return {"overview": overview_page(a),
            "groups": {g: group_page(a, g) for g in a["groups"]},
            "nodes": {n: node_page(a, n) for n in a["graph"]["order"]}}
