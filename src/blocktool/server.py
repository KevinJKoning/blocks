"""The local dev server for linked builds, while apps are made: `blocks serve`.

Routes (127.0.0.1 only):
  /                                   the projects, each with its current app and superseded versions
  /<project>/                         the project's app, rebuilt from its sources on every request
  /<project>/superseded/<name>/       a superseded version of it
  /_runtime/pyodide/<ver>/<file>      pinned runtime files from .cache/ (immutable, so the
  /_runtime/pele/<ver>/pele.global.js   browser caches them once for every app build)
  /_data/<app>/<dataset>/<rel>        an app's datasets, read in place (ETag, revalidated);
                                      <app> is the project, or <project>--<name> for a superseded one
  /_api/runs/<app>                    GET the run log, POST one run file (appends build/<app>/runs.jsonl)

Each app page is a single HTML file holding the app's code, params, plugins and shipped
runs; only the heavy, shared parts (runtime, pele, data) come from here.
"""
from __future__ import annotations

import json
import mimetypes
import re
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import html

from . import build, spec
from blocks import runs

from .runlog import read_runs, runs_path
from .runtime import Runtime

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_RUN_BYTES = 8 << 20   # a run file, its blocks included


def _safe(*parts: str) -> bool:
    return all(_NAME.match(p) for p in parts)


def app_of(name: str) -> tuple[str, str | None]:
    """`project` or `project--version` (as in /_data/ and /_api/ URLs)."""
    project, _, version = name.partition("--")
    return project, version or None


def known_app(repo: Path, project: str, version: str | None) -> bool:
    return project in spec.projects(repo) and (not version or version in spec.superseded(repo, project))


