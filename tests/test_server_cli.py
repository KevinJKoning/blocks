"""The dev server's routes and the file-only CLI commands (no browser)."""
import http.client
import json
from urllib.parse import urlsplit

import pytest

from blocktool import cli, spec
from conftest import SENSOR, fetch

RUNS = f"/_api/runs/{SENSOR}"


def blocks(*args):
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    return e.value.code


@pytest.fixture
def older(repo, monkeypatch):
    """A superseded version of the app, as `blocks supersede` keeps one."""
    monkeypatch.chdir(repo)
    assert blocks("supersede", SENSOR, "older") == 0
    return "older"


def test_index_and_app_pages(server, repo, older):
    status, _, body = fetch(server + "/")
    assert status == 200 and b"Sensor calibration" in body and b"/sensor-calibration/superseded/older/" in body
    assert b"<script" not in body
    status, headers, body = fetch(f"{server}/{SENSOR}/")
    assert status == 200 and b'id="proto-manifest"' in body
    assert (repo / "build" / SENSOR / "index.html").read_bytes() == body
    status, _, body = fetch(f"{server}/{SENSOR}/superseded/older/index.html")
    assert status == 200 and b'"version": "older"' in body
    assert (repo / "build" / SENSOR / "superseded" / "older" / "index.html").is_file()
    assert fetch(f"{server}/{SENSOR}/superseded/nope/")[0] == 404
    assert fetch(f"{server}/nope/")[0] == 404


def test_build_errors_are_shown_in_the_browser(server, repo):
    (spec.app_dir(repo, SENSOR) / "app.yaml").write_text("title: x\nplugins: [nope]\n")
    status, _, body = fetch(f"{server}/{SENSOR}/")
    assert status == 500 and b"no plugin 'nope'" in body


def test_runtime_files_are_immutable_and_pinned(server, repo):
    from blocktool.runtime import Runtime
    rt = Runtime(repo)
    status, headers, body = fetch(f"{server}/_runtime/pyodide/{rt.version}/pyodide.mjs")
    assert status == 200 and "immutable" in headers["Cache-Control"]
    assert fetch(f"{server}/_runtime/pyodide/0.0.1/pyodide.mjs")[0] == 404
    assert fetch(f"{server}/_runtime/pyodide/{rt.version}/..%2Fruntime.lock.json")[0] == 404


def test_data_is_revalidated_by_etag(server, older):
    url = f"{server}/_data/{SENSOR}/measurements/measurements.parquet"
    status, headers, body = fetch(url)
    assert status == 200 and body[:4] == b"PAR1"
    assert fetch(url, headers={"If-None-Match": headers["ETag"]})[0] == 304
    assert fetch(f"{server}/_data/{SENSOR}/measurements/../../app.yaml")[0] == 404
    # a superseded version reads the project's data
    assert fetch(f"{server}/_data/{SENSOR}--older/measurements/measurements.parquet")[2] == body


def test_many_concurrent_requests_are_all_served(server):
    """A directory dataset is fetched file by file in parallel: none of those connections may be reset."""
    from concurrent.futures import ThreadPoolExecutor
    url = f"{server}/_data/{SENSOR}/measurements/measurements.parquet"
    with ThreadPoolExecutor(64) as pool:
        assert {s for s, _, _ in pool.map(lambda _: fetch(url), range(256))} == {200}


def test_runs_api(server, repo, older):
    post = lambda body, ctype="application/json", path=RUNS: fetch(server + path, data=body, headers={"Content-Type": ctype})
    assert post(json.dumps({"id": "r1", "headline": {"x": 1}}).encode())[0] == 200
    assert post(b"id=r2", "application/x-www-form-urlencoded")[0] == 415
    assert post(b"[1]")[0] == 400
    assert post(b"{")[0] == 400
    status, _, body = fetch(server + RUNS)
    assert [r["id"] for r in json.loads(body)["runs"]] == ["r1"]
    assert (spec.app_dir(repo, SENSOR) / "runs.jsonl").is_file()
    assert post(b'{"id": "r3"}', path=f"{RUNS}--older")[0] == 200
    assert (spec.app_dir(repo, SENSOR, "older") / "runs.jsonl").is_file()
    assert post(b'{"id": 1}', path="/_api/runs/nope")[0] == 404


def test_other_host_names_are_refused(server):
    u = urlsplit(server)
    conn = http.client.HTTPConnection(u.hostname, u.port)
    conn.request("GET", "/", headers={"Host": "evil.example:80"})
    assert conn.getresponse().status == 403


def test_new_skeleton(repo, monkeypatch):
    monkeypatch.chdir(repo)
    assert blocks("new", "hello") == 0
    a = spec.load_app(repo, "hello")
    assert a["graph"]["order"] == ["numbers", "total"] and a["graph"]["nodes"]["total"]["doc"] == "Adds them up."
    assert a["settings"] == {"numbers.n": {"default": 10, "type": "int", "min": 1, "max": 100}}
    assert [m["id"] for m in a["metrics"]] == ["total:total"]
    assert blocks("new", "hello") != 0
    assert blocks("new", "a--b") != 0


def test_supersede_keeps_a_copy_that_still_runs_on_the_project_data(repo, monkeypatch):
    monkeypatch.chdir(repo)
    assert blocks("supersede", SENSOR, "cubic") == 0
    old = spec.load_app(repo, SENSOR, "cubic")
    cur = spec.load_app(repo, SENSOR)
    assert old["code_sha"] == cur["code_sha"] and old["baseline"]["code_sha"] == old["code_sha"]
    assert set(old["files"]) == set(cur["files"]) and set(old["views"]) == set(cur["views"])
    assert old["runs"] == {"baseline": cur["baseline"]}          # it ships its own runs, not the superseded ones
    assert not (old["dir"] / "data").exists() and not (old["dir"] / "superseded").exists()
    assert "cubic" in spec.load_app(repo, SENSOR)["superseded"]
    assert blocks("supersede", SENSOR, "cubic") != 0
