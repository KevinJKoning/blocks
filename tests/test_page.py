"""The page in headless Chromium: the DAG as the report's contents, pages of blocks
(a node's docstring, live settings, the results its view made, the reference folded), comparing
runs, schema checks, the header, and an app's own sandboxed views."""
import hashlib
import json
import re

import pytest

from blocktool import build, harvest
from conftest import SENSOR, edit_yaml, tool

pytestmark = pytest.mark.browser
VIEWS = f"projects/{SENSOR}/plugins/calibration-views"


def app_url(server, harvest_run=True):
    return f"{server}/{SENSOR}/index.html" + ("?harvest=1" if harvest_run else "")


def open_modal(page):
    return page.evaluate("[...document.querySelectorAll('dialog.modal')].filter((d) => d.open).map((d) => d.dataset.modal)[0] || null")


def node_text(page, n):
    return page.locator(f'.dag .node[data-node="{n}"] .pele-label').text_content()


def block_ids(page):
    return page.evaluate("[...document.querySelectorAll('.report [data-block=results] [data-block]')].map((b) => b.dataset.id || b.dataset.block)")


def page_blocks(page):
    return page.evaluate("[...document.querySelectorAll('.report [data-block]')].filter((b) => !b.parentElement.closest('[data-block]'))"
                         ".map((b) => b.dataset.block)")


def test_before_a_run_the_app_describes_itself(server, open_app):
    page = open_app(app_url(server))
    assert open_modal(page) is None
    assert page.locator('[data-action="download-run"]').is_disabled()
    assert page.locator('[data-action="auto"]').is_checked()
    assert {page.locator(".dag .node").nth(i).get_attribute("data-status") for i in range(5)} == {"pending"}
    ev = node_text(page, "evaluate")
    assert "○ not run" in ev and "RMSE —" in ev and "R² —" in ev
    page.wait_for_function("() => /400 rows/.test(document.querySelector('.dag .node[data-node=prepare]').textContent)")
    page.wait_for_function("() => /matches its schema/.test(document.querySelector('.dag .node[data-node=prepare]').textContent)")
    assert tool(page, "get_report")["selected"] == {"kind": "overview", "name": None}
    assert page.locator(".report [role=tab]").count() == 0                       # one page, no tabs
    text = page.locator(".report").inner_text()
    assert "Which calibration curve" in text and "HEADLINE METRICS" in text and "No runs yet" in text
    assert "ABOUT THIS APP" in text and "CONTENTS" not in text                   # folded until opened
    page.click('.report [data-fold="about-app"] > summary')
    assert "CONTENTS" in page.locator(".report").inner_text()
    assert page.locator(".report input, .report select").count() == 0     # the overview changes nothing


def test_a_nodes_documentation_comes_from_its_file(server, open_app):
    page = open_app(app_url(server))
    page.click('.dag .node[data-node="prepare"]')
    assert page_blocks(page) == ["markdown", "settings", "results", "fold"]
    assert "Not run yet" in page.locator('.report [data-block="results"]').inner_text()
    page.click('.report [data-fold="about-node"] > summary')                    # the reference material
    page.wait_for_selector('.report [data-schema="measurements"] .pill.done')
    text = page.locator(".report").inner_text()
    assert "Connector spikes are screened against a robust" in text        # the docstring
    assert "400 rows · 2 columns" in text and "minimum 0, maximum 12" in text
    assert "METRICS IT REPORTS" not in text                                  # its results label them
    assert page.locator('.report [data-param="prepare.outlier_z"] input[type=range]').count() == 1   # live settings
    assert "SCHEMA = {" in page.locator(".report details.fold pre.src").text_content()            # the code
    v = tool(page, "open_view", {"name": "preview"})
    assert v["settled"] and v["describe"] == {"rows": 400, "missing": 8, "plotted": 392}
    page.click('.dag .node[data-node="train"]')
    assert page.locator('.report [data-fold="about-node"]').get_attribute("open") is not None   # stays open
    # a group's label selects the group: its documentation and its nodes
    page.click('[data-group="Modelling"] .pele-cluster-label')
    page.wait_for_function("() => window.blocksApp.state.sel.kind === 'group'")
    assert "Fits the calibration curve" in page.locator(".report").inner_text()


