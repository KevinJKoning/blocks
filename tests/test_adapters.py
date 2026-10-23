"""Dataset adapters: a zipped file geodatabase converted to GeoParquet in the browser."""
import io
import json
import zipfile

import pytest

from blocktool import build, cli, harvest, plugins, spec
from conftest import edit_yaml, fetch, make_repo, tool, verified

APP = "parcels"
FIXTURE = "projects/parcels/data/parcels.gdb.zip"
PLUGIN, gdb_zip = plugins.builtin_format("gdb-zip")


@pytest.fixture
def prepo(tmp_path):
    return make_repo(tmp_path / "repo", projects=(APP,))


def rezip(src, dest, folder="Export/Parcels.gdb/", compression=zipfile.ZIP_STORED, drop=()):
    """The same geodatabase zipped again: another folder, another compression, entries dropped."""
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(dest, "w", compression) as out:
        for i in z.infolist():
            name = i.filename.split("/", 1)[1]
            if name and not any(name.startswith(d) for d in drop):
                out.writestr(folder + name, z.read(i))
    return dest


# -- the adapter, natively (stdlib only) ---------------------------------------------------------

def test_inspect_reads_the_index_and_catalog(prepo):
    info = gdb_zip.inspect(str(prepo / FIXTURE), {"layer": "Parcels"})
    assert info["gdb"] == "Parcels.gdb" and info["layers"] == ["Hydrants", "Parcels", "Roads"]
    assert info["total"] == 2000 and info["unit"] == "features" and info["deflated"]
    assert gdb_zip.inspect(str(prepo / FIXTURE), {"layer": "Roads"})["total"] == 60


def test_fingerprint_ignores_how_it_was_zipped(prepo, tmp_path):
    fp = gdb_zip.inspect(str(prepo / FIXTURE), {"layer": "Parcels"})["fingerprint"]
    again = rezip(prepo / FIXTURE, tmp_path / "again.zip")
    info = gdb_zip.inspect(str(again), {"layer": "Parcels"})
    assert info["fingerprint"] == fp and info["gdb"] == "Export/Parcels.gdb" and not info["deflated"]
    assert gdb_zip.inspect(str(again), {"layer": "Roads"})["fingerprint"] != fp


def test_inspect_explains_what_is_wrong(prepo, tmp_path):
    with pytest.raises(ValueError, match=r"no feature class 'Nope' in Parcels.gdb \(have: Hydrants, Parcels, Roads\)"):
        gdb_zip.inspect(str(prepo / FIXTURE), {"layer": "Nope"})
    with pytest.raises(ValueError, match="layer.*required"):
        gdb_zip.check_options({})
    with pytest.raises(ValueError, match="unknown option"):
        gdb_zip.check_options({"layer": "Parcels", "sheet": 1})
    two = tmp_path / "two.zip"
    with zipfile.ZipFile(prepo / FIXTURE) as z, zipfile.ZipFile(two, "w") as out:
        for i in z.infolist():
            for folder in ("A.gdb/", "B.gdb/"):
                out.writestr(folder + i.filename.split("/", 1)[1], z.read(i))
    with pytest.raises(ValueError, match=r"2 geodatabases \(A.gdb, B.gdb\); choose one with `gdb:`"):
        gdb_zip.inspect(str(two), {"layer": "Parcels"})
    assert gdb_zip.inspect(str(two), {"layer": "Parcels", "gdb": "B.gdb"})["gdb"] == "B.gdb"
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("readme.txt", "no geodatabase here")
    with pytest.raises(ValueError, match="holds no file geodatabase"):
        gdb_zip.inspect(str(plain), {"layer": "Parcels"})


def test_adapter_module_level_is_stdlib_only():
    """It runs natively in spec.py, where neither GDAL nor pyarrow is installed."""
    src = PLUGIN["files"]["plugins/gdb-zip/gdb_zip.py"].decode()
    head = src.split("\ndef ")[0]
    assert "import pyarrow" not in head and "import fiona" not in head
    with pytest.raises(ValueError, match="unknown dataset format 'shp'"):
        plugins.builtin_format("shp")


# -- spec and build -------------------------------------------------------------------------------

