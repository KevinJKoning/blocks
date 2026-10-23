import json
import shutil
import urllib.request
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SENSOR = "sensor-calibration"


def make_repo(dest: Path, projects=(SENSOR,)) -> Path:
    """A throwaway blocks repo: the runtime pins, the shared download cache and copies of projects."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "runtime.lock.json", dest)
    (dest / ".cache").symlink_to(REPO / ".cache")
    for p in projects:
        shutil.copytree(REPO / "projects" / p, dest / "projects" / p,
                        ignore=shutil.ignore_patterns("runs.jsonl", "__pycache__"))
    return dest


def edit_yaml(path: Path, fn) -> None:
    cfg = yaml.safe_load(path.read_text())
    fn(cfg)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


@pytest.fixture
def repo(tmp_path) -> Path:
    return make_repo(tmp_path / "repo")


@pytest.fixture
def server(repo):
    from blocktool.server import background
    srv, base = background(repo)
    yield base
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    from blocktool.harvest import browser as launch
    with launch() as b:
        yield b


@pytest.fixture
def open_app(browser):
    """open_app(url) -> a page whose app has booted (runtime started, datasets loaded)."""
    contexts = []

    def go(url: str):
        ctx = browser.new_context()
        contexts.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(300_000)
        page.goto(url)
        page.wait_for_function("() => !!window.blocksApp")
        page.evaluate("window.blocksApp.whenReady.then(() => true)")
        assert page.evaluate("window.blocksApp.state.fatal || null") is None
        return page
    yield go
    for c in contexts:
        c.close()


def tool(page, name: str, args: dict | None = None):
    return page.evaluate("([n, a]) => window.blocksApp.tools[n](a)", [name, args or {}])


def verified(page, repo: Path, app_id: str) -> str:
    """What `blocks run` concludes about the page's last run: its run file against the app's
    recorded baseline (verification is the tooling's, never the page's)."""
    from blocktool import spec, verify
    a = spec.load_app(repo, *spec.parse_target(app_id))
    return verify.compare_runs(tool(page, "export_run")["run"], a["baseline"], a["verify"])["verified"]


def fetch(url: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def read_json(p: Path):
    return json.loads(p.read_text())
