"""Read an app: its nodes (one function per file, read with ast, never run natively), the
graph their signatures make, its settings, datasets, plugins and views.

Layout
  projects/<project>/app.yaml           the app: title, question, description, data, groups,
                                        plugins, overview, docs, runs, verify
  projects/<project>/nodes/<name>.py    one node: def <name>(inputs..., *, settings...)
  projects/<project>/*.py, lib/…        helpers the nodes import
  projects/<project>/data/              the project's datasets
  projects/<project>/plugins/<name>/    the app's own plugins (views, formats)
  projects/<project>/superseded/<name>/ earlier versions of the app, same shape

A node's positional parameters are what it reads: other nodes (by name) or datasets (by
name). Its keyword-only parameters are its settings, with literal defaults and, optionally,
Annotated[..., Range(...), Choices(...), Note(...)]. Its docstring documents it; METRICS,
SCHEMA and GROUP are literal module constants; view(out) is its presentation, downloads(out)
the files it offers.
"""
from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
from pathlib import Path

import yaml

from . import plugins as plugin_mod
from blocks import runs as table_runs, schema as table_schema

BASELINE = "baseline.run.json"
RUN_SUFFIX = ".run.json"
RUN_FORMAT = table_runs.FORMAT
BOOKKEEPING = {"app.yaml", "runs.jsonl"}   # runs.jsonl: where the run log was kept before it moved to build/
RESERVED_DIRS = ("plugins", "superseded", "data")
DEFAULT_TOL = {"rel_tol": 1e-9, "abs_tol": 1e-12}
APP_KEYS = {"title", "question", "description", "data", "groups", "plugins", "packages", "overview",
            "docs", "runs", "verify", "ui", "env"}
DATASET_KEYS = ("path", "at", "desc", "inline", "format")
VIEW_KEYS = {"at", "title", "code", "css", "reads", "can"}
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def _yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


_FILE_SHA: dict = {}


def sha256_file(path: Path) -> str:
    """Streamed, and remembered while the file's size and mtime are unchanged."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _FILE_SHA:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while block := f.read(1 << 22):
                h.update(block)
        _FILE_SHA[key] = h.hexdigest()
    return _FILE_SHA[key]


# ------------------------------------------------------------------ nodes
def _literal(node, where):
    try:
        return ast.literal_eval(node)
    except ValueError:
        raise ValueError(f"{where} must be a literal (numbers, strings, lists, dicts)") from None


def _marker(call, where) -> dict:
    """Range(...), Choices(...) or Note(...) in a setting's annotation."""
    name = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
    args = [_literal(a, where) for a in call.args]
    kw = {k.arg: _literal(k.value, where) for k in call.keywords}
    if name == "Range":
        names = ["min", "max", "step", "log"]
        vals = dict(zip(names, args)) | kw
        out = {"min": vals["min"], "max": vals["max"]}
        if vals.get("step") is not None:
            out["step"] = vals["step"]
        if vals.get("log"):
            out["scale"] = "log"
        return out
    if name == "Choices":
        return {"choices": args}
    if name == "Note":
        return {"note": args[0] if args else kw.get("text", "")}
    raise ValueError(f"{where}: {name}(...) is not Range, Choices or Note")


def _setting(arg: ast.arg, default, where) -> dict:
    if default is None:
        raise ValueError(f"{where}: a setting needs a default value")
    out = {"default": _literal(default, f"{where}: its default")}
    ann = arg.annotation
    if isinstance(ann, ast.Subscript) and getattr(ann.value, "id", getattr(ann.value, "attr", "")) == "Annotated":
        elts = ann.slice.elts if isinstance(ann.slice, ast.Tuple) else [ann.slice]
        out["type"] = ast.unparse(elts[0])
        for e in elts[1:]:
            if isinstance(e, ast.Call):
                out.update(_marker(e, where))
    elif ann is not None:
        out["type"] = ast.unparse(ann)
    return out


