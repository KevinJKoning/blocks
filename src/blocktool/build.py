"""Build one app as a single HTML file.

Two modes, one page format and one worker path:
  linked (what `blocks serve` serves while an app is made)  code, params, plugins, shipped
      runs and UI are in the page; the Pyodide runtime, pele and datasets are loaded from
      the dev server, whose immutable /_runtime/ cache the browser keeps across builds.
  inline (`blocks build`, the app itself)  everything is embedded; the page makes no
      network requests and runs from file://. Datasets marked `inline: false` are asked for with
      a file picker and checked against their recorded size and sha256.

Page format: a JSON manifest (id="proto-manifest") lists every component (path, role,
media type, encoding, size, sha256), and each component is an inert
<script type="application/x-proto" data-path=...>. Text is stored verbatim when that is
lossless inside HTML, otherwise base64. Only the stylesheets and scripts are live, and
the Content-Security-Policy pins them by hash.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import time
from importlib import resources
from pathlib import Path

from blocks import runs

from . import docs, spec, themes
from .runtime import Runtime

FORMAT = "proto-html/1"
_SCRIPT, _END_SCRIPT, _COMMENT = "<" + "script", "<" + "/script>", "<" + "!--"


def template(name: str) -> bytes:
    return resources.files("blocktool").joinpath("templates", name).read_bytes()


# The page's script, kept in topic files (templates/app/) and joined into one live script
# (one CSP hash). Order matters only for top-level statements; see app/base.js.
APP_PARTS = ("base", "runtime", "runs", "downloads", "shell", "dag", "blocks", "report", "render", "views", "modals", "tools", "boot")
# The blocks library: what node files import, and the graph that runs them; written to /lib
# in the worker.
PYLIB = ("__init__.py", "markers.py", "ui.py", "graph.py", "runs.py", "session.py", "schema.py")


def pylib(rel: str) -> bytes:
    return resources.files("blocks").joinpath(rel).read_bytes()


def app_script() -> bytes:
    return b'"use strict";\n(() => {\n' + b"\n".join(template(f"app/{n}.js") for n in APP_PARTS) + b"})();\n"


def _verbatim_ok(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    low = text.lower()
    return not ("\r" in text or "\x00" in text or "</script" in low or _COMMENT in low or "</style" in low)


def _b64(data: bytes) -> str:
    s = base64.b64encode(data).decode("ascii")
    return "\n" + "\n".join(s[i:i + 76] for i in range(0, len(s), 76)) + "\n"


def _hash(data: bytes) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode() + "'"


def _media(path: str) -> str:
    if path.endswith((".py", ".yaml", ".yml", ".md", ".txt", ".csv", ".lock")):
        return "text/plain"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def csp(scripts: list[bytes], styles: list[bytes], linked: bool) -> str:
    return "; ".join([
        "default-src 'none'",
        "script-src " + " ".join((["'self'"] if linked else []) + [_hash(s) for s in scripts] + ["'wasm-unsafe-eval'"]),
        "style-src " + " ".join(_hash(s) for s in styles),
        "worker-src blob:",
        "img-src data: blob:",
        "connect-src " + ("'self'" if linked else "'none'"),
        "font-src 'none'", "media-src 'none'", "frame-src 'none'", "object-src 'none'",
        "form-action 'none'", "base-uri 'none'",
    ])


def view_csp(scripts: list[bytes], styles: list[bytes]) -> str:
    """The extra policy inside one view's frame. The frame also inherits the page's policy and
    both are enforced, so this only narrows it: this view's own code, and no network even in
    linked builds (Chromium otherwise lets a sandboxed frame send requests under 'self')."""
    return "; ".join([
        "default-src 'none'",
        "script-src " + " ".join(_hash(s) for s in scripts),
        "style-src " + " ".join(_hash(s) for s in styles),
        "img-src data: blob:", "connect-src 'none'", "form-action 'none'", "base-uri 'none'",
    ])


def pack(manifest: dict, components: list[dict], live_scripts: list[bytes], linked_scripts: list[str],
         view_scripts: list[bytes] = (), view_styles: list[bytes] = ()) -> bytes:
    """components: [{path, role, data}] in file order; role "style" is live CSS. view_scripts
    and view_styles run only inside view frames, which inherit this page's CSP, so their
    hashes are listed here too."""
    comps = []
    for c in components:
        data = c["data"]
        enc = "utf-8" if _verbatim_ok(data) else "base64"
        if c["role"] == "style" and enc != "utf-8":
            raise ValueError(f"{c['path']}: a stylesheet must be storable verbatim")
        comps.append({"path": c["path"], "role": c["role"], "media": c.get("media") or _media(c["path"]),
                      "encoding": enc, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    styles = [c["data"] for c in components if c["role"] == "style"]
    m = {**manifest, "format": FORMAT, "components": comps,
         "csp": csp([*live_scripts, *view_scripts], [*styles, *view_styles], bool(linked_scripts))}
    mjson = json.dumps(m, indent=1, ensure_ascii=False).replace("<", "\\u003c")   # "<" occurs only in strings
    title = html.escape(m["title"])
    desc = html.escape(m.get("description") or "")
    out = ["<!DOCTYPE html>", f'<html lang="en" data-theme="{html.escape(m["ui"]["theme"])}">', "<head>",
           '<meta charset="utf-8">',
           f'<meta http-equiv="Content-Security-Policy" content="{html.escape(m["csp"], quote=False)}">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{title}</title>", f'<meta name="description" content="{desc}">',
           '<meta name="generator" content="blocks">',
           f'{_SCRIPT} id="proto-manifest" type="application/json">{mjson}{_END_SCRIPT}']
    for c, meta in zip(components, comps):
        if c["role"] == "style":
            out.append(f'<style data-path="{html.escape(c["path"])}">{c["data"].decode()}</style>')
    out += ["</head>", "<body>",
            f'<main id="app"><header class="intro"><h1>{title}</h1><p>{desc}</p>'
            '<p class="intro-note">Loading… This page needs JavaScript; every component can still be read in its source.</p>'
            "</header></main>"]
    for c, meta in zip(components, comps):
        if c["role"] == "style":
            continue
        attrs = f'type="application/x-proto" data-path="{html.escape(c["path"])}" data-encoding="{meta["encoding"]}"'
        body = c["data"].decode() if meta["encoding"] == "utf-8" else _b64(c["data"])
        out.append(f"{_SCRIPT} {attrs}>{body}{_END_SCRIPT}")
    for src in linked_scripts:
        out.append(f'{_SCRIPT} src="{html.escape(src)}">{_END_SCRIPT}')
    for s in live_scripts:
        if not _verbatim_ok(s):
            raise ValueError("a live script contains markup that would end its script element")
        out.append(f"{_SCRIPT}>{s.decode()}{_END_SCRIPT}")
    return ("\n".join(out) + "\n</body>\n</html>\n").encode("utf-8")


def ingest_packages(a: dict) -> list[str]:
    """Packages the app's dataset adapters load in their ingest worker."""
    return sorted({p for d in a["datasets"].values() if d.get("format") for p in d["adapter"]["packages"]})


