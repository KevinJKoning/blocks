"""The graph, run in Pyodide (docs/nodes.md): nodes are functions, values pass in memory,
and every node's output is cached by a key over its code, its settings and its inputs' keys.

Changing a setting re-runs the node that reads it and what depends on it, nothing else; a
view re-renders from the cached output without re-running anything. A node's result for
the page is its status, seconds, metrics, a digest of its output (what verification
compares, byte for byte) and its blocks (its view's, or default ones).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import sys
import time
import traceback
import types

from . import ui

VERSION = "1"   # part of every cache key: a new executor recomputes everything


def dig(obj, key):
    """A dotted path into a dict, or attributes of an object."""
    for k in key.split("."):
        obj = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
        if obj is None:
            return None
    return obj


def numbers(o, prefix=""):
    """Numeric leaves of a dict-like output as (dotted key, value)."""
    if not isinstance(o, dict):
        if hasattr(o, "__dataclass_fields__"):
            o = {f: getattr(o, f) for f in o.__dataclass_fields__}
        else:
            return
    for k, v in o.items():
        if isinstance(v, dict) or hasattr(v, "__dataclass_fields__"):
            yield from numbers(v, f"{prefix}{k}.")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            yield f"{prefix}{k}", v
        elif hasattr(v, "item") and getattr(v, "shape", None) == ():   # a numpy scalar
            yield f"{prefix}{k}", v.item()


def canon(h, v):
    """Feed a value into a hash, deterministically: what makes two outputs the same."""
    if v is None or isinstance(v, (bool, int, str)):
        h.update(json.dumps(v).encode())
    elif isinstance(v, float):
        h.update(("f" + ("nan" if math.isnan(v) else repr(v))).encode())
    elif isinstance(v, (bytes, bytearray)):
        h.update(b"b"); h.update(bytes(v))
    elif isinstance(v, dict):
        h.update(b"{")
        for k in sorted(v, key=str):
            canon(h, str(k)); canon(h, v[k])
        h.update(b"}")
    elif isinstance(v, (list, tuple)):
        h.update(b"[")
        for x in v:
            canon(h, x)
        h.update(b"]")
    elif hasattr(v, "__dataclass_fields__"):
        canon(h, {f: getattr(v, f) for f in v.__dataclass_fields__})
    elif hasattr(v, "dtype") and hasattr(v, "tobytes") and hasattr(v, "shape"):    # numpy
        h.update(f"nd{v.dtype.str}{v.shape}".encode()); h.update(v.tobytes())
    elif hasattr(v, "column_names") and hasattr(v, "to_pydict"):                  # pyarrow
        canon(h, v.to_pydict())
    elif hasattr(v, "columns") and hasattr(v, "to_numpy"):                         # pandas
        canon(h, {str(c): v[c].to_numpy() for c in v.columns})
    elif hasattr(v, "item"):
        canon(h, v.item())
    else:
        h.update(repr(v).encode())


def digest(v) -> str:
    h = hashlib.sha256()
    canon(h, v)
    return h.hexdigest()


def to_json(v, max_rows=100_000):
    """An output as JSON-able data (for views and agents)."""
    if hasattr(v, "column_names") or (hasattr(v, "columns") and hasattr(v, "itertuples")):
        cols, rows = ui.tabulate(v)
        return {"columns": cols, "rows": ui.plain(rows[:max_rows]), "total": len(rows)}
    if hasattr(v, "__dataclass_fields__"):
        v = {f: getattr(v, f) for f in v.__dataclass_fields__}
    if isinstance(v, dict):
        return {str(k): to_json(x, max_rows) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_json(x, max_rows) for x in v]
    return ui.plain(v)


def describe(value, root) -> dict:
    """What a data block shows: rows, columns and their types, a few rows; or a file's."""
    if isinstance(value, str):
        return profile_file(value if os.path.isabs(value) else os.path.join(root, value))
    cols, rows = ui.tabulate(value)
    types_ = []
    if hasattr(value, "schema") and hasattr(value, "column_names"):
        types_ = [str(f.type) for f in value.schema]
    elif hasattr(value, "dtypes"):
        types_ = [str(t) for t in value.dtypes]
    return {"kind": "table", "rows": len(rows), "columns": [{"name": c, "type": types_[i] if i < len(types_) else ""} for i, c in enumerate(cols)],
            "head": ui.plain(rows[:8])}