def test_format_dataset_identity_is_the_fingerprint(prepo):
    a = spec.load_app(prepo, APP)
    d = a["datasets"]["parcels"]
    assert d["format"] == "gdb-zip" and d["options"] == {"layer": "Parcels"}
    assert d["sha256"] == gdb_zip.inspect(str(prepo / FIXTURE), {"layer": "Parcels"})["fingerprint"]
    assert a["baseline"]["code_sha"] == a["code_sha"]
    # another layer is other data: the baseline is stale
    y = prepo / "projects" / APP / "app.yaml"
    y.write_text(y.read_text().replace("layer: Parcels", "layer: Roads"))
    assert spec.load_app(prepo, APP)["code_sha"] != a["code_sha"]
    y.write_text(y.read_text().replace("layer: Roads", "layer: Nope"))
    with pytest.raises(ValueError, match="dataset parcels .*no feature class 'Nope'"):
        spec.load_app(prepo, APP)


def test_options_need_a_format(prepo):
    edit_yaml(prepo / "projects" / APP / "app.yaml", lambda c: c["data"]["parcels"].pop("format"))
    with pytest.raises(ValueError, match=r"unknown keys \['layer'\]"):
        spec.load_app(prepo, APP)


def test_builds_carry_the_adapter(prepo):
    for inline in (False, True):
        html, _ = build.build(prepo, APP, inline=inline)
        manifest, files = build.unpack(html)
        (d,) = manifest["datasets"]
        assert d["source"] == "user" and "url" not in d   # never copied through the dev server
        assert d["adapter"]["path"] == "plugins/gdb-zip/gdb_zip.py" and d["adapter"]["packages"] == ["fiona", "pyarrow"]
        assert files["plugins/gdb-zip/gdb_zip.py"] == PLUGIN["files"]["plugins/gdb-zip/gdb_zip.py"]
        assert d["schema"]["fields"][0]["name"] == "LANDUSE"
        assert any(f.startswith("fiona-") for f in manifest["runtime"]["files"])
        assert not any(p.startswith("data/") for p in files)   # inline: false
        assert build.check(html) == []
    assert any(p.startswith("runtime/fiona-") for p in files) and any(p.startswith("runtime/pyarrow-") for p in files)


def test_server_serves_the_zip_with_the_fingerprint_as_etag(prepo):
    from blocktool.server import background
    srv, base = background(prepo)
    try:
        status, headers, body = fetch(f"{base}/_data/{APP}/parcels/parcels.gdb.zip")
    finally:
        srv.shutdown()
    assert status == 200 and body == (prepo / FIXTURE).read_bytes()
    assert headers["ETag"] == f'"{spec.load_app(prepo, APP)["datasets"]["parcels"]["sha256"][:32]}"'


# -- in the browser -------------------------------------------------------------------------------

@pytest.fixture
def pserver(prepo):
    from blocktool.server import background
    srv, base = background(prepo)
    yield base
    srv.shutdown()


def provide(page, path):
    page.set_input_files('input[type=file][aria-label="File for parcels"]', str(path))
    page.wait_for_function("() => ['mounted', 'error', 'waiting'].includes((window.blocksApp.state.data.parcels || {}).status)"
                           " && !window.blocksApp.state.data.parcels.progress")
    return page.evaluate("window.blocksApp.state.data.parcels")