def _dataset_entry(a: dict, d: dict, inline: bool) -> dict:
    entry = {k: d[k] for k in ("name", "kind", "desc", "size", "sha256", "targets", "path")}
    entry["files"] = [{k: f[k] for k in ("rel", "size", "sha256")} for f in d["files"]]
    entry["at"] = d["at"]
    if d.get("schema"):   # declared by the node that reads it (SCHEMA), checked in the page
        entry["schema"], entry["schema_node"] = d["schema"], d["schema_node"]
    if d.get("format"):
        # converted in the browser by a plugin's adapter; sha256 is its fingerprint
        entry["format"] = d["format"]
        entry["options"] = d["options"]
        entry["adapter"] = {k: d["adapter"][k] for k in ("plugin", "path", "version", "packages", "output", "unit", "describe")}
        entry["estimate"] = {k: d["info"].get(k) for k in ("total", "unit", "bytes", "compressed", "deflated")}
    if d.get("format") and not d["inline"]:
        # a large source (a zipped geodatabase of several GB) is never copied through the
        # dev server into the page: the viewer picks it, in linked builds too
        entry["source"] = "user"
    elif not inline:
        entry["url"] = f"/_data/{a['id'].replace('/', '--')}/{d['name']}/"
        entry["source"] = "server"
    elif d["inline"]:
        entry["source"] = "embedded"
    else:
        entry["source"] = "user"
    return entry