def _metric_decls(where: str, name: str, decl) -> list[dict]:
    """METRICS = {key: {label, goal, headline, desc} | "label"}; key is a dotted path into the output."""
    if decl and not isinstance(decl, dict):
        raise ValueError(f"{where}: METRICS must be a dict of key: label or {{label, goal, headline, desc}}")
    out = []
    for key, m in (decl or {}).items():
        m = {"label": m} if isinstance(m, str) else (m or {})
        unknown = set(m) - {"label", "goal", "headline", "desc"}
        if unknown:
            raise ValueError(f"{where}: metric {key!r}: unknown keys {sorted(unknown)}")
        if m.get("goal") not in (None, "min", "max"):
            raise ValueError(f"{where}: metric {key!r}: goal must be min or max")
        if m.get("headline") and not m.get("goal"):
            raise ValueError(f"{where}: metric {key!r}: a headline metric needs a goal (min or max)")
        out.append({"id": f"{name}:{key}", "node": name, "key": str(key), "label": m.get("label") or str(key),
                    "goal": m.get("goal"), "headline": bool(m.get("headline")), "desc": m.get("desc") or ""})
    return out


def _is_doc(n) -> bool:
    return isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)


def _compute_source(tree: ast.Module) -> str:
    """What a node computes: its file without its view and downloads, its docstrings and its
    declarations (METRICS, SCHEMA, GROUP). Changing any of those never changes results, so
    never makes the baseline stale."""
    import copy
    tree = copy.deepcopy(tree)
    keep = []
    for n in tree.body:
        if _is_doc(n) or (isinstance(n, ast.FunctionDef) and n.name in ("view", "downloads")):
            continue
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if all(isinstance(t, ast.Name) and t.id in ("METRICS", "SCHEMA", "GROUP") for t in targets):
                continue
        for f in ast.walk(n):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and f.body and _is_doc(f.body[0]):
                f.body = f.body[1:] or [ast.Pass()]
        keep.append(n)
    return ast.unparse(ast.Module(body=keep, type_ignores=[]))


def read_node(path: Path, src: str) -> dict:
    """One node file: its function, docstring, settings, constants, and whether it has a view
    and downloads."""
    name = path.stem
    where = f"node {name} ({path.name})"
    if not _NAME.match(name):
        raise ValueError(f"{where}: a node's file name is a Python name (lower case, digits, _)")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise ValueError(f"{where}: {e.msg} (line {e.lineno})") from None
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if fn is None:
        raise ValueError(f"{where}: defines no function {name}(...) (a node's function is named after its file)")
    a = fn.args
    if a.vararg or a.kwarg:
        raise ValueError(f"{where}: *args and **kwargs are not allowed: inputs and settings are named")
    inputs = [x.arg for x in a.posonlyargs + a.args]
    if a.defaults:
        raise ValueError(f"{where}: inputs have no defaults; put settings after * (keyword-only)")
    settings = {x.arg: _setting(x, d, f"{where}: setting {x.arg}") for x, d in zip(a.kwonlyargs, a.kw_defaults)}
    consts = {}
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) and n.value else []
        for t in targets:
            if isinstance(t, ast.Name) and t.id in ("METRICS", "SCHEMA", "GROUP"):
                consts[t.id] = _literal(n.value, f"{where}: {t.id}")
    view = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "view"), None)
    if view is not None and len(view.args.args) != 1:
        raise ValueError(f"{where}: view takes one argument, the node's output")
    downloads = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "downloads"), None)
    if downloads is not None and len(downloads.args.args) != 1:
        raise ValueError(f"{where}: downloads takes one argument, the node's output")
    doc = ast.get_docstring(tree) or ast.get_docstring(fn) or ""
    compute_sha = sha256(_compute_source(tree).encode())
    return {"name": name, "file": f"nodes/{path.name}", "doc": doc, "desc": doc.strip().split("\n")[0] if doc else "",
            "inputs": inputs, "settings": settings, "metrics": _metric_decls(where, name, consts.get("METRICS")),
            "schema": consts.get("SCHEMA") or {}, "group": consts.get("GROUP"), "view": view is not None,
            "downloads": downloads is not None,
            "compute_sha": compute_sha}


