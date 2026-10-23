"""Runs as data (docs/runs.md): a run file records one run of the graph, and one rule
compares two of them. This module is the only place either is defined: the page's worker
makes a run file after every run (blocks.session), the page shows comparisons it asks the
worker for, and the tooling verifies a run against its baseline with the same `compare`.

A run file (blocks-run/1):

    {format, name, app, project, title, made, code_sha, runtime, source, ran, seconds,
     complete, settings, changed_settings, data, nodes: {name: {status, seconds, metrics,
     digest, blocks, files, error}}, headline}

`files` names what the node's downloads(out) offered: the files are made from outputs, which
a run file does not keep.

`data` is {dataset: {key, original, file}}: `key` identifies the bytes (the recorded sha256,
a swapped file's sha256, or a format adapter's fingerprint), the same key the graph's cache
uses. Two runs read the same data when their keys are equal.
"""
from __future__ import annotations

import datetime
import math
import sys

FORMAT = "blocks-run/1"


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
def record(spec: dict, results: dict, settings: dict, data: dict, source: str = "ui", made: str | None = None) -> dict:
    """The run file of a run: `results` is Graph.run's {node: result}. It is `complete` when
    every node is done; `ran` lists the nodes it computed (the rest came from the cache)."""
    app = spec.get("app") or {}
    made = made or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"
    base = defaults(spec)
    full = {**base, **{k: v for k, v in settings.items() if k in base}}
    nodes = {}
    for n in spec["order"]:
        r = results.get(n) or {"status": "pending"}
        nodes[n] = {"status": r["status"], "seconds": r.get("seconds"), "metrics": r.get("metrics") or {},
                    "digest": r.get("digest"), "blocks": r.get("blocks") or [], "files": [f["name"] for f in r.get("files") or []],
                    **({"error": r["error"]} if r.get("error") else {})}
    ran = [n for n in spec["order"] if nodes[n]["status"] == "done" and not (results.get(n) or {}).get("cached")]
    return {
        "format": FORMAT, "name": made[:19].replace(":", "-"), "app": app.get("id"), "project": app.get("project"),
        "title": app.get("title"), "made": made, "code_sha": app.get("code_sha"),
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


def changes(run: dict, ref: dict) -> list[dict]:
    """What differs between two runs' inputs: the app, settings, and data (by key)."""
    out = []
    if run.get("app") != ref.get("app"):
        out.append({"kind": "app", "from": ref.get("app"), "to": run.get("app")})
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
    error        the node did not run.
    Also each metric's cell (the node's metrics, and each metrics block's items, by block id),
    the headline's cells, and what changed between the runs' inputs."""
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
        metrics = {k: cell(mine.get(k), theirs[k], g.get(k), tol) for k in theirs}
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
    verdicts = [x["verdict"] for x in nodes.values()]
    verified = ("error" if "error" in verdicts or not verdicts else "differs" if "differs" in verdicts
                else "no-baseline" if not ref or "no-baseline" in verdicts else "match")
    head = {m["id"]: cell((run.get("headline") or {}).get(m["id"]), ((ref or {}).get("headline") or {}).get(m["id"]), m.get("goal"), tol)
            for m in headline_metrics(spec)} if ref else {}
    return {"verified": verified, "nodes": nodes, "headline": head, "changes": changes(run, ref) if ref else [],
            "reference": ref and ref.get("name")}


def summarize(runs: list[dict], ref: dict | None, spec: dict, tol: dict) -> dict:
    """Many runs against the reference, for a table of runs: each run's input changes and
    headline cells, and per headline metric the runs best first (`order`) and the best."""
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