def graph_spec(a: dict, rt: Runtime) -> dict:
    """The graph as the page and the worker see it: nodes with their inputs, settings, metrics,
    docs and the hash of what they compute; the edges; the order; where each dataset is
    mounted; what a run file records of the app (blocks.runs: its id, code_sha and Python
    files) and the tolerance runs are compared with."""
    keep = ("name", "file", "doc", "desc", "deps", "settings", "metrics", "view", "downloads", "group", "compute_sha")
    g = a["graph"]
    return {"order": g["order"], "edges": g["edges"], "nodes": {n: {k: g["nodes"][n][k] for k in keep} for n in g["order"]},
            "datasets": {d["name"]: {"at": d["at"]} for d in a["datasets"].values()},
            "code": [p for p in a["files"] if p.endswith(".py")],   # what a run file keeps of the app (blocks.runs)
            "app": {"id": a["id"], "project": a["project"], "title": a["title"], "code_sha": a["code_sha"],
                    "runtime": {"pyodide": rt.version, "packages": rt.versions(a["packages"])}},
            "verify": a["verify"]}


def build(repo: Path, project: str, version: str | None = None, inline: bool = False,
          runtime: Runtime | None = None) -> tuple[bytes, dict]:
    """Returns (html bytes, the loaded app spec)."""
    a = spec.load_app(repo, project, version)
    rt = runtime or Runtime(repo)
    pkgs = rt.closure(a["packages"])
    theme = a["ui"].get("theme", themes.DEFAULT)
    if theme not in themes.THEMES:
        raise ValueError(f"unknown theme {theme!r} (have {', '.join(themes.THEMES)})")
    plugins = a["plugins"]
    manifest = {
        "name": a["id"].replace("/", "--"), "id": a["id"], "project": project, "version": version,
        "title": a["title"], "question": a["question"], "description": a["description"],
        "mode": "inline" if inline else "linked", "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime": {"pyodide": rt.version, "python": rt.py["python"], "packages": rt.versions(a["packages"]),
                    **({} if inline else {"base": f"/_runtime/pyodide/{rt.version}/"})},
        "datasets": [_dataset_entry(a, d, inline) for d in a["datasets"].values()],
        "settings": a["settings"], "verify": a["verify"], "docs": a["docs"], "env": a["env"],
        "metrics": a["metrics"], "groups": a["groups"], "pages": docs.pages(a), "overview": a["overview"],
        "plugins": [{"name": p["name"], "title": p["title"], "description": p["description"], "builtin": p["builtin"],
                     "formats": list(p["formats"]), "views": list(p["views"])} for p in plugins.values()],
        "ui": {"theme": theme, "themes": themes.catalog(), "runs": a["ui"]["runs"]},
        "code_sha": a["code_sha"], "run_format": runs.FORMAT,
        "runs": [{"name": n, "path": f"runs/{n}{spec.RUN_SUFFIX}"} for n in a["runs"]],
        "superseded": [] if inline else [{"name": v, "url": f"/{project}/superseded/{v}/"} for v in a["superseded"]],
        "api": None if inline else f"/_api/runs/{a['id'].replace('/', '--')}",
    }
    comps = [
        {"path": "proto/themes.css", "role": "style", "data": themes.css(theme).encode()},
        {"path": "proto/app.css", "role": "style", "data": template("app.css")},
        # the graph: what the page draws and the worker runs
        {"path": "proto/graph.json", "role": "data", "data": json.dumps(graph_spec(a, rt), indent=1).encode()},
        {"path": "proto/worker.js", "role": "code", "data": template("worker.js")},
    ]
    comps += [{"path": f"pylib/blocks/{rel}", "role": "code", "data": pylib(rel)} for rel in PYLIB]
    # the adapters the app's datasets use, run in the ingest worker
    files = {k: v for p in plugins.values() for k, v in p["files"].items()}
    comps += [{"path": c, "role": "code", "data": files[c]} for c in dict.fromkeys(d["adapter"]["path"] for d in a["datasets"].values() if d.get("format"))]
    comps += [{"path": f"project/{p}", "role": "project", "data": b} for p, b in a["files"].items()]
    comps += [{"path": f"runs/{n}{spec.RUN_SUFFIX}", "role": "data", "data": json.dumps(d, indent=1).encode()} for n, d in a["runs"].items()]
    view_scripts, view_styles = _views(a, manifest, comps, themes_css=comps[0]["data"])
    if inline:
        for d in a["datasets"].values():
            if d["inline"]:
                comps += [{"path": f"data/{d['name']}/{f['rel']}", "role": "data", "data": Path(f["src"]).read_bytes()}
                          for f in d["files"]]
        names = [*rt.py["core"], *rt.package_files(a["packages"] + ingest_packages(a))]
        comps += [{"path": f"runtime/{n}", "role": "runtime", "data": rt.file(n)} for n in names]
        manifest["runtime"]["files"] = names
        live, linked = [rt.pele(), app_script()], []
    else:
        manifest["runtime"]["files"] = rt.package_files(a["packages"] + ingest_packages(a))
        live, linked = [app_script()], [f"/_runtime/pele/{rt.pins['pele']['version']}/pele.global.js"]
    manifest["packages"] = pkgs
    return pack(manifest, comps, live, linked, view_scripts, view_styles), a