def profile_file(full) -> dict:
    if not os.path.exists(full):
        return {"kind": "missing"}
    if os.path.isdir(full):
        files = [os.path.join(d, n) for d, _, ns in os.walk(full) for n in ns]
        return {"kind": "dir", "files": len(files), "bytes": sum(os.path.getsize(f) for f in files)}
    if not full.lower().endswith((".parquet", ".csv", ".tsv", ".json", ".ndjson", ".jsonl")):
        return {"kind": "file", "bytes": os.path.getsize(full)}
    import duckdb
    db = duckdb.connect()
    try:
        lit = "'" + full.replace("'", "''") + "'"
        cols = [{"name": r[0], "type": r[1]} for r in db.execute(f"DESCRIBE SELECT * FROM {lit}").fetchall()]
        rows = db.execute(f"SELECT count(*) FROM {lit}").fetchone()[0]
        head = [list(r) for r in db.execute(f"SELECT * FROM {lit} LIMIT 8").fetchall()]
    except Exception as e:  # noqa: BLE001 - a file DuckDB cannot read is still described
        return {"kind": "file", "bytes": os.path.getsize(full), "error": str(e).splitlines()[0]}
    finally:
        db.close()
    return {"kind": "table", "rows": rows, "columns": cols, "bytes": os.path.getsize(full), "head": ui.plain(head)}


