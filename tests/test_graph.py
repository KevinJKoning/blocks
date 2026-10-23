"""The blocks library natively: the graph executor (caching by key, failures, views), run
files and comparing them, and UI blocks, on toy nodes in plain Python. (Real apps' nodes
run only in Pyodide.)"""
import json

import pytest

from blocks import graph as graph_mod, runs, schema, ui
from blocks.session import Session

NODES = {
    "numbers": '"""Numbers 1..n."""\ndef numbers(*, n=3):\n    return list(range(1, n + 1))\n',
    "total": ('"""Their sum."""\nfrom blocks import ui\nMETRICS = {"total": {"label": "total", "goal": "max", "headline": True}}\n'
              'def total(numbers, *, scale=1):\n    return {"total": sum(numbers) * scale, "count": len(numbers)}\n'
              'def view(out):\n    return [ui.metrics(), ui.markdown(f"{out[\'count\']} numbers"), ui.data({"x": [1, 2]}, id="d")]\n'),
    "square": '"""Squares."""\ndef square(numbers):\n    return [x * x for x in numbers]\n',
}
SPEC = {
    "order": ["numbers", "total", "square"],
    "datasets": {},
    "nodes": {
        "numbers": {"file": "nodes/numbers.py", "deps": [], "settings": {"n": {"default": 3}}, "metrics": [], "view": False},
        "total": {"file": "nodes/total.py", "deps": [{"name": "numbers", "kind": "node"}], "settings": {"scale": {"default": 1}},
                  "metrics": [{"id": "total:total", "key": "total", "label": "total", "goal": "max", "headline": True}], "view": True},
        "square": {"file": "nodes/square.py", "deps": [{"name": "numbers", "kind": "node"}], "settings": {}, "metrics": [], "view": False},
    },
    "app": {"id": "toy", "project": "toy", "title": "Toy", "code_sha": "c0de", "runtime": {"pyodide": "0"}},
    "verify": {"rel_tol": 1e-9, "abs_tol": 1e-12},
}
DATA = {}


@pytest.fixture
def app(tmp_path):
    (tmp_path / "nodes").mkdir()
    for n, src in NODES.items():
        (tmp_path / "nodes" / f"{n}.py").write_text(src)
    return tmp_path


def test_a_run_computes_every_node_then_only_what_a_change_reaches(app):
    g = graph_mod.Graph(str(app), SPEC)
    r = g.run({}, {})
    assert {n: (x["status"], x["cached"]) for n, x in r.items()} == {"numbers": ("done", False), "total": ("done", False), "square": ("done", False)}
    assert r["total"]["metrics"] == {"total": 6, "count": 3}
    assert [b["id"] for b in r["total"]["blocks"]] == ["metrics", "markdown-2", "d"]
    assert r["total"]["blocks"][0]["items"][0] == {"key": "total", "label": "total", "goal": "max", "headline": True, "value": 6}
    assert r["total"]["blocks"][2]["profile"] == {"kind": "table", "rows": 2, "columns": [{"name": "x", "type": ""}], "head": [[1], [2]]}
    # a setting of total: only total runs again
    r = g.run({"total.scale": 10}, {})
    assert [n for n, x in r.items() if not x["cached"]] == ["total"] and r["total"]["metrics"]["total"] == 60
    # a setting of numbers reaches everything
    r = g.run({"total.scale": 10, "numbers.n": 4}, {})
    assert [n for n, x in r.items() if not x["cached"]] == ["numbers", "total", "square"]
    # nothing changed: all from the cache, unless asked to run again
    assert all(x["cached"] for x in g.run({"total.scale": 10, "numbers.n": 4}, {}).values())
    assert not any(x["cached"] for x in g.run({"total.scale": 10, "numbers.n": 4}, {}, only={"numbers", "total", "square"}).values())
    assert g.output("square") == [1, 4, 9, 16]


def test_the_digest_is_the_value_not_how_it_was_made(app):
    g = graph_mod.Graph(str(app), SPEC)
    a = g.run({}, {})["square"]["digest"]
    (app / "nodes" / "square.py").write_text('"""Squares."""\ndef square(numbers):\n    return [x ** 2 for x in numbers]\n')
    g2 = graph_mod.Graph(str(app), SPEC)
    assert g2.run({}, {})["square"]["digest"] == a
    assert graph_mod.digest({"a": 1.0, "b": [1, 2]}) == graph_mod.digest({"b": [1, 2], "a": 1.0})
    assert graph_mod.digest(1.0) != graph_mod.digest(1)


def test_a_failure_blocks_what_depends_on_it_and_a_failing_view_does_not_fail_the_node(app):
    (app / "nodes" / "numbers.py").write_text('def numbers(*, n=3):\n    raise ValueError("no numbers")\n')
    r = graph_mod.Graph(str(app), SPEC).run({}, {})
    assert r["numbers"]["status"] == "error" and "no numbers" in r["numbers"]["error"]
    assert r["total"] == {"status": "blocked", "error": "numbers failed"}
    (app / "nodes" / "numbers.py").write_text(NODES["numbers"])
    (app / "nodes" / "total.py").write_text(NODES["total"].replace("ui.metrics(),", "ui.metrics(), 1/0,"))
    r = graph_mod.Graph(str(app), SPEC).run({}, {})
    assert r["total"]["status"] == "done" and r["total"]["blocks"][0]["id"] == "view-error"


