"""Plugins: dataset formats and an app's own sandboxed views (no browser)."""
import pytest

from blocktool import build, plugins, spec
from conftest import SENSOR, edit_yaml

VIEWS = "projects/sensor-calibration/plugins/calibration-views"


def plugin_yaml(repo):
    return repo / VIEWS / "plugin.yaml"


def test_builtin_plugins():
    assert plugins.builtin_names() == ["gdb-zip"]
    p, mod = plugins.builtin_format("gdb-zip")
    assert p["name"] == "gdb-zip" and p["builtin"] and mod.NAME == "gdb-zip"


def test_a_plugin_has_formats_and_views_only(repo):
    p = plugins.load("calibration-views", spec.app_dir(repo, SENSOR))
    assert not p["builtin"] and set(p["views"]) == {"preview", "residuals"}
    (repo / VIEWS / "host.js").write_text("alert(1)\n")
    edit_yaml(plugin_yaml(repo), lambda c: c.update(scripts=["host.js"]))
    with pytest.raises(ValueError, match=r"unknown keys \['scripts'\]"):
        spec.load_app(repo, SENSOR)


def test_a_format_needs_its_plugin(tmp_path):
    from conftest import make_repo
    repo = make_repo(tmp_path / "repo", projects=("parcels",))
    edit_yaml(repo / "projects" / "parcels" / "app.yaml", lambda c: c.update(plugins=[]))
    with pytest.raises(ValueError, match="the built-in plugin gdb-zip reads it: add it to plugins:"):
        spec.load_app(repo, "parcels")


def test_views_are_placed_and_kept_out_of_code_sha(repo):
    a = spec.load_app(repo, SENSOR)
    v = a["views"]
    assert v["residuals"]["at"] == {"kind": "node", "target": "evaluate"} and v["residuals"]["tab"] == "results"
    assert v["preview"]["tab"] == "documentation" and v["preview"]["before_run"]
    assert v["residuals"]["reads"] == ["evaluate"] and v["preview"]["paths"] == ["data/measurements.parquet"]
    assert v["residuals"]["code"] == ["plugins/calibration-views/plot.js", "plugins/calibration-views/residuals.js"]


@pytest.mark.parametrize("change, message", [
    (lambda v: v["residuals"].update(at="node:nope"), "must be data, overview, node:<node> or group:<group>"),
    (lambda v: v["residuals"].update(tab="code"), "not one of"),
    (lambda v: v["residuals"].update(reads=["measurements"]), "which is not a node"),
    (lambda v: v["residuals"].update(code=["missing.js"]), "does not exist"),
    (lambda v: v["residuals"].update(code=["../../src/train.py"]), "inside the plugin"),
    (lambda v: v["residuals"].update(can=["network"]), "allowed"),
    (lambda v: v["residuals"].update(can=["params"]), "allowed here"),
    (lambda v: v["residuals"].update(can=["run"]), "allowed here"),
    (lambda v: v["preview"].update(at="data", can=["query", "run"]), "allowed here"),
    (lambda v: v["preview"].update(reads=["evaluate"]), "which is not a dataset"),
    (lambda v: v["residuals"].update(tab="documentation"), "which is not a dataset"),
])
def test_view_declarations_are_checked(repo, change, message):
    edit_yaml(plugin_yaml(repo), lambda c: change(c["views"]))
    with pytest.raises(ValueError, match=message):
        spec.load_app(repo, SENSOR)


def test_build_pins_view_code_in_the_csp(repo):
    html, a = build.build(repo, SENSOR)
    manifest, files = build.unpack(html)
    assert build.check(html) == []
    page_csp = html.decode().split('http-equiv="Content-Security-Policy" content="')[1].split('"')[0]
    assert manifest["plugins"] == [{"name": "calibration-views", "title": "Calibration views", "builtin": False, "formats": [],
                                    "views": ["preview", "residuals"],
                                    "description": "The measurements before any run (queried with DuckDB), and a residual explorer with a threshold to drag."}]
    roles = {c["path"]: c["role"] for c in manifest["components"]}
    assert roles["plugins/calibration-views/residuals.js"] == roles["proto/view-bridge.js"] == "view"
    for p in ("proto/view-bridge.js", "plugins/calibration-views/plot.js", "plugins/calibration-views/residuals.js"):
        assert build._hash(files[p]) in page_csp
    res_csp = manifest["views"]["residuals"]["csp"]
    assert build._hash(files["plugins/calibration-views/residuals.js"]) in res_csp
    assert build._hash(files["plugins/calibration-views/preview.js"]) not in res_csp
    assert "connect-src 'none'" in res_csp
    assert manifest["ui_sha"] == a["ui_sha"]


@pytest.mark.parametrize("old, new", [
    ("script-src ", "script-src 'unsafe-inline' "),          # extra source next to the hashes
    ("connect-src ", "connect-src * "),                      # a directive with no hashes at all
    ("frame-src 'none'", "frame-src *"),
    ("base-uri 'none'", "base-uri 'none'; worker-src *"),     # a repeated directive
])
def test_check_rejects_a_weakened_csp(repo, old, new):
    html, _ = build.build(repo, SENSOR)
    assert build.check(html) == []
    assert any("Content-Security-Policy" in p for p in build.check(html.decode().replace(old, new, 1).encode()))


def test_check_detects_csp_that_does_not_match_the_views(repo):
    html, _ = build.build(repo, SENSOR)
    _, files = build.unpack(html)
    bad = html.replace(build._hash(files["plugins/calibration-views/residuals.js"]).encode(), b"'sha256-AAAA'", 1)
    assert build.check(bad)


def test_view_code_must_be_storable_verbatim(repo):
    js = repo / VIEWS / "residuals.js"
    js.write_text(js.read_text() + '\nconst s = "</script>";\n')
    with pytest.raises(ValueError, match="view file"):
        build.build(repo, SENSOR)
