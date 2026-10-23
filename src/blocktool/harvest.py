"""Run apps headlessly, the way a viewer would, and collect what they report.

Every node runs in the browser app itself (Pyodide in headless Chromium, driven through
the same window.blocksApp tools an agent uses); nothing here runs node code natively.
Used by:
  blocks run      -> each app's run verified against its baseline (a regression test)
  blocks baseline -> baseline.run.json per app (what later runs are verified against)
  blocks build    -> the app as one offline file, opened from file:// with the network blocked
"""
from __future__ import annotations

import json
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from blocks import runs

from . import spec
from .runtime import Runtime

TIMEOUT_S = 1800

_COLLECT = """async ({source, name}) => {
  const p = window.blocksApp;
  await p.whenReady;
  if (p.state.fatal) return { fatal: p.state.fatal };
  const t0 = performance.now();
  const r = await p.tools.run({ source });
  const run_seconds = Number(((performance.now() - t0) / 1000).toFixed(2));
  const ov = p.tools.get_overview();
  // The run file the app exports (verified against the recorded baseline in Python), and a
  // check that the run produced every result.
  const exported = r.ok ? await p.tools.export_run({ save: false, name }) : null;
  // Open every view of the app after the run, so that each shows real outputs.
  const views = {};
  for (const v of ov.views || []) {
    const s = await p.tools.open_view({ name: v.name });
    views[v.name] = { status: s.status, settled: s.settled, ms: s.ms, errors: s.errors, violations: s.violations, describe: s.describe };
  }
  return {
    views, run_file: exported && exported.run, results_missing: exported && exported.missing,
    ok: r.ok, failed: r.failed || null, error: r.error || null,
    node_errors: Object.fromEntries(ov.nodes.map((s) => [s.name, (p.state.node[s.name].result || {}).error || null])),
    startup_seconds: p.state.timings ? Number(p.state.timings.total.toFixed(2)) : null,
    page_seconds: p.state.startup ? Number(p.state.startup.toFixed(2)) : null,
    run_seconds, python: p.state.python, integrity: p.state.integrity, mode: p.manifest.mode,
    data: Object.fromEntries(Object.entries(p.state.data).map(([k, v]) => [k, { status: v.status, original: v.original }])),
  };
}"""


_active = []


@contextmanager
def browser():
    """Headless Chromium; nested uses share the browser that is already open."""
    if _active:
        yield _active[-1]
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        _active.append(b)
        try:
            yield b
        finally:
            _active.pop()
            b.close()


def drive(b, url: str, provide: dict[str, Path] | None = None, offline: bool = False,
          source: str = "harvest", timeout_s: float = TIMEOUT_S, screenshot: Path | None = None,
          name: str | None = None) -> dict:
    """Open one app page, provide any user datasets, press Run, and report, with the run
    file the app exports (named `name`, by default its date and time).
    offline: block and record every request that is not file:, blob: or data:."""
    ctx = b.new_context(viewport={"width": 1360, "height": 860})
    requests, console = [], []
    if offline:
        ctx.route("**/*", lambda route: (requests.append(route.request.url), route.abort())
                  if not route.request.url.startswith(("file:", "blob:", "data:")) else route.continue_())
    page = ctx.new_page()
    page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
    page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
    page.add_init_script("document.addEventListener('securitypolicyviolation', e => "
                         "console.error('CSP-VIOLATION ' + e.violatedDirective + ' ' + e.blockedURI))")
    page.set_default_timeout(timeout_s * 1000)
    try:
        page.goto(url)
        page.wait_for_function("() => !!window.blocksApp", timeout=30_000)
        page.evaluate("window.blocksApp.whenReady.then(() => true)")
        for name, path in (provide or {}).items():
            page.set_input_files(f'input[type=file][aria-label="File for {name}"]', str(path))
            page.wait_for_function("n => ['mounted', 'error'].includes((window.blocksApp.state.data[n] || {}).status) "
                                   "&& !String(window.blocksApp.state.data[n].note || '').startsWith('checking')", arg=name)
        res = page.evaluate(_COLLECT, {"source": source, "name": name})
        if screenshot:
            page.screenshot(path=str(screenshot))
            for name in res.get("views") or {}:
                page.evaluate("n => window.blocksApp.tools.open_view({ name: n })", name)
                page.screenshot(path=str(screenshot.with_name(f"{screenshot.stem}.{name}{screenshot.suffix}")))
    finally:
        ctx.close()
    res["network_requests"] = requests
    res["csp_violations"] = [c for c in console if "CSP-VIOLATION" in c]
    res["console_errors"] = [c for c in console if c.startswith(("error", "pageerror")) and "CSP-VIOLATION" not in c]
    return res


