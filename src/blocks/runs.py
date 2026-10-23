"""Runs as data (docs/runs.md): a run file is a snapshot of one run of the graph, and one
rule compares runs. This module is the only place either is defined: the page's worker
makes a run file after every run (blocks.session), the page shows comparisons it asks the
worker for, and the tooling verifies a run against its baseline with the same `compare`.

A run file (blocks-run/2) keeps what is cheap in full and what is expensive by hash:

    {format, name, app, project, title, made, code_sha, code: {path: source}, runtime,
     source, ran, seconds, complete, settings, changed_settings, data,
     nodes: {name: {status, seconds, key, code, metrics, digest, output, blocks, files, error}},
     headline}

`code` is the app's Python as it was (nodes and helpers); each node's `code` is the hash of
what it computes (its file without views, downloads, docstrings and declarations) and its
`key` the graph's cache key, so two runs of a node with the same key have the same output.
`output` is the node's output as JSON when it is small (blocks.graph.small_output), else
absent: the `digest` stands for it. `blocks` are what the page showed. `files` names what
downloads(out) offered: the files are made from outputs, when downloaded.

`data` is {dataset: {key, original, file}}: `key` identifies the bytes (the recorded sha256,
a swapped file's sha256, or a format adapter's fingerprint), the same key the graph's cache
uses. Two runs read the same data when their keys are equal.
"""
from __future__ import annotations

import datetime
import math
import sys

FORMAT = "blocks-run/2"


def restore(v):
    """Run files carry non-finite numbers as "NaN"/"Infinity" strings (JSON has none)."""
    if isinstance(v, str) and v in ("NaN", "Infinity", "-Infinity"):
        return float(v.lower().replace("infinity", "inf"))
    if isinstance(v, dict):
        return {k: restore(x) for k, x in v.items()}
    if isinstance(v, list):
        return [restore(x) for x in v]
    return v


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def defaults(spec: dict) -> dict:
    return {f"{n}.{p}": s["default"] for n, node in spec["nodes"].items() for p, s in node["settings"].items()}


def headline_metrics(spec: dict) -> list[dict]:
    return [{**m, "node": n} for n in spec["order"] for m in spec["nodes"][n]["metrics"] if m["headline"]]


# ------------------------------------------------------------------ making a run file
def record(spec: dict, results: dict, settings: dict, data: dict, source: str = "ui", made: str | None = None,
           code: dict | None = None) -> dict:
    """The run file of a run: `results` is Graph.run's {node: result}, `code` the app's Python
    files {path: source}. It is `complete` when every node is done; `ran` lists the nodes it
    computed (the rest came from the cache)."""
    app = spec.get("app") or {}
    made = made or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"
    base = defaults(spec)
    full = {**base, **{k: v for k, v in settings.items() if k in base}}
    nodes = {}
    for n in spec["order"]:
        r = results.get(n) or {"status": "pending"}
        nodes[n] = {"status": r["status"], "seconds": r.get("seconds"), "key": r.get("key"),
                    "code": spec["nodes"][n].get("compute_sha"), "metrics": r.get("metrics") or {},
                    "digest": r.get("digest"), **({"output": r["output"]} if r.get("output") is not None else {}),
                    "blocks": r.get("blocks") or [], "files": [f["name"] for f in r.get("files") or []],
                    **({"error": r["error"]} if r.get("error") else {})}
    ran = [n for n in spec["order"] if nodes[n]["status"] == "done" and not (results.get(n) or {}).get("cached")]
    return {
        "format": FORMAT, "name": made[:19].replace(":", "-"), "app": app.get("id"), "project": app.get("project"),
        "title": app.get("title"), "made": made, "code_sha": app.get("code_sha"), "code": code or {},
        "runtime": {**(app.get("runtime") or {}), "python": sys.version.split()[0]},
        "source": source, "ran": ran, "seconds": round(sum(nodes[n]["seconds"] or 0 for n in ran), 4),
        "complete": all(s["status"] == "done" for s in nodes.values()),
        "settings": full, "changed_settings": {k: v for k, v in full.items() if v != base[k]}, "data": data,
        "nodes": nodes,
        "headline": {m["id"]: nodes[m["node"]]["metrics"].get(m["key"]) for m in headline_metrics(spec)},
    }


