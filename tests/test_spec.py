"""Reading apps: the graph from node functions' signatures (ast, never run natively), their
declarations, datasets, views; building pages of blocks (no browser)."""
import copy
import json
import re

import pytest

from blocks import runs
from blocktool import build, docs, spec
from conftest import SENSOR, edit_yaml

NODES = f"projects/{SENSOR}/nodes"
TOL = {"rel_tol": 1e-9, "abs_tol": 1e-12}


def edit_text(path, old, new):
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def test_the_graph_comes_from_the_signatures(repo):
    a = spec.load_app(repo, SENSOR)
    g = a["graph"]
    assert g["order"] == ["prepare", "baseline", "featurize", "train", "evaluate", "calibrated"]
    assert g["nodes"]["evaluate"]["deps"] == [{"name": "train", "kind": "node"}, {"name": "featurize", "kind": "node"},
                                              {"name": "baseline", "kind": "node"}]
    assert g["nodes"]["prepare"]["deps"] == [{"name": "measurements", "kind": "dataset"}]
    assert a["settings"]["train.alpha"] == {"default": 0.1, "type": "float", "min": 0.0001, "max": 10, "scale": "log", "note": "ridge penalty"}
    assert a["settings"]["featurize.degree"] == {"default": 3, "type": "int", "min": 1, "max": 8, "step": 1}
    assert a["settings"]["prepare.seed"] == {"default": 42, "type": "int"}
    assert g["nodes"]["evaluate"]["doc"].startswith("Score the calibration curve on held-out rows")
    assert g["nodes"]["evaluate"]["view"] and not g["nodes"]["train"]["view"]
    assert [m["label"] for m in a["metrics"] if m["headline"]] == ["RMSE", "R²", "max error"]
    assert next(m for m in a["metrics"] if m["key"] == "n_raw")["label"] == "rows read"
    assert a["groups"]["Modelling"]["nodes"] == ["baseline", "train", "evaluate"]
    assert a["datasets"]["measurements"]["schema_node"] == "prepare"
    assert a["overview"] == [{"node": "evaluate", "block": "curve"}]
    assert a["baseline"]["code_sha"] == a["code_sha"]


@pytest.mark.parametrize("node, old, new, message", [
    ("train", "def train(featurize, *,", "def train(features, *,", "input 'features' is neither a node"),
    ("train", "def train(featurize, *,", "def fit(featurize, *,", "defines no function train"),
    ("train", "] = 0.1):", "]):", "a setting needs a default"),
    ("train", "def train(featurize, *,", "def train(featurize, extra=1, *,", "inputs have no defaults"),
    ("train", "def train(featurize, *,", "def train(featurize, *args,", r"\*args and \*\*kwargs"),
    ("train", "Range(0.0001, 10, log=True)", "Between(0, 1)", "is not Range, Choices or Note"),
    ("train", "= 0.1):", "= DEFAULT):", "must be a literal"),
    ("evaluate", '"goal": "min", "headline": True}', '"headline": True}', "needs a goal"),
    ("evaluate", '"goal": "min", "headline": True}', '"goal": "up"}', "goal must be min or max"),
    ("evaluate", "def view(out):", "def view(out, ref):", "view takes one argument"),
    ("prepare", '"measurements": {"fields": [', '"other": {"fields": [', "SCHEMA names 'other'"),
    ("prepare", '"name": "reading", "type": "number"', '"name": "reading", "type": "float"', "type 'float' is not one of"),
    ("featurize", "def featurize(prepare, *,", "def featurize(evaluate, *,", "cycle"),
])
def test_node_declarations_are_checked(repo, node, old, new, message):
    edit_text(repo / NODES / f"{node}.py", old, new)
    with pytest.raises(ValueError, match=message):
        spec.load_app(repo, SENSOR)


@pytest.mark.parametrize("change, message", [
    (lambda c: c["groups"].update(Nope={"doc": "x"}), "no node has GROUP = 'Nope'"),
    (lambda c: c.update(metrics={}), r"unknown keys \['metrics'\]"),
    (lambda c: c.update(plugins=["nope"]), "no plugin 'nope'"),
    (lambda c: c["data"]["measurements"].update(schema={}), "declared by the node that reads it"),
    (lambda c: c["data"].update({"train": c["data"]["measurements"]}), "both a node and a dataset"),
    (lambda c: c.update(overview=[{"node": "train", "block": "x"}]), "has no view"),
    (lambda c: c.update(runs=["missing.run.json"]), "must be a"),
])
def test_app_declarations_are_checked(repo, change, message):
    edit_yaml(spec.app_dir(repo, SENSOR) / "app.yaml", change)
    with pytest.raises(ValueError, match=message):
        spec.load_app(repo, SENSOR)


def test_views_docs_and_declarations_never_make_the_baseline_stale(repo):
    before = spec.load_app(repo, SENSOR)
    edit_text(repo / NODES / "evaluate.py", 'title="Residuals on held-out rows"', 'title="Residuals"')        # the view
    edit_text(repo / NODES / "evaluate.py", '"""Score the calibration', '"""Score the held-out calibration')   # the docstring
    edit_text(repo / NODES / "evaluate.py", '"label": "RMSE vs baseline"', '"label": "relative RMSE"')        # METRICS
    edit_text(repo / NODES / "calibrated.py", 'ui.file("calibration.md"', 'ui.file("report.md"')                # downloads
    after = spec.load_app(repo, SENSOR)
    assert after["code_sha"] == before["code_sha"] and after["ui_sha"] != before["ui_sha"]
    assert after["baseline"]["code_sha"] == after["code_sha"]
    edit_text(repo / NODES / "train.py", "pred = X @ w + y_mean", "pred = y_mean + X @ w")                     # the computation
    assert spec.load_app(repo, SENSOR)["code_sha"] != before["code_sha"]


