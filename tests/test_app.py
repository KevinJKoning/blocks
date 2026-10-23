"""The apps themselves, in headless Chromium: every node runs in Pyodide, in the page."""
import json
import shutil

import pytest

from blocktool import cli, harvest, spec
from conftest import SENSOR, tool, verified

pytestmark = pytest.mark.browser
RMSE = "evaluate:test_rmse"


def url(base, app=SENSOR, harvest_run=True):
    return f"{base}/{app}/index.html" + ("?harvest=1" if harvest_run else "")


def blocks(*args):
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    return e.value.code


def computed(page):
    return [n for n, s in page.evaluate("window.blocksApp.state.node").items() if s["status"] == "done" and not s.get("cached")]


def test_a_run_reproduces_the_baseline(server, open_app, repo):
    page = open_app(url(server))
    r = tool(page, "run")
    assert r["ok"], r
    assert r["computed"] == ["prepare", "baseline", "featurize", "train", "evaluate"]
    assert verified(page, repo, SENSOR) == "match"
    assert r["run"]["headline"][RMSE] == pytest.approx(0.35649534617614814, rel=1e-12)
    out = tool(page, "read_output", {"node": "baseline"})["output"]
    assert out["baseline_rmse"] == pytest.approx(0.6941426542401036)


def test_a_change_recomputes_only_what_it_reaches(server, open_app):
    page = open_app(url(server))
    assert tool(page, "run")["ok"]
    r = tool(page, "set_settings", {"values": {"train.alpha": 1}, "run": True})
    assert r["ok"] and r["computed"] == ["train", "evaluate"]
    r = tool(page, "set_settings", {"values": {"featurize.degree": 5}, "run": True})
    assert r["computed"] == ["featurize", "train", "evaluate"]
    # nothing changed: everything from the cache, and no run is logged
    r = tool(page, "run")
    assert r["computed"] == [] and r["run"] is None
    # all: every node again, and the same results
    before = page.evaluate("Object.fromEntries(Object.entries(window.blocksApp.state.node).map(([n, s]) => [n, s.digest]))")
    r = tool(page, "run", {"all": True})
    assert len(r["computed"]) == 5
    assert page.evaluate("Object.fromEntries(Object.entries(window.blocksApp.state.node).map(([n, s]) => [n, s.digest]))") == before


def test_auto_runs_a_change_by_itself(server, open_app):
    page = open_app(url(server, harvest_run=False))
    assert tool(page, "run")["ok"]
    assert tool(page, "get_overview")["auto"] is True
    page.evaluate("window.blocksApp.tools.set_settings({values: {'prepare.outlier_z': 4}})")
    page.wait_for_function("() => window.blocksApp.state.runs.length === 2 && !window.blocksApp.state.busy")
    assert page.evaluate("window.blocksApp.state.runs[1].ran") == ["prepare", "baseline", "featurize", "train", "evaluate"]
    tool(page, "set_auto", {"on": False})
    tool(page, "set_settings", {"values": {"prepare.outlier_z": 5}})
    page.wait_for_timeout(600)
    assert page.evaluate("window.blocksApp.state.node.prepare.status") == "stale" and page.evaluate("window.blocksApp.state.runs.length") == 2


def test_explore_settings_and_log_runs(server, open_app, repo):
    page = open_app(url(server, harvest_run=False))
    tool(page, "set_auto", {"on": False})
    assert tool(page, "set_settings", {"values": {"featurize.degree": 99}})["warnings"]
    sw = tool(page, "sweep", {"grid": {"featurize.degree": [1, 3], "train.alpha": [0.01, 1]}})
    assert len(sw["runs"]) == 4 and sw["restored"]
    assert tool(page, "get_overview")["settings"]["featurize.degree"]["value"] == 99
    runs = tool(page, "list_runs", {"sort_by": RMSE})
    best = runs["runs"][0]
    applied = tool(page, "apply_run", {"id": best["id"], "run": True})
    assert applied["ok"]
    logged = [json.loads(l) for l in (spec.app_dir(repo, SENSOR) / "runs.jsonl").read_text().splitlines()]
    assert logged and all("ran" in r for r in logged)
    q = tool(page, "query_data", {"sql": "SELECT count(*) AS n FROM 'data/measurements.parquet'"})
    assert q["rows"] == [[400]]
    assert tool(page, "reset")["ok"] and tool(page, "get_overview")["at_defaults"]