def test_a_setting_in_the_report_runs_what_it_reaches(server, open_app):
    page = open_app(app_url(server))
    assert tool(page, "run")["ok"]
    tool(page, "select", {"node": "train"})
    page.fill('.report [data-param="train.alpha"] input[type=number]', "1")
    page.press('.report [data-param="train.alpha"] input[type=number]', "Enter")
    page.wait_for_function("() => window.blocksApp.state.runs.length === 2 && !window.blocksApp.state.busy")
    assert page.evaluate("window.blocksApp.state.runs[1].ran") == ["train", "evaluate"]
    assert "train RMSE 0.3798" in node_text(page, "train")
    # the setting and what it changed are on one page, and the control keeps its focus
    assert re.search(r"train RMSE\s+0\.3798", page.locator('.report [data-block="results"]').inner_text())
    assert page.evaluate("document.activeElement.closest('[data-param]')?.dataset.param") == "train.alpha"


def test_results_are_each_nodes_blocks(server, open_app):
    page = open_app(app_url(server, harvest_run=False))
    page.click('[data-action="run"]')
    page.wait_for_function("() => window.blocksApp.state.runs.length === 1 && !window.blocksApp.state.busy")
    text = page.locator(".report").inner_text()
    assert "HEADLINE METRICS" in text and re.search(r"RMSE\s+0\.3565", text)
    assert page.locator('.report [data-block="pick"] [data-plot="curve"] svg.chart').count() == 1   # a block from evaluate's view
    tool(page, "select", {"node": "evaluate"})
    assert block_ids(page) == ["metrics", "markdown-2", "curve", "residuals"]
    tool(page, "select", {"node": "prepare"})
    assert block_ids(page) == ["metrics", "markdown-2", "screen", "train"]
    assert "290 rows · 2 columns" in page.locator(".report").inner_text()
    assert page.locator(".report details.fold", has_text="Other metrics (2)").count() == 1   # n_missing, n_test: not declared
    tool(page, "select", {"node": "featurize"})                # no view: its metrics
    assert block_ids(page) == ["metrics"]


def test_previous_runs_are_data_compared_after_a_run(server, open_app, tmp_path):
    page = open_app(app_url(server))
    ov = tool(page, "get_overview")
    assert [r["name"] for r in ov["previous_runs"]] == ["baseline"] and ov["reference"] == "baseline"
    assert tool(page, "set_settings", {"values": {"featurize.degree": 1}, "run": True})["ok"]
    ev = tool(page, "get_node", {"name": "evaluate"})
    assert ev["reference"] == "baseline" and ev["compare"] and ev["showing"] == "run"
    tool(page, "select", {"node": "evaluate"})
    assert "featurize.degree 3 → 1" in page.locator(".report [data-changes]").inner_text()
    assert page.locator('.report [data-plot="curve"] svg.chart .base').count() > 0
    assert page.locator(".report table.metrics th").all_inner_texts()[2:] == ["baseline", "Δ"]
    assert "Δ" in node_text(page, "evaluate")
    page.click('[data-action="show-reference"]')
    assert block_ids(page) == ["metrics", "markdown-2", "curve", "residuals"]
    exported = tool(page, "export_run")["run"]
    f = tmp_path / "degree one.run.json"
    f.write_text(json.dumps(exported))
    page.click('[data-action="open-data"]')
    page.set_input_files('input[type=file][aria-label="Previous run files"]', str(f))
    page.wait_for_function("() => window.blocksApp.tools.get_overview().previous_runs.some((r) => r.name === 'degree one')")
    page.click('dialog[data-modal="data"] [data-action="done"]')
    assert tool(page, "set_reference", {"name": "degree one"})["reference"] == "degree one"
    assert tool(page, "set_settings", {"values": {"featurize.degree": 3}, "run": True})["ok"]
    tool(page, "select", {"node": "evaluate"})
    page.click('[data-action="show-run"]')
    assert "featurize.degree 1 → 3" in page.locator(".report [data-changes]").inner_text()
    other = dict(exported, project="elsewhere")
    assert "project" in page.evaluate("(r) => Promise.resolve().then(() => window.blocksApp.tools.add_run({name: 'x', run: r})).then(() => 'added', (e) => e.message)", other)