def read_graph(app_dir: Path, datasets: dict) -> dict:
    """Every node of the app, the edges their inputs make, and their order."""
    nd = app_dir / "nodes"
    if not nd.is_dir():
        raise ValueError(f"{app_dir.name}: no nodes/ directory (one Python file per node)")
    nodes = {}
    for p in sorted(nd.glob("*.py")):
        if p.name.startswith("_"):
            continue
        n = read_node(p, p.read_text())
        nodes[n["name"]] = n
    if not nodes:
        raise ValueError(f"{app_dir.name}: nodes/ holds no node")
    clash = set(nodes) & set(datasets)
    if clash:
        raise ValueError(f"{', '.join(sorted(clash))}: both a node and a dataset; rename one")
    edges = []
    for n in nodes.values():
        n["deps"] = []
        for i in n["inputs"]:
            if i in nodes:
                n["deps"].append({"name": i, "kind": "node"})
                edges.append({"from": i, "to": n["name"]})
            elif i in datasets:
                n["deps"].append({"name": i, "kind": "dataset"})
            else:
                raise ValueError(f"node {n['name']}: input {i!r} is neither a node ({', '.join(nodes)}) "
                                 f"nor a dataset ({', '.join(datasets) or 'none'})")
        for ds in n["schema"]:
            if ds not in n["inputs"] or ds not in datasets:
                raise ValueError(f"node {n['name']}: SCHEMA names {ds!r}, which is not a dataset it reads")
    return {"nodes": nodes, "edges": edges, "order": _toposort(list(nodes), edges)}


def _toposort(nodes, edges):
    indeg = {n: 0 for n in nodes}
    for e in edges:
        indeg[e["to"]] += 1
    ready, out = [n for n in nodes if indeg[n] == 0], []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for e in edges:
            if e["from"] == n:
                indeg[e["to"]] -= 1
                if indeg[e["to"]] == 0:
                    ready.append(e["to"])
    if len(out) != len(nodes):
        stuck = sorted(set(nodes) - set(out))
        raise ValueError(f"the nodes' inputs make a cycle: {', '.join(stuck)}")
    return out


def read_groups(decl, graph: dict) -> dict:
    """Groups of nodes (GROUP = "..." in a node file), documented in app.yaml `groups:`."""
    out = {}
    for n in graph["order"]:
        g = graph["nodes"][n]["group"]
        if g:
            out.setdefault(str(g), {"name": str(g), "nodes": [], "doc": ""})["nodes"].append(n)
    for g, d in (decl or {}).items():
        if g not in out:
            raise ValueError(f"groups: no node has GROUP = {g!r}")
        d = d or {}
        if set(d) - {"doc"}:
            raise ValueError(f"groups: {g}: unknown keys {sorted(set(d) - {'doc'})}")
        out[g]["doc"] = str(d.get("doc") or "")
    return out


# ------------------------------------------------------------------ datasets
_INSPECT: dict = {}


def _dataset(project_dir: Path, name: str, cfg: dict, plugins: dict) -> dict:
    if not _NAME.match(name):
        raise ValueError(f"dataset {name!r}: a dataset's name is a Python name (nodes take it as an input)")
    if not isinstance(cfg, dict) or "path" not in cfg:
        raise ValueError(f"dataset {name}: want at least `path:` (relative to the project)")
    rel = posixpath.normpath(str(cfg["path"]))
    if rel.startswith("../") or posixpath.isabs(rel):
        raise ValueError(f"dataset {name}: path {rel!r} points outside the project")
    path = project_dir / rel
    if path.is_file():
        files, kind = [path], "file"
    elif path.is_dir():
        files, kind = sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")), "dir"
    else:
        raise FileNotFoundError(f"dataset {name}: {path} does not exist")
    at = posixpath.normpath(str(cfg.get("at", rel)))
    if at.startswith("../") or posixpath.isabs(at):
        raise ValueError(f"dataset {name}: at {at!r} is not a plain app path")
    inline = cfg.get("inline", True)
    if not inline and kind == "dir":
        raise ValueError(f"dataset {name}: only file datasets can be provided by the user (inline: false)")
    out = {"name": name, "kind": kind, "path": rel, "at": at, "targets": [at], "desc": cfg.get("desc", ""), "inline": bool(inline)}
    rest = {k: v for k, v in cfg.items() if k not in DATASET_KEYS}
    if cfg.get("format"):
        p, ad = plugin_mod.find_format(cfg["format"], plugins)
        if kind != "file":
            raise ValueError(f"dataset {name}: format {cfg['format']} takes a file, not a directory")
        try:
            opts = ad.check_options(rest)
            st = path.stat()
            key = (str(path), st.st_size, st.st_mtime_ns, cfg["format"], json.dumps(opts, sort_keys=True))
            if key not in _INSPECT:
                _INSPECT[key] = ad.inspect(str(path), opts)
            info = _INSPECT[key]
        except ValueError as e:
            raise ValueError(f"dataset {name} ({path.name}): {e}") from None
        comp = plugin_mod.component(p, p["formats"][cfg["format"]])
        return {**out, "format": ad.NAME, "options": opts, "info": info,
                "files": [{"rel": path.name, "size": st.st_size, "sha256": None, "src": str(path)}],
                "size": st.st_size, "sha256": info["fingerprint"],
                "adapter": {"plugin": p["name"], "path": comp, "version": ad.VERSION, "packages": list(ad.PACKAGES),
                            "output": ad.OUTPUT, "unit": ad.UNIT, "describe": ad.describe(opts), "sha256": sha256(p["files"][comp])}}
    if rest:
        raise ValueError(f"dataset {name}: unknown keys {sorted(rest)} (options need a `format:`; "
                         f"a schema is declared by the node that reads it: SCHEMA)")
    entries = []
    for f in files:
        r = f.name if kind == "file" else f.relative_to(path).as_posix()
        entries.append({"rel": r, "size": f.stat().st_size, "sha256": sha256_file(f), "src": str(f)})
    return {**out, "files": entries, "size": sum(e["size"] for e in entries),
            "sha256": sha256("".join(f"{e['rel']}\0{e['sha256']}\n" for e in entries).encode())}