def test_swapping_data(server, open_app, repo, tmp_path):
    src = repo / "projects" / SENSOR / "data" / "measurements.parquet"
    same = tmp_path / "copy.parquet"
    shutil.copy(src, same)
    fewer = tmp_path / "fewer.parquet"
    fewer.write_bytes(harvest.duckdb_in_browser(
        repo, "COPY (SELECT * FROM 'in.parquet' LIMIT 300) TO 'out.parquet' (FORMAT parquet)", {"in.parquet": src}, "out.parquet"))
    page = open_app(url(server))
    tool(page, "set_auto", {"on": False})
    assert tool(page, "run")["ok"]
    field = 'input[type=file][aria-label="File for measurements"]'
    wait = ("() => { const d = window.blocksApp.state.data.measurements; "
            "return d.status === 'mounted' && !String(d.note || '').startsWith('checking') && d.profile; }")
    page.set_input_files(field, str(fewer))
    page.wait_for_function(wait)
    assert page.evaluate("window.blocksApp.state.data.measurements.profile.rows") == 300
    assert page.evaluate("window.blocksApp.state.node.prepare.status") == "stale"
    r = tool(page, "run")
    assert r["ok"] and r["computed"] == ["prepare", "baseline", "featurize", "train", "evaluate"]
    assert verified(page, repo, SENSOR) == "differs"
    page.set_input_files(field, str(same))   # the same bytes under another name count as the original
    page.wait_for_function(wait)
    assert page.evaluate("window.blocksApp.state.data.measurements.original") is True
    assert tool(page, "run")["ok"] and verified(page, repo, SENSOR) == "match"


def test_large_parquet_is_read_in_place(repo, open_app):
    """A dataset far bigger than the app is mounted with WORKERFS and read by DuckDB without copying it in."""
    n = 4_000_000
    project = repo / "projects" / "big"
    (project / "data").mkdir(parents=True)
    (project / "nodes").mkdir()
    (project / "data" / "big.parquet").write_bytes(harvest.duckdb_in_browser(
        repo, f"COPY (SELECT range AS i, range % 7 AS k FROM range({n})) TO 'out.parquet' (FORMAT parquet)", {}, "out.parquet"))
    (project / "app.yaml").write_text("title: Big\ndata:\n  big: {path: data/big.parquet}\n")
    (project / "nodes" / "agg.py").write_text(
        '"""Counts the rows."""\nimport os\nimport duckdb\n\nMETRICS = {"rows": {"goal": "max", "headline": True}}\n\n\n'
        "def agg(big):\n    rows, k = duckdb.sql(f\"SELECT count(*), sum(k) FROM '{big}'\").fetchone()\n"
        "    return {'rows': rows, 'k': int(k), 'at': os.path.realpath(big)}\n")
    from blocktool.server import background
    srv, base = background(repo)
    try:
        page = open_app(f"{base}/big/index.html?harvest=1")
        assert page.evaluate("window.blocksApp.state.data.big.profile.rows") == n
        assert tool(page, "run")["ok"]
        out = tool(page, "read_output", {"node": "agg"})["output"]
    finally:
        srv.shutdown()
    assert out["rows"] == n and out["at"] == "/_data/big/big.parquet"


def test_baseline_run_and_build_offline(repo, monkeypatch):
    """`blocks baseline`, `blocks run`, then `blocks build`: the inline build from file:// with the network blocked."""
    monkeypatch.chdir(repo)
    d = spec.app_dir(repo, SENSOR)
    (d / "baseline.run.json").unlink()
    cfg = (d / "app.yaml").read_text()
    (d / "app.yaml").write_text(cfg.replace("runs: [baseline.run.json]", ""))
    assert blocks("build", SENSOR) != 0                       # no baseline yet
    assert blocks("run", SENSOR) != 0                         # nothing to verify against
    assert blocks("baseline", SENSOR) == 0
    assert blocks("run", SENSOR) == 0
    assert blocks("build", SENSOR) == 0
    assert (repo / "dist" / f"{SENSOR}.html").is_file()
    # a view's change leaves the baseline current; a computation's does not
    ev = d / "nodes" / "evaluate.py"
    ev.write_text(ev.read_text().replace('title="Residuals on held-out rows"', 'title="Residuals"'))
    assert spec.load_app(repo, SENSOR)["baseline"]["code_sha"] == spec.load_app(repo, SENSOR)["code_sha"]
    tr = d / "nodes" / "train.py"
    tr.write_text(tr.read_text().replace("pred = X @ w + y_mean", "pred = y_mean + X @ w"))
    assert blocks("build", SENSOR) != 0
    assert blocks("build", SENSOR, "--no-verify") == 0