def test_downloads_are_read_and_runs_can_be_left_out(repo):
    a = spec.load_app(repo, SENSOR)
    assert a["graph"]["nodes"]["calibrated"]["downloads"] and not a["graph"]["nodes"]["train"]["downloads"]
    assert a["ui"]["runs"] and docs.pages(a)["runs"] == [{"type": "runs"}]
    edit_yaml(repo / "projects" / SENSOR / "app.yaml", lambda c: c.update(ui={"runs": False}))
    with pytest.raises(ValueError, match="turns runs off"):
        spec.load_app(repo, SENSOR)                            # it still ships baseline.run.json to compare with
    edit_yaml(repo / "projects" / SENSOR / "app.yaml", lambda c: c.pop("runs"))
    a = spec.load_app(repo, SENSOR)
    p = docs.pages(a)
    assert not a["ui"]["runs"] and p["runs"] == [] and "runs-link" not in [b["type"] for b in p["overview"]]
    assert a["baseline"]                                       # making the app still verifies against it
    edit_yaml(repo / "projects" / SENSOR / "app.yaml", lambda c: c.update(ui={"runs": "no"}))
    with pytest.raises(ValueError, match="true or false"):
        spec.load_app(repo, SENSOR)


def test_documentation_pages_are_blocks(repo):
    a = spec.load_app(repo, SENSOR)
    p = docs.pages(a)
    prepare = p["nodes"]["prepare"]
    assert [b["type"] for b in prepare] == ["markdown", "settings", "results", "comparison", "views", "fold"]   # read top to bottom
    assert prepare[1]["keys"] == ["prepare.test_fraction", "prepare.seed", "prepare.outlier_z"]
    assert [b["type"] for b in prepare[-1]["blocks"]] == ["dataset", "links", "links", "code"]     # the reference, folded
    assert [b["type"] for b in p["nodes"]["evaluate"]] == ["markdown", "results", "comparison", "views", "fold"]  # no settings
    assert [b["type"] for b in p["groups"]["Modelling"]] == ["markdown", "nodes", "views"]
    assert [b["type"] for b in p["overview"]] == ["markdown", "markdown", "headline", "comparison", "pick", "views",
                                                   "runs-link", "markdown", "fold"]
    assert [b["type"] for b in p["runs"]] == ["runs"]
    assert [b["type"] for b in p["overview"][-1]["blocks"]] == ["dataset", "contents"]


def test_builds(repo):
    page, a = build.build(repo, SENSOR)
    manifest, files = build.unpack(page)
    assert build.check(page) == [] and len(page) < 600_000
    assert manifest["mode"] == "linked" and set(manifest["pages"]) == {"overview", "runs", "groups", "nodes"}
    g = json.loads(files["proto/graph.json"])
    assert g["order"] == a["graph"]["order"] and g["datasets"] == {"measurements": {"at": "data/measurements.parquet"}}
    assert "project/nodes/train.py" in files and "pylib/blocks/graph.py" in files
    assert not any(p.startswith(("project/data/", "project/plugins/")) for p in files)
    assert len(re.findall(r"\n<script>", page.decode())) == 1     # only the app script runs in the page
    page, _ = build.build(repo, SENSOR, inline=True)
    manifest, files = build.unpack(page)
    assert manifest["mode"] == "inline" and "runtime/pyodide.asm.wasm" in files and "data/measurements/measurements.parquet" in files
    assert "connect-src 'none'" in page.decode() and build.check(page) == []


def test_verification_compares_metrics_and_digests(repo):
    a = spec.load_app(repo, SENSOR)
    base, G = a["baseline"], a["graph"]
    assert base["format"] == spec.RUN_FORMAT and base["app"] == SENSOR
    assert [b["id"] for b in base["nodes"]["evaluate"]["blocks"]] == ["metrics", "markdown-1", "curve", "residuals"]
    assert set(base["code"]) == {p for p in a["files"] if p.endswith(".py")}                 # a snapshot: the app's code
    assert all(base["nodes"][n]["code"] == G["nodes"][n]["compute_sha"] and len(base["nodes"][n]["key"]) == 64 for n in G["order"])
    assert runs.compare(base, base, G, TOL)["verified"] == "match"
    run = copy.deepcopy(base)
    run["nodes"]["train"]["metrics"]["train_rmse"] += 1e-3
    res = runs.compare(run, base, G, TOL)
    assert res["nodes"]["train"]["verdict"] == "differs" and res["nodes"]["evaluate"]["verdict"] == "match"
    run = copy.deepcopy(base)
    run["nodes"]["featurize"]["digest"] = "0" * 64
    assert runs.compare(run, base, G, TOL)["nodes"]["featurize"]["mismatches"] == [{"metric": "(output)", "expected": base["nodes"]["featurize"]["digest"], "got": "0" * 64}]
    assert runs.compare(None, base, G, TOL)["verified"] == "error"
    assert runs.compare(base, None, G, TOL)["verified"] == "no-baseline"
    run = copy.deepcopy(base)
    del run["nodes"]["calibrated"]                                       # a node removed since the baseline
    assert runs.compare(run, base, G, TOL)["verified"] == "differs"