def test_schema_problems_are_reported(server, open_app, repo, tmp_path):
    src = repo / "projects" / SENSOR / "data" / "measurements.parquet"
    out = tmp_path / "scaled.parquet"
    out.write_bytes(harvest.duckdb_in_browser(
        repo, "COPY (SELECT reading * 2 AS reading, CAST(reference AS VARCHAR) AS reference FROM 'in.parquet') "
              "TO 'out.parquet' (FORMAT parquet)", {"in.parquet": src}, "out.parquet"))
    page = open_app(app_url(server))
    page.set_input_files('input[type=file][aria-label="File for measurements"]', str(out))
    page.wait_for_function("() => /schema problem/.test(document.querySelector('.dag .node[data-node=prepare]').textContent)")
    c = tool(page, "check_data", {"dataset": "measurements"})
    fields = {f["name"]: f for f in c["result"]["fields"]}
    assert any(p.startswith("above maximum 12:") for p in fields["reading"]["problems"])
    assert fields["reference"]["problems"] == ["type VARCHAR, not number"]


def test_the_header_report_and_settings(server, open_app):
    page = open_app(app_url(server))
    page.click('[data-action="toggle-report"]')
    assert page.locator(".report").is_hidden()
    page.click('.dag .node[data-node="train"]')
    assert page.locator(".report").is_visible()
    page.click('[data-action="open-settings"]')
    dlg = page.locator('dialog[data-modal="settings"]')
    assert dlg.locator("[data-param]").count() == 5 and dlg.locator("[data-node-group]").count() == 3
    page.click('[data-settings-tab="app"]')
    assert dlg.locator('select[aria-label="Theme"]').count() == 1 and dlg.locator("[data-plugin]").count() == 1
    page.click('dialog[data-modal="settings"] [data-action="done"]')
    assert tool(page, "run")["ok"]
    with page.expect_download() as dl:
        page.click('[data-action="download-run"]')
    run = json.loads(open(dl.value.path()).read())
    assert run["format"] == "blocks-run/1" and set(run["nodes"]) == {"prepare", "baseline", "featurize", "train", "evaluate"}
    assert run["nodes"]["evaluate"]["digest"] and "verified" not in run


PROBE = """async () => {
  const out = {};
  const t = async (k, f) => { try { out[k] = await f(); } catch (e) { out[k] = "denied: " + e.message; } };
  await t("undeclared", () => bridge.read("train"));
  await t("sql_other", () => bridge.query("SELECT * FROM read_text('app.yaml')"));
  await t("sql_glob", () => bridge.query("SELECT * FROM glob('**')"));
  await t("settings", () => bridge.setSettings({"train.alpha": 1}));
  out.run = typeof bridge.run;
  try { out.parent = String(window.parent.document.title); } catch (e) { out.parent = e.name; }
  try { await fetch("/"); out.fetch = "sent"; } catch (e) { out.fetch = e.name; }
  out.origin = self.origin;
  return out;
}"""


def test_views_are_confined(server, open_app):
    page = open_app(app_url(server))
    tool(page, "open_view", {"name": "preview"})
    probe = page.frame_locator('iframe[data-view="preview"]').locator("body").evaluate(PROBE)
    assert probe["sql_other"].startswith("denied") and probe["sql_glob"].startswith("denied")
    assert "cannot setSettings" in probe["settings"] and probe["run"] == "undefined"
    assert tool(page, "run")["ok"]
    res = tool(page, "open_view", {"name": "residuals"})
    assert res["settled"] and res["describe"]["points"] == 96
    probe = page.frame_locator('iframe[data-view="residuals"]').locator("body").evaluate(PROBE)
    assert "not in its reads" in probe["undeclared"] and "cannot query" in probe["sql_other"]
    assert probe["parent"] == "SecurityError" and probe["fetch"] == "TypeError" and probe["origin"] == "null"
    page.wait_for_function("() => window.blocksApp.tools.list_views().views.find((v) => v.name === 'residuals').violations.length > 0")