def user_data(a: dict, inline: bool) -> dict[str, Path]:
    """Datasets the viewer provides with a file picker (see build.build), from the project's copy."""
    return {n: Path(d["files"][0]["src"]) for n, d in a["datasets"].items()
            if not d["inline"] and (inline or d.get("format"))}


def app_url(base: str, project: str, version: str | None = None) -> str:
    # ?harvest=1: the run is reported here and not appended to the app's exploration log.
    return f"{base}/{project}/{'superseded/' + version + '/' if version else ''}index.html?harvest=1"


def results(a: dict, res: dict, rt: Runtime) -> dict:
    """What a headless run says: the run, verified against the app's recorded baseline with
    the one rule that compares runs (blocks.runs.compare)."""
    run = res.get("run_file") or {}
    check = runs.compare(run if res.get("ok") and not res.get("fatal") else None, a["baseline"], a["graph"], a["verify"])
    nodes = {n: {"verdict": check["nodes"].get(n, {}).get("verdict", "error"),
                 "mismatches": check["nodes"].get(n, {}).get("mismatches", []),
                 "seconds": ((run.get("nodes") or {}).get(n) or {}).get("seconds"),
                 "error": (res.get("node_errors") or {}).get(n)}
             for n in [*a["graph"]["order"], *(m for m in check["nodes"] if m not in a["graph"]["order"])]}   # removed nodes too
    return {
        "app": a["id"], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "code_sha": a["code_sha"],
        "verified": check["verified"], "headline": run.get("headline") or {}, "nodes": nodes,
        "metrics": {n: s.get("metrics") or {} for n, s in (run.get("nodes") or {}).items()},
        "startup_seconds": res.get("startup_seconds"), "run_seconds": res.get("run_seconds"),
        "error": res.get("fatal") or res.get("error") or (res.get("node_errors") or {}).get(res.get("failed") or ""),
        "runtime": {"pyodide": rt.version, "python": res.get("python")},
        "ui_sha": a["ui_sha"], "views": res.get("views") or {}, "results_missing": res.get("results_missing"),
    }


def problems(res: dict) -> list[str]:
    """What a run's report says is wrong besides the numbers: a result that was not produced,
    or an unhealthy view. A view is healthy when it is ready, has finished drawing the app's
    latest state, and reported no errors or CSP violations."""
    out = [f"result {p} was not produced" for p in res.get("results_missing") or []]
    for name, v in (res.get("views") or {}).items():
        if v.get("status") != "ready":
            out.append(f"view {name} is {v.get('status')}, not ready")
        elif not v.get("settled"):
            out.append(f"view {name} did not finish drawing the latest state")
        for e in v.get("errors") or []:
            out.append(f"view {name}: {e.splitlines()[0] if e else e}")
        for e in v.get("violations") or []:
            out.append(f"view {name}: CSP violation {e}")
    return out


def write_baseline(a: dict, res: dict) -> None:
    run = res.get("run_file") or {}
    write_json(a["dir"] / spec.BASELINE, run)


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=1, allow_nan=False) + "\n")


