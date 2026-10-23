"""What the page's worker calls (templates/worker.js), in Pyodide: run the graph (and make
its run file), compare runs, read an output, describe and check datasets, DuckDB queries,
hashing. Every answer is JSON."""
from __future__ import annotations

import hashlib
import json
import math
import os

from . import graph as graph_mod
from . import runs


def browser_json(o):
    """JSON.parse rejects NaN/Infinity, so send them as strings."""
    def clean(v):
        if isinstance(v, float) and not math.isfinite(v):
            return "NaN" if math.isnan(v) else ("Infinity" if v > 0 else "-Infinity")
        if isinstance(v, dict):
            return {str(k): clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        return v
    return json.dumps(clean(o), default=str)


class Session:
    def __init__(self, root, spec_json):
        self.root = os.path.abspath(root)
        self.spec = json.loads(spec_json)
        self.graph = graph_mod.Graph(self.root, self.spec)
        self._db = None

    def run(self, settings_json, data_json, only_json="null", source="ui"):
        """Run what changed; data is {dataset: {key, original, file}} (blocks.runs). Returns
        {nodes: {node: result}, record: the run file of the graph as it now stands}."""
        settings, data, only = json.loads(settings_json), json.loads(data_json), json.loads(only_json)
        results = self.graph.run(settings, {n: d["key"] for n, d in data.items()}, set(only) if only else None)
        return browser_json({"nodes": results, "record": runs.record(self.spec, results, settings, data, source)})

    def compare(self, run_json, ref_json):
        return browser_json(runs.compare(json.loads(run_json), json.loads(ref_json), self.spec, self.spec["verify"]))

    def summarize(self, runs_json, ref_json):
        return browser_json(runs.summarize(json.loads(runs_json), json.loads(ref_json), self.spec, self.spec["verify"]))

    def output(self, name):
        return browser_json(self.graph.output(name))

    def profile(self, path):
        return browser_json(graph_mod.profile_file(os.path.join(self.root, path)))

    def validate(self, path, schema_json):
        from . import schema
        old = os.getcwd()
        os.chdir(self.root)
        try:
            return browser_json(schema.validate(path, json.loads(schema_json)))
        finally:
            os.chdir(old)

    def sha256_file(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 22), b""):
                h.update(block)
        return h.hexdigest()

    def query(self, sql, limit, allow=None):
        """DuckDB SQL from the app root. allow (JSON list of app paths): a fresh connection
        that can read only these, locked so that SQL cannot unlock it."""
        import duckdb
        old = os.getcwd()
        os.chdir(self.root)
        db = None
        try:
            if allow is not None:
                paths = [os.path.join(self.root, p) for p in json.loads(allow)]
                lit = lambda xs: "[" + ", ".join("'" + x.replace("'", "''") + "'" for x in xs) + "]"
                db = duckdb.connect()
                db.execute(f"SET allowed_paths = {lit([p for p in paths if not os.path.isdir(p)])}")
                db.execute(f"SET allowed_directories = {lit([p for p in paths if os.path.isdir(p)])}")
                db.execute("SET enable_external_access = false")
            else:
                self._db = self._db or duckdb.connect()
                db = self._db
            rel = db.sql(sql)
            if rel is None:
                return browser_json({"columns": [], "rows": [], "truncated": False})
            cols = list(rel.columns)
            rows = rel.limit(int(limit) + 1).fetchall()
        finally:
            os.chdir(old)
            if allow is not None and db is not None:
                db.close()
        return browser_json({"columns": cols, "rows": [list(r) for r in rows[:int(limit)]], "truncated": len(rows) > int(limit)})
