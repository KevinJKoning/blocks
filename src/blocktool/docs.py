"""Every page of the report as one list of blocks (docs/blocks.md), built with the page out
of blocks.ui, where every block the page draws is defined.

A page reads top to bottom: what it is (a docstring, the app's question), what changes it
(settings, live controls), what it found (`results`: the node's run, filled by the page),
where its views go (`views`), and a fold with the reference material (the data it reads
and its schema check, what it reads and what reads it, its code). Blocks marked live are
filled by the page from this session's state.
"""
from __future__ import annotations

from blocks import ui


def node_page(a: dict, n: str) -> list[dict]:
    g = a["graph"]
    node = g["nodes"][n]
    out = [ui.markdown(node["doc"])] if node["doc"] else []
    if node["settings"]:
        out.append(ui.settings([f"{n}.{k}" for k in node["settings"]]))
    out += [ui.results(), ui.views()]
    about = [ui.dataset(d["name"]) for d in node["deps"] if d["kind"] == "dataset"]
    reads = [{"node": d["name"]} if d["kind"] == "node" else {"dataset": d["name"]} for d in node["deps"]]
    if reads:
        about.append(ui.links(reads, title="Reads"))
    users = [{"node": e["to"]} for e in g["edges"] if e["from"] == n]
    if users:
        about.append(ui.links(users, title="Read by"))
    about.append(ui.code(node["file"]))
    return out + [ui.fold("about-node", "About this node", about)]


def group_page(a: dict, name: str) -> list[dict]:
    gr = a["groups"][name]
    out = [ui.markdown(gr["doc"])] if gr["doc"] else []
    return out + [ui.nodes(gr["nodes"]), ui.views()]


def overview_page(a: dict) -> list[dict]:
    out = []
    if a["question"]:
        out.append(ui.markdown(f"**{a['question'].strip()}**"))
    if a["description"]:
        out.append(ui.markdown(a["description"]))
    if any(m["headline"] for m in a["metrics"]):
        out.append(ui.headline())
    out.append(ui.changes())
    out += [ui.pick(o["node"], o["block"]) for o in a["overview"]]
    out.append(ui.views())
    out += [ui.markdown(a["files"][doc].decode(), doc=doc) for doc in a["docs"]]
    out.append(ui.runs())
    about = [ui.dataset(d, brief=True) for d in a["datasets"]] + [ui.contents(a["graph"]["order"])]
    return out + [ui.fold("about-app", "About this app", about)]


def pages(a: dict) -> dict:
    return {"overview": overview_page(a),
            "groups": {g: group_page(a, g) for g in a["groups"]},
            "nodes": {n: node_page(a, n) for n in a["graph"]["order"]}}