def index(repo: Path) -> bytes:
    """The projects: a static page (no scripts) linking each app."""
    rows = []
    for p in spec.projects(repo):
        try:
            title = spec._yaml(spec.app_dir(repo, p) / "app.yaml").get("title", p)
        except Exception:  # noqa: BLE001 - a broken app.yaml still gets a row
            title = p
        old = "".join(f' <a class="old" href="/{p}/superseded/{v}/">{html.escape(v)}</a>' for v in spec.superseded(repo, p))
        rows.append(f'<li><a href="/{p}/">{html.escape(str(title))}</a> <span class="muted">{p}</span>'
                    + (f'<div class="muted">superseded:{old}</div>' if old else "") + "</li>")
    body = "".join(rows) or "<li>No projects yet: <code>proto new NAME</code>.</li>"
    style = ("body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:48px auto;padding:0 16px;color:#222}"
             "a{color:#205ea6;font-weight:600;text-decoration:none}a.old{font-weight:400;margin-left:6px}"
             "li{margin:10px 0}.muted{color:#777;font-size:13px}")
    return (f"<!DOCTYPE html><html lang=en><head><meta charset=utf-8><title>blocks</title>"
            f"<meta http-equiv=Content-Security-Policy content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            f"<style>{style}</style></head><body><h1>Projects</h1><ul>{body}</ul></body></html>").encode()




class Handler(BaseHTTPRequestHandler):
    server_version = "blocks-serve"
    repo: Path
    runtime: Runtime
    quiet = False
    _append = threading.Lock()

    def log_message(self, fmt, *args):  # noqa: D102
        if not self.quiet:
            super().log_message(fmt, *args)

    # -- responses ------------------------------------------------------------
    def _send(self, status, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status, msg: str):
        self._send(status, (msg + "\n").encode(), "text/plain; charset=utf-8", {"Cache-Control": "no-store"})

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(status, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def _host_ok(self) -> bool:
        # Refuse requests addressed to another name (DNS rebinding): only loopback names.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    # -- routing --------------------------------------------------------------
    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "loopback hosts only")
        path = unquote(urlsplit(self.path).path)
        parts = [p for p in path.split("/") if p]
        try:
            if not parts or parts == ["index.html"]:
                return self._send(HTTPStatus.OK, index(self.repo), "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
            if parts[0] == "_runtime":
                return self._runtime(parts[1:])
            if parts[0] == "_data":
                return self._data(parts[1:])
            if parts[0] == "_api" and parts[1:2] == ["runs"] and len(parts) == 3 and _safe(parts[2]):
                return self._json({"runs": read_runs(runs_path(self.repo, *app_of(parts[2])))})
            app = self._app_parts(parts)
            if app and not path.endswith("/") and parts[-1] != "index.html":
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", path + "/")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            if app:
                return self._app(*app)
        except Exception:  # noqa: BLE001 - report build errors in the browser
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, traceback.format_exc())
        return self._error(HTTPStatus.NOT_FOUND, f"not found: {path}")

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "loopback hosts only")
        parts = [p for p in unquote(urlsplit(self.path).path).split("/") if p]
        if not (len(parts) == 3 and parts[:2] == ["_api", "runs"] and _safe(parts[2])):
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        # application/json is not a "simple" content type, so other origins cannot post here
        # without a CORS preflight, which this server never approves.
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "want application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_RUN_BYTES:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "run record too large")
        try:
            run = json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return self._error(HTTPStatus.BAD_REQUEST, "not JSON")
        if not isinstance(run, dict) or run.get("format") != runs.FORMAT or not isinstance(run.get("name"), str):
            return self._error(HTTPStatus.BAD_REQUEST, f"want a {runs.FORMAT} run file")
        if not known_app(self.repo, *app_of(parts[2])):
            return self._error(HTTPStatus.NOT_FOUND, "no such app")
        dest = runs_path(self.repo, *app_of(parts[2]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._append, dest.open("a") as f:
            f.write(json.dumps(run, separators=(",", ":")) + "\n")
        return self._json({"ok": True, "name": run["name"]})

    # -- handlers ---------------------------------------------------------------
    @staticmethod
    def _app_parts(parts: list[str]) -> tuple[str, str | None] | None:
        """/<project>/ or /<project>/superseded/<name>/ (optionally .../index.html)."""
        if parts[-1:] == ["index.html"]:
            parts = parts[:-1]
        if len(parts) == 1 and _safe(parts[0]) and not parts[0].startswith("_"):
            return parts[0], None
        if len(parts) == 3 and parts[1] == "superseded" and _safe(parts[0], parts[2]):
            return parts[0], parts[2]
        return None

    def _app(self, project: str, version: str | None):
        if not known_app(self.repo, project, version):
            return self._error(HTTPStatus.NOT_FOUND, f"no app {project}{'/' + version if version else ''}")
        page, _ = build.build(self.repo, project, version, inline=False, runtime=self.runtime)
        dest = build.output_path(self.repo, project, version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(page)
        self._send(HTTPStatus.OK, page, "text/html; charset=utf-8", {"Cache-Control": "no-cache"})

    def _runtime(self, parts):
        immutable = {"Cache-Control": "public, max-age=31536000, immutable"}
        rt = self.runtime
        if len(parts) == 3 and parts[0] == "pyodide" and parts[1] == rt.version and _safe(parts[2]):
            try:
                data = rt.file(parts[2])
            except KeyError:
                return self._error(HTTPStatus.NOT_FOUND, f"{parts[2]} is not part of Pyodide {rt.version}")
            ctype = {".wasm": "application/wasm", ".mjs": "text/javascript", ".json": "application/json",
                     ".zip": "application/zip"}.get(Path(parts[2]).suffix, "application/octet-stream")
            return self._send(HTTPStatus.OK, data, ctype, immutable)
        if parts == ["pele", rt.pins["pele"]["version"], "pele.global.js"]:
            return self._send(HTTPStatus.OK, rt.pele(), "text/javascript", immutable)
        return self._error(HTTPStatus.NOT_FOUND, "unknown runtime file")

    def _data(self, parts):
        if len(parts) < 3 or not _safe(parts[0], parts[1]):
            return self._error(HTTPStatus.NOT_FOUND, "want /_data/<app>/<dataset>/<file>")
        project, version = app_of(parts[0])
        if not known_app(self.repo, project, version):
            return self._error(HTTPStatus.NOT_FOUND, f"no app {parts[0]}")
        d = spec.load_app(self.repo, project, version)["datasets"].get(parts[1])
        rel = "/".join(parts[2:])
        f = next((f for f in (d or {}).get("files", []) if f["rel"] == rel), None)
        if not f:
            return self._error(HTTPStatus.NOT_FOUND, f"no file {rel} in dataset {parts[1]}")
        etag = f'"{(f["sha256"] or d["sha256"])[:32]}"'   # a format dataset: its fingerprint
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            for k, v in headers.items():
                self.send_header(k, v)
            return self.end_headers()
        path = Path(f["src"])
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(rel)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as src:
            while block := src.read(1 << 20):
                self.wfile.write(block)


class Server(ThreadingHTTPServer):
    # socketserver listens with a backlog of 5. An app page opens many short connections at
    # once (one per dataset file and runtime file, each closed after its response), and when
    # the accept loop falls behind, macOS resets the connections that overflow the queue: the
    # browser sees ERR_CONNECTION_RESET and the dataset fails to load.
    request_queue_size = 128
    daemon_threads = True


def make_server(repo: Path, port: int = 8765, quiet: bool = False) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"repo": repo, "runtime": Runtime(repo), "quiet": quiet})
    return Server(("127.0.0.1", port), handler)


def background(repo: Path) -> tuple[ThreadingHTTPServer, str]:
    """A quiet server on a free port in a daemon thread; returns (server, base URL)."""
    srv = make_server(repo, port=0, quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