# ------------------------------------------------------------------ comparing two
def cell(value, ref, goal, tol: dict) -> dict:
    """One number against the reference's: the change, whether it is beyond the tolerance,
    and whether that is better by the metric's goal (None without a goal or a change)."""
    value, ref = restore(value), restore(ref)
    out = {"value": value, "ref": ref, "delta": None, "differs": False, "better": None}
    if _num(value) and _num(ref):
        if math.isfinite(value) and math.isfinite(ref):
            out["delta"] = value - ref
            out["differs"] = abs(value - ref) > max(tol["abs_tol"], tol["rel_tol"] * abs(ref))
        else:
            out["differs"] = not ((math.isnan(value) and math.isnan(ref)) or value == ref)
        if out["differs"] and goal in ("min", "max") and out["delta"] is not None:
            out["better"] = out["delta"] < 0 if goal == "min" else out["delta"] > 0
    else:
        out["differs"] = value != ref
    return out


def _data_key(d: dict) -> str | None:
    return (d or {}).get("key") or (d or {}).get("sha256")


def code_changes(run: dict, ref: dict) -> dict | None:
    """Which nodes compute differently in two runs (by their code's hash), and which exist in
    only one; None when the app's code is the same. A change of helpers, packages or the
    recorded data changes code_sha without any node's own code: `nodes` is then empty."""
    if run.get("code_sha") == ref.get("code_sha"):
        return None
    a, b = run.get("nodes") or {}, ref.get("nodes") or {}
    return {"kind": "code", "from": ref.get("code_sha"), "to": run.get("code_sha"),
            "nodes": [n for n in a if n in b and (a[n].get("code") != b[n].get("code"))],
            "added": [n for n in a if n not in b], "removed": [n for n in b if n not in a]}


def changes(run: dict, ref: dict) -> list[dict]:
    """What differs between two runs' inputs: the app, its code, settings, and data (by key)."""
    out = []
    if run.get("app") != ref.get("app"):
        out.append({"kind": "app", "from": ref.get("app"), "to": run.get("app")})
    code = code_changes(run, ref)
    if code:
        out.append(code)
    a, b = run.get("settings") or {}, ref.get("settings") or {}
    for k in sorted(set(a) | set(b)):
        if restore(a.get(k)) != restore(b.get(k)):
            out.append({"kind": "setting", "key": k, "from": b.get(k), "to": a.get(k)})
    a, b = run.get("data") or {}, ref.get("data") or {}
    for k in sorted(set(a) | set(b)):
        if _data_key(a.get(k)) != _data_key(b.get(k)):
            label = lambda d: None if d is None else "original" if d.get("original") else (d.get("file") or "other data")
            out.append({"kind": "data", "key": k, "from": label(b.get(k)), "to": label(a.get(k))})
    return out