def run_apps(repo: Path, targets: list[tuple[str, str | None]], record_baseline: bool = False, log=print) -> list[dict]:
    from .server import background
    rt = Runtime(repo)
    srv, base = background(repo)
    out = []
    try:
        with browser() as b:
            for project, version in targets:
                a = spec.load_app(repo, project, version)
                log(f"{a['id']}: running {len(a['graph']['order'])} nodes in headless Chromium…")
                res = drive(b, app_url(base, project, version), provide=user_data(a, inline=False),
                            name="baseline" if record_baseline else None)
                r = results(a, res, rt)
                if record_baseline:
                    if r["verified"] == "error":
                        log(f"{a['id']}: not recording a baseline, the run failed:\n{r['error']}")
                    else:
                        try:
                            write_baseline(a, res)
                        except ValueError as e:
                            log(f"{a['id']}: not recording a baseline: {e}")
                        else:
                            r["verified"] = "match"   # by definition: this run is the baseline
                            for st in r["nodes"].values():
                                st["verdict"] = "match"
                            log(f"{a['id']}: baseline recorded for {len(res['run_file'].get('nodes') or {})} nodes")
                out.append(r)
                hl = ", ".join(f"{m['label']} {r['headline'].get(m['id'])}" for m in a["metrics"] if m["headline"])
                log(f"{a['id']}: {r['verified']} · {hl} · start-up {r['startup_seconds']} s, run {r['run_seconds']} s")
                if r["verified"] in ("error", "differs") and r.get("error"):
                    log(r["error"])
                for p in problems(res):
                    log(f"{a['id']}: {p}")
    finally:
        srv.shutdown()
    return out


_DUCKDB = """async ({base, sql, inputs, output}) => {
  const { loadPyodide } = await import(base + "pyodide.mjs");
  const py = await loadPyodide({ indexURL: base });
  await py.loadPackage(["duckdb"]);
  py.FS.mkdirTree("/work");
  const bin = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  for (const [name, b64] of Object.entries(inputs)) py.FS.writeFile("/work/" + name, bin(b64));
  py.globals.set("_SQL", sql);
  py.runPython("import os, duckdb; os.chdir('/work'); duckdb.connect().execute(_SQL)");
  const out = py.FS.readFile("/work/" + output);
  let s = "";
  for (let i = 0; i < out.length; i += 0x8000) s += String.fromCharCode.apply(null, out.subarray(i, i + 0x8000));
  return btoa(s);
}"""


def duckdb_in_browser(repo: Path, sql: str, inputs: dict[str, Path], output: str) -> bytes:
    """Run one DuckDB statement in Pyodide (headless Chromium) over `inputs` (copied into
    the working directory under their names) and return the bytes of `output`.
    Used for data preparation, e.g. CSV -> Parquet, so that no data step needs native Python."""
    import base64
    from .server import background
    rt = Runtime(repo)
    srv, base = background(repo)
    try:
        with browser() as b:
            ctx = b.new_context(bypass_csp=True)
            page = ctx.new_page()
            page.set_default_timeout(TIMEOUT_S * 1000)
            page.goto(base + "/")
            data = page.evaluate(_DUCKDB, {
                "base": f"{base}/_runtime/pyodide/{rt.version}/", "sql": sql, "output": output,
                "inputs": {n: base64.b64encode(Path(p).read_bytes()).decode() for n, p in inputs.items()}})
            ctx.close()
    finally:
        srv.shutdown()
    return base64.b64decode(data)


def to_parquet(repo: Path, src: Path, dest: Path) -> Path:
    """CSV (or anything DuckDB reads) -> Parquet, converted by DuckDB in Pyodide."""
    name = "input" + src.suffix
    data = duckdb_in_browser(repo, f"COPY (SELECT * FROM '{name}') TO 'out.parquet' (FORMAT parquet)",
                             {name: src}, "out.parquet")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