def test_a_data_modal_view_can_change_settings(repo, server, open_app):
    (repo / VIEWS / "inputs.js").write_text("bridge.init.then(() => bridge.ready());\n")
    edit_yaml(repo / VIEWS / "plugin.yaml", lambda c: c["views"].update(inputs={"at": "data", "code": ["inputs.js"], "can": ["params"]}))
    page = open_app(app_url(server))
    tool(page, "open_view", {"name": "inputs"})
    assert open_modal(page) == "data"
    out = page.frame_locator('iframe[data-view="inputs"]').locator("body").evaluate(
        "async () => ({ warnings: (await bridge.setSettings({'prepare.outlier_z': 4})).warnings, run: typeof bridge.run })")
    assert out == {"warnings": [], "run": "undefined"}
    assert page.evaluate("window.blocksApp.state.settings['prepare.outlier_z']") == 4


def test_open_view_waits_for_slow_drawing(repo, server, open_app):
    (repo / VIEWS / "slow.js").write_text(
        "bridge.on('update', (s) => new Promise((r) => setTimeout(r, 1500)).then(() => bridge.describe({ drawn: s.nodes.evaluate.status })));\n"
        "bridge.init.then(() => bridge.ready());\n")
    edit_yaml(repo / VIEWS / "plugin.yaml", lambda c: c["views"].update(slow={"at": "node:evaluate", "code": ["slow.js"], "reads": ["evaluate"]}))
    page = open_app(app_url(server))
    assert "run evaluate first" in page.evaluate("window.blocksApp.tools.open_view({name: 'slow'}).then(() => 'opened', (e) => e.message)")
    assert tool(page, "run")["ok"]
    assert tool(page, "open_view", {"name": "slow"})["status"] == "ready"
    assert tool(page, "set_settings", {"values": {"train.alpha": 1}, "run": True})["ok"]
    v = tool(page, "open_view", {"name": "slow"})
    assert v["settled"] and v["describe"] == {"drawn": "done"}


def test_tampered_view_code_does_not_run(repo, browser, tmp_path):
    """The CSP is the backstop: a view script whose hash is not in the page's policy never runs."""
    page_bytes, _ = build.build(repo, SENSOR, inline=True)
    text = page_bytes.decode()
    manifest_json = re.search(r'id="proto-manifest" type="application/json">(.*?)</script>', text, re.S).group(1)
    path_ = "plugins/calibration-views/preview.js"
    _, files = build.unpack(page_bytes)
    orig, evil = files[path_].decode(), "bridge.ready({ evil: true });"
    m = json.loads(manifest_json.replace("\\u003c", "<"))
    for c in m["components"]:
        if c["path"] == path_:
            c["sha256"], c["size"] = hashlib.sha256(evil.encode()).hexdigest(), len(evil)
    text = text.replace(manifest_json, json.dumps(m, indent=1, ensure_ascii=False).replace("<", "\\u003c")).replace(
        f'data-path="{path_}" data-encoding="utf-8">{orig}<', f'data-path="{path_}" data-encoding="utf-8">{evil}<')
    path = tmp_path / "tampered.html"
    path.write_text(text)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(path.as_uri())
    page.wait_for_function("() => !!window.blocksApp")
    page.evaluate("window.blocksApp.whenReady.then(() => true)")
    assert page.evaluate("window.blocksApp.state.integrity.bad") == []
    v = tool(page, "open_view", {"name": "preview", "timeout_ms": 3000})
    assert v["status"] != "ready" and any("script-src" in x for x in v["violations"])
    ctx.close()


def test_harvest_reports_view_health(repo):
    out = harvest.run_apps(repo, [(SENSOR, None)], log=lambda *_: None)
    views = out[0]["views"]
    assert set(views) == {"residuals", "preview"}
    assert all(v["status"] == "ready" and v["settled"] and not v["errors"] and not v["violations"] for v in views.values())
    assert harvest.problems({"views": {"x": {"status": "loading", "errors": ["boom"], "violations": []}}}) == [
        "view x is loading, not ready", "view x: boom"]