def compare(run: dict | None, ref: dict | None, spec: dict, tol: dict) -> dict:
    """`run` against `ref` (both run files), node by node:
    match        every metric of the reference's is within tolerance and the output digest is the same;
    differs      a metric or the digest is not;
    no-baseline  the reference has no result for the node;
    error        the node did not run;
    missing      the reference has a result for a node this run does not have (a removed node).
    Also each metric's cell (every metric either run has, and each metrics block's items, by
    block id), the headline's cells, and what changed between the runs' inputs."""
    if not run:
        return {"verified": "error", "nodes": {}, "headline": {}, "changes": [], "reference": ref and ref.get("name")}
    goals = {n: {m["key"]: m.get("goal") for m in spec["nodes"][n]["metrics"]} for n in spec["nodes"]}
    nodes = {}
    for n, s in (run.get("nodes") or {}).items():
        r = ((ref or {}).get("nodes") or {}).get(n)
        if s.get("status") != "done":
            nodes[n] = {"verdict": "error", "mismatches": [], "metrics": {}, "blocks": {}}
            continue
        if not r or r.get("status") != "done":
            nodes[n] = {"verdict": "no-baseline", "mismatches": [], "metrics": {}, "blocks": {}}
            continue
        g = goals.get(n, {})
        mine, theirs = s.get("metrics") or {}, r.get("metrics") or {}
        metrics = {k: cell(mine.get(k), theirs.get(k), g.get(k), tol) for k in dict.fromkeys([*theirs, *mine])}
        bad = [{"metric": k, "expected": c["ref"], "got": c["value"]} for k, c in metrics.items() if c["differs"]]
        if s.get("digest") != r.get("digest"):
            bad.append({"metric": "(output)", "expected": r.get("digest"), "got": s.get("digest")})
        ref_blocks = {b.get("id"): b for b in r.get("blocks") or [] if b.get("type") == "metrics"}
        blocks = {}
        for b in s.get("blocks") or []:
            rb = ref_blocks.get(b.get("id")) if b.get("type") == "metrics" else None
            if rb:
                rv = {it["key"]: it.get("value") for it in rb.get("items") or []}
                blocks[b["id"]] = {it["key"]: cell(it.get("value"), rv[it["key"]], it.get("goal"), tol)
                                   for it in b.get("items") or [] if it["key"] in rv}
        nodes[n] = {"verdict": "differs" if bad else "match", "mismatches": bad, "metrics": metrics, "blocks": blocks}
    for n, r in ((ref or {}).get("nodes") or {}).items():
        if n not in nodes and r.get("status") == "done":
            nodes[n] = {"verdict": "missing", "mismatches": [{"metric": "(node)", "expected": r.get("digest"), "got": None}],
                        "metrics": {}, "blocks": {}}
    verdicts = [x["verdict"] for x in nodes.values()]
    verified = ("error" if "error" in verdicts or not verdicts else "differs" if {"differs", "missing"} & set(verdicts)
                else "no-baseline" if not ref or "no-baseline" in verdicts else "match")
    head = {m["id"]: cell((run.get("headline") or {}).get(m["id"]), ((ref or {}).get("headline") or {}).get(m["id"]), m.get("goal"), tol)
            for m in headline_metrics(spec)} if ref else {}
    return {"verified": verified, "nodes": nodes, "headline": head, "changes": changes(run, ref) if ref else [],
            "reference": ref and ref.get("name")}


def compare_many(run: dict | None, refs: list[dict], spec: dict, tol: dict) -> list[dict]:
    """`run` against each of `refs`: what the page compares the active run with."""
    return [compare(run, ref, spec, tol) for ref in refs]


def brief(run: dict) -> dict:
    """What `changes` and `summarize` read of a run, without its blocks, outputs and code."""
    keep = ("name", "app", "code_sha", "settings", "data", "headline", "made")
    return {**{k: run.get(k) for k in keep}, "nodes": {n: {"code": s.get("code"), "status": s.get("status")}
                                                       for n, s in (run.get("nodes") or {}).items()}}


def summarize(runs: list[dict], ref: dict | None, spec: dict, tol: dict) -> dict:
    """Many runs against one (the active run), for a table of runs: each run's input changes
    and headline cells, and per headline metric the runs best first (`order`) and the best.
    The runs may be briefs (`brief`)."""
    rows, best, ranked = [], {}, {m["id"]: [] for m in headline_metrics(spec)}
    hm = headline_metrics(spec)
    for r in runs:
        hl = r.get("headline") or {}
        rows.append({"name": r.get("name"), "changes": changes(r, ref) if ref else [],
                     "headline": {m["id"]: cell(hl.get(m["id"]), ((ref or {}).get("headline") or {}).get(m["id"]), m.get("goal"), tol)
                                  for m in hm}})
        for m in hm:
            v = restore(hl.get(m["id"]))
            if not (_num(v) and math.isfinite(v)) or m.get("goal") not in ("min", "max"):
                continue
            ranked[m["id"]].append((v if m["goal"] == "min" else -v, r.get("name")))
            if m["id"] not in best or (v < best[m["id"]][1] if m["goal"] == "min" else v > best[m["id"]][1]):
                best[m["id"]] = (r.get("name"), v)
    return {"rows": rows, "best": {k: v[0] for k, v in best.items()},
            "order": {k: [name for _, name in sorted(v, key=lambda x: x[0])] for k, v in ranked.items()}}