def _views(a: dict, manifest: dict, comps: list[dict], themes_css: bytes) -> tuple[list[bytes], list[bytes]]:
    """Adds the app's views to the manifest and components; returns the scripts and styles
    that run in view frames. A view frame's document is composed by the app script (app/views.js) from these
    components (see viewDoc there), each script and style inline, so each must be storable
    verbatim: a CSP hash matches an element's text exactly."""
    manifest["views"], manifest["ui_sha"] = {}, a["ui_sha"]
    if not a["views"]:
        return [], []
    files = {k: v for p in a["plugins"].values() for k, v in p["files"].items()}
    used = list(dict.fromkeys(p for v in a["views"].values() for p in v["code"] + v["css"]))
    bridge, base = template("view-bridge.js"), template("view-base.css")
    for path, data in [("proto/view-bridge.js", bridge), ("proto/view-base.css", base), *((p, files[p]) for p in used)]:
        if not _verbatim_ok(data):
            raise ValueError(f"{path}: a view file must be UTF-8 text without '</script', '</style', "
                             "'<!--', NUL or CR, so that it can run inline under a CSP hash")
        comps.append({"path": path, "role": "view", "data": data})
    for name, v in a["views"].items():
        code = [files[p] for p in v["code"]]
        css = [files[p] for p in v["css"]]
        manifest["views"][name] = {**v, "csp": view_csp([bridge, *code], [themes_css, base, *css])}
    return ([bridge, *dict.fromkeys(files[p] for v in a["views"].values() for p in v["code"])],
            [base, *dict.fromkeys(files[p] for v in a["views"].values() for p in v["css"])])