class Graph:
    """spec: {order, nodes: {name: {file, deps: [{name, kind}], settings: {param: {default}},
    metrics: [{id, key, label, goal, headline}], view}}, datasets: {name: {at}}}"""

    def __init__(self, root: str, spec: dict):
        self.root = os.path.abspath(root)
        self.spec = spec
        self.cache: dict[str, tuple[str, object]] = {}     # node -> (key, output)
        self.results: dict[str, dict] = {}                   # node -> its last result
        self.modules: dict[str, types.ModuleType] = {}
        helpers = sorted(p for p in self._py_files() if not p.startswith("nodes/"))
        self.helpers_sha = hashlib.sha256("".join(self._sha(p) for p in helpers).encode()).hexdigest()

    def _py_files(self):
        for d, dirs, names in os.walk(self.root):
            dirs[:] = [x for x in dirs if not x.startswith((".", "_")) and x not in ("data", "plugins")]
            for n in names:
                if n.endswith(".py"):
                    yield os.path.relpath(os.path.join(d, n), self.root)

    def _sha(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def module(self, name):
        if name not in self.modules:
            path = os.path.join(self.root, self.spec["nodes"][name]["file"])
            mod = types.ModuleType(f"node_{name}")
            mod.__file__ = path
            with open(path) as f:
                src = f.read()
            if self.root not in sys.path:
                sys.path.insert(0, self.root)
            exec(compile(src, path, "exec"), mod.__dict__)
            self.modules[name] = mod
        return self.modules[name]

    def key(self, name, settings, data_keys, keys):
        node = self.spec["nodes"][name]
        mine = {p: settings.get(f"{name}.{p}", s["default"]) for p, s in node["settings"].items()}
        parts = [VERSION, self._sha(node["file"]), self.helpers_sha, json.dumps(mine, sort_keys=True, default=repr)]
        parts += [data_keys.get(d["name"], "") if d["kind"] == "dataset" else keys.get(d["name"], "") for d in node["deps"]]
        return hashlib.sha256("\0".join(parts).encode()).hexdigest(), mine

    def run(self, settings: dict, data_keys: dict, only=None) -> dict:
        """Run every node whose key changed (or the named ones and what depends on them).
        Returns {node: result} for every node, cached ones included (cached: true)."""
        results, keys, failed = {}, {}, {}
        for name in self.spec["order"]:
            node = self.spec["nodes"][name]
            blocked = next((d["name"] for d in node["deps"] if d["kind"] == "node" and d["name"] in failed), None)
            if blocked:
                failed[name] = True
                results[name] = {"status": "blocked", "error": f"{blocked} failed"}
                continue
            key, mine = self.key(name, settings, data_keys, keys)
            keys[name] = key
            hit = self.cache.get(name)
            if hit and hit[0] == key and name in self.results and not (only and name in only):
                results[name] = {**self.results[name], "cached": True}
                continue
            args = [os.path.join(self.root, self.spec["datasets"][d["name"]]["at"]) if d["kind"] == "dataset" else self.cache[d["name"]][1]
                    for d in node["deps"]]
            old = os.getcwd()
            out, err = io.StringIO(), io.StringIO()
            t0 = time.perf_counter()
            try:
                os.chdir(self.root)
                fn = getattr(self.module(name), name)
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    value = fn(*args, **mine)
            except BaseException:  # noqa: BLE001 - a node's failure is reported, never raised
                failed[name] = True
                self.cache.pop(name, None)
                self.results.pop(name, None)
                results[name] = {"status": "error", "error": traceback.format_exc(), "seconds": round(time.perf_counter() - t0, 4),
                                 "log": out.getvalue()[-20000:] + err.getvalue()[-20000:]}
                continue
            finally:
                os.chdir(old)
            self.cache[name] = (key, value)
            results[name] = self.results[name] = self.result(name, value, round(time.perf_counter() - t0, 4), mine, False,
                                                              out.getvalue()[-20000:] + err.getvalue()[-20000:])
        return results

    def rerender(self, name) -> list:
        """A node's blocks again, from its cached output (after its view changed)."""
        self.modules.pop(name, None)
        blocks = self.blocks(name, self.cache[name][1])
        self.results[name] = {**self.results[name], "blocks": blocks}
        return blocks

    def result(self, name, value, seconds, settings, cached, log=""):
        node = self.spec["nodes"][name]
        metrics = dict(numbers(value))
        for m in node["metrics"]:
            v = dig(value, m["key"])
            if v is not None:
                metrics[m["key"]] = ui.plain(v)
        return {"status": "done", "seconds": seconds, "cached": cached, "settings": settings, "metrics": metrics,
                "digest": digest(value), "blocks": self.blocks(name, value), "log": log}

    def blocks(self, name, value):
        """The node's view of its output, with ids, metrics and data cards filled in; a node
        without a view shows its metrics and, if it is table-like, its output."""
        node = self.spec["nodes"][name]
        try:
            view = getattr(self.module(name), "view", None) if node.get("view") else None
            if view:
                old = os.getcwd()
                os.chdir(self.root)
                try:
                    raw = list(view(value) or [])
                finally:
                    os.chdir(old)
            else:
                raw = [ui.metrics()] if node["metrics"] or dict(numbers(value)) else []
                if hasattr(value, "column_names") or hasattr(value, "itertuples"):
                    raw.append(ui.data(value, title="Output"))
        except Exception:  # noqa: BLE001 - the node ran; only its view failed
            return [ui.markdown("The view failed:\n\n```\n" + traceback.format_exc() + "```", id="view-error")]
        out, taken = [], set()
        for i, b in enumerate(raw):
            b = dict(b)
            b["id"] = str(b.get("id") or f"{b['type']}-{i + 1}")
            if b["id"] in taken:
                return [ui.markdown(f"The view made two blocks with id {b['id']!r}; give one an id.", id="view-error")]
            taken.add(b["id"])
            if b["type"] == "metrics":
                b["items"] = self.metric_items(node, value, b.pop("values", None))
            elif b["type"] == "data":
                b["profile"] = describe(b.pop("value"), self.root)
            out.append(b)
        return out

    def metric_items(self, node, value, values):
        if values is not None:
            return [{"key": str(k), "label": str(k), "value": v} for k, v in values.items()]
        items = [{"key": m["key"], "label": m["label"], "goal": m["goal"], "headline": m["headline"],
                  "value": ui.plain(dig(value, m["key"]))} for m in node["metrics"]]
        seen = {m["key"] for m in node["metrics"]}
        items += [{"key": k, "label": k, "value": v, "undeclared": True} for k, v in numbers(value) if k not in seen]
        return items

    def output(self, name):
        if name not in self.cache:
            raise KeyError(f"{name} has not run")
        return to_json(self.cache[name][1])