# ------------------------------------------------------------------ views
def _placement(where: str, at: str, graph: dict, groups: dict) -> dict:
    at = str(at or "")
    kind, _, target = at.partition(":")
    if at in ("data", "overview"):
        return {"kind": at, "target": None}
    if kind == "node" and target in graph["nodes"]:
        return {"kind": "node", "target": target}
    if kind == "group" and target in groups:
        return {"kind": "group", "target": target}
    raise ValueError(f"{where}: at {at!r} must be data, overview, node:<node> or group:<group>")


def read_views(app_plugins: dict, graph: dict, groups: dict, datasets: dict) -> dict:
    """The sandboxed views of the app's plugins (docs/views.md). What a view reads says when it
    is shown: one that reads datasets (every Data modal view) before any run, one that reads
    nodes' outputs once they have run."""
    views = {}
    for p in app_plugins.values():
        for name, v in (p["views"] or {}).items():
            where = f"plugin {p['name']}: view {name}"
            if not re.fullmatch(r"[A-Za-z0-9_-]+", str(name)) or name in views:
                raise ValueError(f"{where}: a view name is letters, digits, '-' or '_', and unique")
            v = v or {}
            if set(v) - VIEW_KEYS:
                raise ValueError(f"{where}: unknown keys {sorted(set(v) - VIEW_KEYS)}")
            at = _placement(where, v.get("at"), graph, groups)
            code = [plugin_mod.component(p, posixpath.normpath(f)) for f in v.get("code") or []]
            css = [plugin_mod.component(p, posixpath.normpath(f)) for f in v.get("css") or []]
            if not code:
                raise ValueError(f"{where}: needs at least one `code` file")
            reads = [str(r) for r in v.get("reads") or []]
            before = at["kind"] == "data" or all(r in datasets for r in reads)
            for r in reads:
                if before and r not in datasets:
                    raise ValueError(f"{where}: reads {r!r}, which is not a dataset; the Data modal shows it before any run, so it reads data")
                if not before and r not in graph["nodes"]:
                    raise ValueError(f"{where}: reads {r!r}, " + ("a dataset, and nodes: a view reads datasets (shown before any run) "
                                     "or nodes' outputs (shown once they have run), not both" if r in datasets else "which is not a node or a dataset"))
            can = list(v.get("can") or [])
            allowed = ("params", "query", "download") if at["kind"] == "data" else ("query", "download")
            if set(can) - set(allowed):
                raise ValueError(f"{where}: can {sorted(set(can) - set(allowed))}; allowed here: {list(allowed)}")
            views[name] = {"name": name, "plugin": p["name"], "title": v.get("title") or name, "at": at,
                           "before_run": before, "code": code, "css": css, "reads": reads, "can": can,
                           "paths": [datasets[r]["at"] for r in reads] if before else []}
    return views


