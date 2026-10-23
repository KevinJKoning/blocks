"""An app's exploration run log: runs.jsonl, one JSON run per line, kept by the dev server
under build/ next to the app's linked page: local working state, never part of the project."""
from __future__ import annotations

import json
from pathlib import Path

from .build import output_path


def runs_path(repo: Path, project: str, version: str | None = None) -> Path:
    return output_path(repo, project, version).parent / "runs.jsonl"


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
