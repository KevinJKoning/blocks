"""blocktool: build, serve, run and verify blocks apps (docs/nodes.md). Native Python only
reads and packs; every node runs in Pyodide, in the page."""
from pathlib import Path


def find_repo(start: Path | None = None) -> Path:
    """The blocks repo: the nearest directory (from `start`, default cwd) holding runtime.lock.json."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "runtime.lock.json").is_file():
            return d
    raise FileNotFoundError(f"no runtime.lock.json in {here} or its parents; run inside a blocks repo")
