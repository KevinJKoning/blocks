"""An app's exploration run log: runs.jsonl in the app's directory, one JSON run per line."""
from __future__ import annotations

import json
from pathlib import Path

from .spec import app_dir


def runs_path(repo: Path, project: str, version: str | None = None) -> Path:
    return app_dir(repo, project, version) / "runs.jsonl"


def read_runs(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue   # a torn last line from an interrupted write
    return out