@pytest.mark.browser
def test_convert_in_the_browser_with_progress_and_cache(pserver, prepo, browser, tmp_path):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.set_default_timeout(300_000)
    # record the ingest worker's progress events
    page.add_init_script("""window.__ingest = []; const W = window.Worker;
      window.Worker = function (u, o) { const w = new W(u, o);
        if (o && String(o.name).startsWith('proto-ingest')) w.addEventListener('message', (e) => e.data && e.data.type === 'ingest-progress' && window.__ingest.push([e.data.phase, e.data.done, e.data.total]));
        return w; };""")
    try:
        page.goto(f"{pserver}/{APP}/index.html?harvest=1")
        page.evaluate("window.blocksApp.whenReady.then(() => true)")
        assert page.evaluate("window.blocksApp.state.data.parcels.status") == "waiting"
        assert "a zipped file geodatabase" in page.locator('dialog[data-modal="data"] [data-dataset="parcels"]').inner_text()

        st = provide(page, prepo / FIXTURE)
        assert st["status"] == "mounted" and st["original"] and st["rows"] == 2000 and not st["cached"] and st["store"] == "opfs"
        events = page.evaluate("window.__ingest")
        assert events[0][0] == "loading" and ["converting", 2000, 2000] in events and events[-1] == ["done", 2000, 2000]
        r = tool(page, "run")
        assert r["ok"] and verified(page, prepo, APP) == "match", r
        q = tool(page, "query_data", {"sql": "SELECT count(*), count(DISTINCT LANDUSE) FROM 'data/parcels.parquet'"})
        assert q["rows"] == [[2000, 5]]
        # what the report says of the converted data: rows, columns, and its schema checked
        assert page.evaluate("window.blocksApp.state.data.parcels.profile.rows") == 2000
        check = tool(page, "check_data", {"dataset": "parcels"})
        assert check["status"] == "done" and check["result"]["ok"], check
        assert [f["found"] for f in check["result"]["fields"]][:2] == ["VARCHAR", "DOUBLE"]

        # a reload finds the conversion in the origin's storage by the recorded fingerprint
        page.reload()
        page.evaluate("window.blocksApp.whenReady.then(() => true)")
        st = page.evaluate("window.blocksApp.state.data.parcels")
        assert st["status"] == "mounted" and st["cached"] and st["original"]

        # the same data zipped another way is still the original (and comes from the cache)
        st = provide(page, rezip(prepo / FIXTURE, tmp_path / "again.zip"))
        assert st["status"] == "mounted" and st["original"] and st["cached"]
        # an incomplete copy, or no geodatabase at all: a clear error
        st = provide(page, rezip(prepo / FIXTURE, tmp_path / "partial.zip", drop=("a00000009.",)))
        assert st["status"] == "error" and st["note"] == "the zip lacks a00000009.gdbtable, the table of 'Parcels' (an incomplete copy?)"
        other = tmp_path / "other.zip"
        with zipfile.ZipFile(other, "w") as z:
            z.writestr("notes.txt", "no geodatabase")
        st = provide(page, other)
        assert st["status"] == "error" and st["note"] == "this zip holds no file geodatabase (no a00000001.gdbtable inside)"
        assert "not loaded" in page.locator('dialog[data-modal="data"] [data-dataset="parcels"]').inner_text()
    finally:
        ctx.close()


@pytest.mark.browser
def test_cancel_a_conversion(pserver, prepo, browser):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.set_default_timeout(300_000)
    try:
        page.goto(f"{pserver}/{APP}/index.html?harvest=1")
        page.evaluate("window.blocksApp.whenReady.then(() => true)")
        page.set_input_files('input[type=file][aria-label="File for parcels"]', str(prepo / FIXTURE))
        page.wait_for_function("() => (window.blocksApp.state.data.parcels || {}).status === 'converting'")
        assert page.locator('[data-action="cancel-ingest"]').is_visible()
        page.click('[data-action="cancel-ingest"]')
        page.wait_for_function("() => window.blocksApp.state.data.parcels.status !== 'converting'")
        st = page.evaluate("window.blocksApp.state.data.parcels")
        assert st["status"] == "waiting" and st["note"] == "conversion cancelled"
        assert not tool(page, "run")["ok"]   # no data, no run
    finally:
        ctx.close()


@pytest.mark.browser
def test_cli_convert_and_promote_offline(prepo, monkeypatch, tmp_path):
    """`blocks convert --format`, then `blocks run` and `blocks build` (file://: no OPFS, Blob output)."""
    monkeypatch.chdir(prepo)

    def blocks(*args):
        with pytest.raises(SystemExit) as e:
            cli.main(list(args))
        return e.value.code

    out = tmp_path / "parcels.parquet"
    assert blocks("convert", FIXTURE, str(out), "--format", "gdb-zip", "-o", "layer=Parcels") == 0
    assert out.read_bytes()[:4] == b"PAR1"
    n = harvest.duckdb_in_browser(prepo, "COPY (SELECT count(*) AS n FROM 'in.parquet') TO 'n.csv'", {"in.parquet": out}, "n.csv")
    assert n.decode().split() == ["n", "2000"]

    assert blocks("run", APP) == 0
    assert blocks("build", APP) == 0
    assert (prepo / "dist" / f"{APP}.html").is_file()