def output_path(repo: Path, project: str, version: str | None = None, final: bool = False) -> Path:
    """Linked pages under build/ (rebuilt by the dev server); final apps under dist/."""
    if final:
        return repo / "dist" / (f"{project}--{version}.html" if version else f"{project}.html")
    return repo / "build" / project / (f"superseded/{version}/" if version else "") / "index.html"


def write(repo: Path, project: str, version: str | None = None, inline: bool = False, out: Path | None = None) -> Path:
    data, _ = build(repo, project, version, inline=inline)
    dest = out or output_path(repo, project, version, final=inline)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def unpack(doc: bytes) -> tuple[dict, dict]:
    """(manifest, {path: bytes}) from a built page; used by tests and `blocks check`."""
    import re
    text = doc.decode("utf-8")
    mm = re.search(_SCRIPT + r' id="proto-manifest" type="application/json">(.*?)' + _END_SCRIPT, text, re.S)
    if not mm:
        raise ValueError("not a proto page (no manifest)")
    manifest = json.loads(mm.group(1))
    files = {}
    for m in re.finditer(r'<style data-path="([^"]*)">(.*?)</style>', text, re.S):
        files[html.unescape(m.group(1))] = m.group(2).encode()
    for m in re.finditer(_SCRIPT + r' type="application/x-proto" data-path="([^"]*)" data-encoding="([^"]*)">(.*?)'
                         + _END_SCRIPT, text, re.S):
        body = m.group(3)
        files[html.unescape(m.group(1))] = base64.b64decode("".join(body.split())) if m.group(2) == "base64" \
            else body.encode()
    return manifest, files


def _policy(policy: str) -> dict | None:
    """{directive: set of sources}; None when a directive repeats (browsers keep only the
    first, which would make a comparison of the rest misleading)."""
    out = {}
    for d in policy.split(";"):
        parts = d.split()
        if not parts:
            continue
        if parts[0] in out:
            return None
        out[parts[0]] = set(parts[1:])
    return out


def check(doc: bytes) -> list[str]:
    import re
    manifest, files = unpack(doc)
    problems = []
    for c in manifest["components"]:
        b = files.get(c["path"])
        if b is None:
            problems.append(f"missing component {c['path']}")
        elif hashlib.sha256(b).hexdigest() != c["sha256"]:
            problems.append(f"hash mismatch {c['path']}")
    # The page's policy must be exactly the one build would write for these scripts and
    # styles: every directive and every source, not only the hashes.
    text = doc.decode("utf-8")
    head = text[:text.find("</head>")]     # the app script itself holds a view's meta template
    metas = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"', head)
    roles = {c["path"]: c["role"] for c in manifest["components"]}
    view = {p: b for p, b in files.items() if roles.get(p) == "view"}
    live = [s.encode() for s in re.findall(_SCRIPT + r">(.*?)" + _END_SCRIPT, text, re.S)]
    want = csp([*live, *(b for p, b in view.items() if p.endswith(".js"))],
               [*(b for p, b in files.items() if roles.get(p) == "style"), *(b for p, b in view.items() if p.endswith(".css"))],
               manifest.get("mode") == "linked")
    if len(metas) != 1:
        problems.append(f"want exactly one Content-Security-Policy meta element, found {len(metas)}")
    elif _policy(html.unescape(metas[0])) != _policy(want):
        problems.append("the page's Content-Security-Policy is not the one built for its scripts and styles")
    themes_css = files.get("proto/themes.css", b"")
    for name, v in (manifest.get("views") or {}).items():
        missing = [p for p in ["proto/view-bridge.js", *v["code"], "proto/view-base.css", *v["css"]] if p not in view]
        if missing:
            problems.append(f"view {name}: missing components {missing}")
            continue
        own = view_csp([view[p] for p in ["proto/view-bridge.js", *v["code"]]],
                       [themes_css, view["proto/view-base.css"], *(view[p] for p in v["css"])])
        if _policy(v["csp"]) != _policy(own):
            problems.append(f"view {name}: its Content-Security-Policy is not the one built for its own code")
    return problems