_INGEST = """async ({base, worker, adapter, adapterPath, options, packages}) => {
  // The page's ingest worker, built as the app script builds it (workerSource, app/runtime.js): Pyodide's two module
  // files adapted into one classic-worker script, followed by worker.js.
  const text = async (n) => { const r = await fetch(base + n); if (!r.ok) throw new Error(n + ": HTTP " + r.status); return r.text(); };
  const dropMap = (s) => s.replace(/\\n\\/\\/# sourceMappingURL=\\S+\\s*$/, "\\n");
  const asm = dropMap(await text("pyodide.asm.mjs")).replace(/export\\s+default\\s+_createPyodideModule;?\\s*$/, "\\n").replace(/import\\.meta\\.url/g, "self.location.href");
  const mjs = dropMap(await text("pyodide.mjs"));
  const m = mjs.match(/export\\s*\\{([^}]*)\\};?/);
  const ret = m[1].split(",").map((s) => { const [a, b] = s.trim().split(/\\s+as\\s+/); return `${b || a}: ${a}`; }).join(", ");
  // Pyodide refuses a classic worker whose importScripts works; in an app page the CSP makes it
  // fail (no data: scripts), here (CSP bypassed) it is disabled outright.
  const src = `"use strict";\\nglobalThis.importScripts = () => { throw new Error("importScripts is disabled"); };\\n${asm}\\nconst __pyodide = (() => {\\n${mjs.replace(m[0], `return { ${ret} };`)}\\n})();\\n${worker}`;
  const w = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })), { name: "proto-ingest-cli" });
  const waiting = new Map(); let n = 0;
  w.onmessage = (ev) => { const d = ev.data;
    if (d.id !== undefined && waiting.has(d.id)) { const p = waiting.get(d.id); waiting.delete(d.id); d.ok ? p.resolve(d.result) : p.reject(new Error(d.error)); }
    else if (d.type === "ingest-progress") window.protoProgress(d.phase, d.done, d.total); };
  const call = (type, args) => new Promise((resolve, reject) => { const id = ++n; waiting.set(id, { resolve, reject }); w.postMessage({ id, type, ...args }); });
  await call("init", { role: "ingest", runtimeBase: base, runtime: null, packages: [], env: {} });
  const file = document.getElementById("proto-src").files[0];
  await call("ingestSource", { name: "cli", file, adapter, adapterPath });
  const info = await call("inspect", { options });
  const out = await call("convert", { options, packages, key: "cli." + info.fingerprint.slice(0, 32), prefix: "cli." });
  w.terminate();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(out.file); a.download = "converted"; document.body.append(a); a.click();
  return { ...info, rows: out.rows, seconds: out.seconds, size: out.file.size };
}"""


def adapt(repo: Path, src: Path, dest: Path, fmt: str, options: dict, log=print) -> dict:
    """Convert `src` with a dataset adapter (a built-in plugin's format) in Pyodide in headless Chromium,
    exactly as an app's ingest worker does, and save the output to `dest`."""
    import tempfile
    from playwright.sync_api import sync_playwright
    from . import plugins
    from .build import template
    from .server import background
    plugin, ad = plugins.builtin_format(fmt)
    comp = plugins.component(plugin, plugin["formats"][fmt])
    options = ad.check_options(options)
    info = ad.inspect(str(src), options)   # fails early, natively, on a wrong layer or file
    log(f"{src.name}: {ad.describe(options)} ({info['total']:,} {ad.UNIT})")
    rt = Runtime(repo)
    srv, base = background(repo)
    last = [0.0]

    def progress(phase, done, total):
        now = time.time()
        if phase in ("loading", "opening", "done") or now - last[0] > 2:
            last[0] = now
            log(f"  {phase} {done:,}/{total:,}" if total else f"  {phase}")
    try:
        with ExitStack() as stack:
            if _active:   # inside a harvest session (tests): share its browser
                ctx = _active[-1].new_context(accept_downloads=True, bypass_csp=True)
            else:
                # a persistent profile: its storage quota (and Blob spill to disk) fit outputs of several GB
                p = stack.enter_context(sync_playwright())
                profile = stack.enter_context(tempfile.TemporaryDirectory())
                ctx = p.chromium.launch_persistent_context(profile, accept_downloads=True, bypass_csp=True)
            page = ctx.new_page()
            page.set_default_timeout(TIMEOUT_S * 1000)
            page.expose_function("protoProgress", progress)
            page.goto(base + "/")
            page.evaluate("() => { const i = document.createElement('input'); i.type = 'file'; i.id = 'proto-src'; document.body.append(i); }")
            page.set_input_files("#proto-src", str(src))
            with page.expect_download(timeout=TIMEOUT_S * 1000) as dl:
                res = page.evaluate(_INGEST, {
                    "base": f"{base}/_runtime/pyodide/{rt.version}/", "worker": template("worker.js").decode(),
                    "adapter": plugin["files"][comp].decode(), "adapterPath": comp,
                    "options": options, "packages": list(ad.PACKAGES)})
            dest.parent.mkdir(parents=True, exist_ok=True)
            dl.value.save_as(str(dest))
            ctx.close()
    finally:
        srv.shutdown()
    return res
