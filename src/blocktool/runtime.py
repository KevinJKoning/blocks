"""The pinned browser runtime (Pyodide + pele), cached locally and checked by hash.

Files are downloaded from the CDN on first use into `.cache/` and never trusted
unless their sha256 matches: core files and pele against runtime.lock.json, wheels
against the pinned pyodide-lock.json. The dev server serves them from the cache
(experimental builds); `build --inline` embeds them (final builds).
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from pathlib import Path

_lock = threading.Lock()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Runtime:
    def __init__(self, repo: Path):
        self.repo = repo
        self.pins = json.loads((repo / "runtime.lock.json").read_text())
        self.py = self.pins["pyodide"]
        self.version = self.py["version"]
        self.cache = repo / ".cache" / "pyodide" / self.version
        self._pyodide_lock = None

    # -- files ------------------------------------------------------------
    def _fetch(self, url: str, dest: Path, want: str) -> bytes:
        with _lock:
            if dest.is_file():
                data = dest.read_bytes()
                if sha256(data) == want:
                    return data
            with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 (pinned https URL)
                data = r.read()
            if sha256(data) != want:
                raise ValueError(f"{url}: sha256 {sha256(data)} does not match the pin {want}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return data

    def lock(self) -> dict:
        if self._pyodide_lock is None:
            self._pyodide_lock = json.loads(self.file("pyodide-lock.json"))
        return self._pyodide_lock

    def expected_sha(self, name: str) -> str:
        if name in self.py["core"]:
            return self.py["core"][name]
        for pkg in self.lock()["packages"].values():
            if pkg["file_name"] == name:
                return pkg["sha256"]
        raise KeyError(f"{name} is not part of Pyodide {self.version}")

    def file(self, name: str) -> bytes:
        """A runtime file by name (core file or wheel), from cache or the CDN."""
        if "/" in name or name.startswith("."):
            raise KeyError(name)
        return self._fetch(self.py["cdn"] + name, self.cache / name, self.expected_sha(name))

    def pele(self) -> bytes:
        p = self.pins["pele"]
        return self._fetch(p["url"], self.repo / ".cache" / "pele" / p["version"] / "pele.global.js", p["sha256"])

    # -- packages -----------------------------------------------------------
    def closure(self, packages: list[str]) -> list[str]:
        """Requested packages plus the always-loaded ones and every dependency, in lock order."""
        pk = self.lock()["packages"]
        want, stack = set(), [*self.py.get("always", []), *packages]
        while stack:
            n = stack.pop().lower()
            if n in want:
                continue
            if n not in pk:
                raise KeyError(f"package {n!r} has no Pyodide {self.version} build "
                               "(pure-Python code can live in the app itself)")
            want.add(n)
            stack += pk[n].get("depends", [])
        return [n for n in pk if n in want]

    def package_files(self, packages: list[str]) -> list[str]:
        pk = self.lock()["packages"]
        return [pk[n]["file_name"] for n in self.closure(packages)]

    def versions(self, packages: list[str]) -> dict:
        pk = self.lock()["packages"]
        return {n: pk[n]["version"] for n in self.closure(packages)}