def test_the_session_speaks_json(app):
    s = Session(str(app), json.dumps(SPEC))
    out = json.loads(s.run(json.dumps({"numbers.n": 2}), "{}"))
    assert out["nodes"]["total"]["metrics"]["total"] == 3
    assert json.loads(s.output("total")) == {"total": 3, "count": 2}
    rec = out["record"]                          # every run makes its run file
    assert rec["format"] == runs.FORMAT and rec["complete"] and rec["ran"] == ["numbers", "total", "square"]
    assert rec["settings"] == {"numbers.n": 2, "total.scale": 1} and rec["changed_settings"] == {"numbers.n": 2}
    assert rec["headline"] == {"total:total": 3} and rec["app"] == "toy"
    again = json.loads(s.run(json.dumps({"numbers.n": 2}), "{}"))["record"]
    assert again["ran"] == [] and again["nodes"]["total"]["digest"] == rec["nodes"]["total"]["digest"]
    c = json.loads(s.compare(json.dumps(again), json.dumps(rec)))
    assert c["verified"] == "match" and c["changes"] == []


def run_file(app, settings):
    g = graph_mod.Graph(str(app), SPEC)
    return runs.record(SPEC, g.run(settings, {}), settings, DATA)


def test_one_rule_compares_runs(app):
    ref, run = run_file(app, {}), run_file(app, {"total.scale": 2, "numbers.n": 2})
    c = runs.compare(run, ref, SPEC, SPEC["verify"])
    assert c["nodes"]["numbers"]["verdict"] == "differs"                  # its output's digest
    t = c["nodes"]["total"]
    assert t["verdict"] == "differs" and t["metrics"]["total"] == {"value": 6, "ref": 6, "delta": 0, "differs": False, "better": None}
    assert t["metrics"]["count"]["delta"] == -1 and t["blocks"]["metrics"]["count"]["differs"]   # a metrics block, by id
    assert c["changes"] == [{"kind": "setting", "key": "numbers.n", "from": 3, "to": 2},
                            {"kind": "setting", "key": "total.scale", "from": 1, "to": 2}]
    assert c["headline"]["total:total"]["delta"] == 0
    better = runs.record(SPEC, {**{n: {"status": "done", "metrics": {}} for n in SPEC["order"]},
                                "total": {"status": "done", "metrics": {"total": 9}}}, {}, DATA)
    assert runs.compare(better, ref, SPEC, SPEC["verify"])["headline"]["total:total"]["better"] is True   # goal: max
    assert runs.compare(None, ref, SPEC, SPEC["verify"])["verified"] == "error"
    assert runs.compare(ref, None, SPEC, SPEC["verify"])["verified"] == "no-baseline"
    s = runs.summarize([ref, better], ref, SPEC, SPEC["verify"])
    assert s["best"] == {"total:total": better["name"]} and s["rows"][1]["headline"]["total:total"]["better"]


def test_data_is_the_same_when_its_key_is():
    a = {"settings": {}, "data": {"m": {"key": "k1", "original": True}}}
    assert runs.changes(dict(a, data={"m": {"key": "k1", "original": False, "file": "copy.parquet"}}), a) == []
    assert runs.changes(dict(a, data={"m": {"key": "k2", "original": False, "file": "other.parquet"}}), a) == [
        {"kind": "data", "key": "m", "from": "original", "to": "other.parquet"}]


def test_ui_blocks_are_plain_data():
    assert ui.metrics() == {"type": "metrics", "title": "Metrics", "id": "metrics"}
    t = ui.table([{"a": 1, "b": 2}, {"a": 3}], title="Rows")
    assert t["columns"] == ["a", "b"] and t["rows"] == [[1, 2], [3, None]] and t["total"] == 2
    assert len(ui.table([[1, 2]] * 250, columns=["x", "y"])["rows"]) == ui.MAX_ROWS
    c = ui.chart([0, 1], {"y": [1.5, 2.0]}, kind={"y": "scatter"})
    assert c["series"] == [{"name": "y", "y": [1.5, 2.0], "kind": "scatter"}]
    with pytest.raises(ValueError, match="kind is line, scatter"):
        ui.chart([1], {"y": [1]}, kind="bar")
    f = ui.figure(b"\x89PNG")
    assert f["media"] == "image/png" and f["data"] == "iVBORw=="
    assert ui.figure("<svg/>")["media"] == "image/svg+xml"


def test_schema_declarations_are_normalized():
    s = schema.check({"fields": [{"name": "a", "type": "number", "constraints": {"minimum": 0}}, {"name": "b"}], "primaryKey": "a"})
    assert s["fields"][1]["type"] == "any" and s["primaryKey"] == ["a"]
    for bad, msg in [({}, "want {fields"), ({"fields": [{"name": "a"}, {"name": "a"}]}, "declared twice"),
                     ({"fields": [{"name": "a", "constraints": {"min": 1}}]}, "unknown constraints")]:
        with pytest.raises(ValueError, match=msg):
            schema.check(bad)