# ------------------------------------------------------------------ runs
def read_run(path: Path) -> dict:
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or doc.get("format") != RUN_FORMAT:
        old = isinstance(doc, dict) and str(doc.get("format", "")).startswith("blocks-run/")
        raise ValueError(f"{path.name} is not a {RUN_FORMAT} run file" + (f" ({doc['format']}: re-record it with `blocks baseline`)" if old else ""))
    return doc


def read_baseline(path: Path) -> dict | None:
    """The app's baseline; one of an older run format counts as none, so that `blocks baseline`
    can record it again."""
    if not path.is_file():
        return None
    try:
        return read_run(path)
    except ValueError:
        return None


def run_name(rel: str) -> str:
    rel = rel[:-len(RUN_SUFFIX)]
    return rel[len("superseded/"):] if rel.startswith("superseded/") else rel


def read_shipped_runs(app_dir: Path, decl) -> dict[str, dict]:
    out = {}
    for rel in decl or []:
        rel = posixpath.normpath(str(rel))
        ok = "/" not in rel or (rel.startswith("superseded/") and rel.count("/") == 2)
        if not ok or not rel.endswith(RUN_SUFFIX) or not (app_dir / rel).is_file():
            raise ValueError(f"runs: {rel!r} must be a *{RUN_SUFFIX} file of the app or of superseded/<name>/")
        if posixpath.basename(rel) == BASELINE:
            doc = read_baseline(app_dir / rel)   # an older format: not shipped until `blocks baseline` records it again
            if doc:
                out[run_name(rel)] = doc
        else:
            out[run_name(rel)] = read_run(app_dir / rel)
    return out


def read_overview(decl, graph) -> list[dict]:
    """app.yaml `overview:`: blocks of nodes' views placed on the overview too."""
    out = []
    for item in decl or []:
        if not isinstance(item, dict) or set(item) != {"node", "block"} or item["node"] not in graph["nodes"]:
            raise ValueError(f"overview: {item!r}: want {{node: <node>, block: <block id>}}")
        if not graph["nodes"][item["node"]]["view"]:
            raise ValueError(f"overview: node {item['node']} has no view(out)")
        out.append({"node": item["node"], "block": str(item["block"])})
    return out


# ------------------------------------------------------------------ the app
def projects_dir(repo: Path) -> Path:
    return repo / "projects"


def projects(repo: Path) -> list[str]:
    root = projects_dir(repo)
    return sorted(p.name for p in root.iterdir() if (p / "app.yaml").is_file()) if root.is_dir() else []


def superseded(repo: Path, project: str) -> list[str]:
    root = projects_dir(repo) / project / "superseded"
    return sorted(p.name for p in root.iterdir() if (p / "app.yaml").is_file()) if root.is_dir() else []


def app_dir(repo: Path, project: str, version: str | None = None) -> Path:
    d = projects_dir(repo) / project
    return d / "superseded" / version if version else d


def is_bookkeeping(rel: str) -> bool:
    top = rel.split("/")[0]
    return top in BOOKKEEPING or top in RESERVED_DIRS or ("/" not in rel and rel.endswith(RUN_SUFFIX))


