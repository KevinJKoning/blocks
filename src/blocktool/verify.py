"""Verification: does a run reproduce a recorded one? Part of making apps, so it lives in
the tooling and never in the page.

`blocks baseline` stores an app's baseline as a run file (baseline.run.json, what Download
run exports). `blocks run` and `blocks build` run the app at the baseline's settings and
data, take the run file it exports, and compare per node: every metric within the app's
tolerance, and the digest of its output (a hash over the value itself, blocks.graph.canon)
exactly. Views are not compared: they never change results.
"""
from __future__ import annotations

import math


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


def compare_metrics(got: dict, expected: dict, rel_tol: float, abs_tol: float) -> list[dict]:
    got, expected = restore(got or {}), restore(expected or {})
    bad = []
    for k, e in expected.items():
        g = got.get(k)
        if _num(e) and _num(g):
            ok = (abs(g - e) <= max(abs_tol, rel_tol * abs(e))) if math.isfinite(e) and math.isfinite(g) \
                else (math.isnan(e) and math.isnan(g)) or g == e
        else:
            ok = g == e
        if not ok:
            bad.append({"metric": k, "expected": e, "got": g})
    return bad


def compare_runs(got: dict | None, recorded: dict | None, tol: dict) -> dict:
    """Each node of `got` against `recorded` (both run files):
    match        its metrics agree within tolerance and its output digest is the same;
    differs      a metric or the digest does not;
    no-baseline  the recorded run has nothing for the node;
    error        the node did not run.
    Returns {verified, nodes: {name: {verdict, mismatches}}}."""
    if not got:
        return {"verified": "error", "nodes": {}}
    if not recorded:
        return {"verified": "no-baseline", "nodes": {n: {"verdict": "no-baseline", "mismatches": []} for n in got.get("nodes") or {}}}
    out = {}
    for name, s in (got.get("nodes") or {}).items():
        r = (recorded.get("nodes") or {}).get(name)
        if s.get("status") != "done":
            out[name] = {"verdict": "error", "mismatches": []}
        elif r is None:
            out[name] = {"verdict": "no-baseline", "mismatches": []}
        else:
            bad = compare_metrics(s.get("metrics"), r.get("metrics"), tol["rel_tol"], tol["abs_tol"])
            if s.get("digest") != r.get("digest"):
                bad.append({"metric": "(output)", "expected": r.get("digest"), "got": s.get("digest")})
            out[name] = {"verdict": "differs" if bad else "match", "mismatches": bad}
    verdicts = [n["verdict"] for n in out.values()]
    verified = ("error" if "error" in verdicts else "differs" if "differs" in verdicts
                else "no-baseline" if "no-baseline" in verdicts else "match")
    return {"verified": verified, "nodes": out}
