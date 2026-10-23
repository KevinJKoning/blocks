"""Plugins: what varies by app and cannot be a report block. See docs/plugins.md.

A plugin is a directory with a `plugin.yaml` and the files it names. An app lists the
plugins it uses (`app.yaml` `plugins:`); a name is looked up in the app's own `plugins/`
directory first, then among the built-in plugins (`src/proto/plugins/`).

plugin.yaml
  title, description     what it adds, shown in the app's Settings
  formats                {format: module}: dataset adapters (docs/dataset-adapters.md); a
                         module runs natively (spec.py) and in the ingest worker, so its
                         module level uses the standard library only
  views                  sandboxed views, placed on a report page (docs/views.md)

Nothing a plugin has runs in the page itself: adapters run in a worker, views in sandboxed
frames.
"""
from __future__ import annotations

import hashlib
import importlib.util
import posixpath
import re
from importlib import resources
from pathlib import Path
from types import ModuleType

import yaml

BUILTIN_DIR = Path(str(resources.files("blocktool").joinpath("plugins")))
KEYS = {"title", "description", "formats", "views"}
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def builtin_names() -> list[str]:
    return sorted(p.name for p in BUILTIN_DIR.iterdir() if (p / "plugin.yaml").is_file())


def locate(name: str, app_dir: Path | None) -> tuple[Path, bool]:
    """(plugin directory, built-in?) for a name an app lists."""
    if not _NAME.match(str(name)):
        raise ValueError(f"plugin {name!r}: a plugin name is lower-case letters, digits and '-'")
    if app_dir is not None and (app_dir / "plugins" / name / "plugin.yaml").is_file():
        return app_dir / "plugins" / name, False
    if (BUILTIN_DIR / name / "plugin.yaml").is_file():
        return BUILTIN_DIR / name, True
    raise ValueError(f"no plugin {name!r} (built-in: {', '.join(builtin_names())}; or add plugins/{name}/plugin.yaml)")


def _files(where: str, root: Path, rels, ext: tuple[str, ...]) -> list[str]:
    out = []
    for rel in rels or []:
        rel = posixpath.normpath(str(rel))
        if rel.startswith("../") or rel.startswith("/") or not rel.endswith(ext):
            raise ValueError(f"{where}: {rel!r} must be a {' or '.join(ext)} file inside the plugin")
        if not (root / rel).is_file():
            raise ValueError(f"{where}: {rel} does not exist")
        out.append(rel)
    return out


def load(name: str, app_dir: Path | None) -> dict:
    """One plugin's declaration, checked, with its files' bytes (keyed by component path)."""
    root, builtin = locate(name, app_dir)
    where = f"plugin {name}"
    decl = yaml.safe_load((root / "plugin.yaml").read_text()) or {}
    unknown = set(decl) - KEYS
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)} in plugin.yaml (have: {', '.join(sorted(KEYS))})")
    formats = {str(f): _files(where, root, [m], (".py",))[0] for f, m in (decl.get("formats") or {}).items()}
    used = list(formats.values())
    views = decl.get("views") or {}
    for v in views.values():
        used += _files(f"{where} views", root, list((v or {}).get("code") or []) + list((v or {}).get("css") or []), (".js", ".css"))
    files = {f"plugins/{name}/{rel}": (root / rel).read_bytes() for rel in dict.fromkeys(used)}
    return {"name": name, "dir": root, "builtin": builtin, "title": decl.get("title") or name,
            "description": decl.get("description") or "", "formats": formats, "views": views, "files": files}


def load_all(names, app_dir: Path | None) -> dict[str, dict]:
    out = {}
    for n in names or []:
        if n in out:
            raise ValueError(f"plugin {n} is listed twice")
        out[n] = load(n, app_dir)
    seen: dict[str, str] = {}
    for p in out.values():
        for f in p["formats"]:
            if f in seen:
                raise ValueError(f"format {f!r} is provided by both {seen[f]} and {p['name']}")
            seen[f] = p["name"]
    return out


_MODULES: dict[tuple[str, str], ModuleType] = {}


def module(p: dict, rel: str) -> ModuleType:
    """A plugin's adapter module, imported natively."""
    path = p["dir"] / rel
    key = (str(path), hashlib.sha256(path.read_bytes()).hexdigest())
    if key not in _MODULES:
        spec = importlib.util.spec_from_file_location(f"proto_plugin_{p['name'].replace('-', '_')}_{Path(rel).stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULES[key] = mod
    return _MODULES[key]


def component(p: dict, rel: str) -> str:
    return f"plugins/{p['name']}/{rel}"


def find_format(fmt: str, plugins: dict[str, dict]) -> tuple[dict, ModuleType]:
    for p in plugins.values():
        if fmt in p["formats"]:
            return p, module(p, p["formats"][fmt])
    have = {f: n for n in builtin_names() for f in load(n, None)["formats"]}
    hint = f"; the built-in plugin {have[fmt]} reads it: add it to plugins:" if fmt in have else ""
    raise ValueError(f"unknown dataset format {fmt!r}{hint}")


def builtin_format(fmt: str) -> tuple[dict, ModuleType]:
    """A format from the built-in plugins (for `blocks convert`, outside any app)."""
    return find_format(fmt, {n: load(n, None) for n in builtin_names()})