def load_app(repo: Path, project: str, version: str | None = None) -> dict:
    project_dir = projects_dir(repo) / project
    adir = app_dir(repo, project, version)
    app_id = f"{project}/{version}" if version else project
    if not (adir / "app.yaml").is_file():
        raise FileNotFoundError(f"{adir / 'app.yaml'} not found")
    cfg = _yaml(adir / "app.yaml")
    if set(cfg) - APP_KEYS:
        raise ValueError(f"{app_id}: unknown keys {sorted(set(cfg) - APP_KEYS)} in app.yaml")
    plugins = plugin_mod.load_all(cfg.get("plugins"), adir)
    datasets = {n: _dataset(project_dir, n, c, plugins) for n, c in (cfg.get("data") or {}).items()}
    graph = read_graph(adir, datasets)
    groups = read_groups(cfg.get("groups"), graph)
    for n in graph["nodes"].values():
        for ds, sch in n["schema"].items():
            if datasets[ds].get("schema"):
                raise ValueError(f"node {n['name']}: {ds} already has a schema, from node {datasets[ds]['schema_node']}")
            try:
                datasets[ds]["schema"], datasets[ds]["schema_node"] = table_schema.check(sch), n["name"]
            except ValueError as e:
                raise ValueError(f"node {n['name']}: SCHEMA {ds}: {e}") from None
    files = {}
    for p in sorted(adir.rglob("*")):
        rel = p.relative_to(adir).as_posix()
        parts = rel.split("/")
        if p.is_file() and not is_bookkeeping(rel) and not any(x.startswith(".") or x == "__pycache__" for x in parts):
            files[rel] = p.read_bytes()
    settings = {f"{n}.{k}": s for n in graph["order"] for k, s in graph["nodes"][n]["settings"].items()}
    views = read_views(plugins, graph, groups, datasets)
    packages = list(dict.fromkeys(cfg.get("packages") or []))
    helpers = {p: sha256(b) for p, b in files.items() if p.endswith(".py") and not p.startswith("nodes/")}
    code_sha = sha256(json.dumps({
        "nodes": {n: graph["nodes"][n]["compute_sha"] for n in graph["order"]},
        "helpers": helpers,
        "data": {d["at"]: d["sha256"] for d in datasets.values()},
        "packages": sorted(packages),
        "adapters": {d["format"]: d["adapter"]["sha256"] for d in datasets.values() if d.get("format")},
    }, sort_keys=True).encode())
    plugin_files = {p: b for pl in plugins.values() for p, b in pl["files"].items()}
    view_srcs = {n: sha256(files[graph["nodes"][n]["file"]]) for n in graph["order"]
                 if graph["nodes"][n]["view"] or graph["nodes"][n]["downloads"]}
    ui_sha = sha256(json.dumps({"views": views, "node_files": view_srcs,
                                "files": {p: sha256(b) for p, b in plugin_files.items()}}, sort_keys=True).encode())
    baseline = read_baseline(adir / BASELINE)
    return {
        "project": project, "version": version, "id": app_id, "dir": adir, "project_dir": project_dir,
        "title": cfg.get("title", project), "question": cfg.get("question", ""), "description": cfg.get("description", ""),
        "graph": graph, "groups": groups, "settings": settings, "datasets": datasets, "files": files,
        "metrics": [m for n in graph["order"] for m in graph["nodes"][n]["metrics"]],
        "plugins": plugins, "views": views, "packages": packages, "overview": read_overview(cfg.get("overview"), graph),
        "verify": {**DEFAULT_TOL, **(cfg.get("verify") or {})}, "ui": read_ui(cfg.get("ui"), cfg.get("runs")),
        "docs": [d for d in cfg.get("docs") or [] if d in files], "env": cfg.get("env") or {},
        "code_sha": code_sha, "ui_sha": ui_sha, "baseline": baseline, "runs": read_shipped_runs(adir, cfg.get("runs")),
        "superseded": superseded(repo, project) if not version else [],
    }


UI_KEYS = {"theme", "runs"}


def read_ui(decl, shipped) -> dict:
    """app.yaml `ui:`: the theme, and whether the app has runs (the run log, previous runs,
    comparing with a reference; on by default). Without them a viewer changes data and
    settings, runs, and downloads; making the app still verifies against its baseline."""
    ui = dict(decl or {})
    if set(ui) - UI_KEYS:
        raise ValueError(f"ui: unknown keys {sorted(set(ui) - UI_KEYS)} (have: {sorted(UI_KEYS)})")
    ui["runs"] = ui.get("runs", True)
    if not isinstance(ui["runs"], bool):
        raise ValueError("ui: runs is true or false")
    if not ui["runs"] and shipped:
        raise ValueError("runs: ships previous runs, but ui: runs: false turns runs off")
    return ui


def parse_target(t: str) -> tuple[str, str | None]:
    project, _, version = t.strip("/").partition("/")
    return project, version or None


def find_apps(repo: Path, targets: list[str] | None = None, all_versions: bool = False) -> list[tuple[str, str | None]]:
    out = []
    have = projects(repo)
    for t in targets or have:
        project, version = parse_target(t)
        if project not in have:
            raise ValueError(f"no project {project!r} (have: {', '.join(have) or 'none'})")
        old = superseded(repo, project)
        if version and version not in old:
            raise ValueError(f"no superseded app {project}/{version} (have: {', '.join(old) or 'none'})")
        out.append((project, version))
        if not targets and all_versions:
            out += [(project, v) for v in old]
    return out
