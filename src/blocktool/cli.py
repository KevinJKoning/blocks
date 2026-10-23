"""blocks: make an app of a graph of Python functions, and build it as one offline HTML file.

  blocks serve                      dev server: projects at /, apps at /<project>/, rebuilt per request
  blocks new PROJECT                start a project (a skeleton app)
  blocks baseline [TARGET…]         run apps headlessly and record baseline.run.json
  blocks run [TARGET…]              run apps headlessly and verify each against its baseline
  blocks build [TARGET…]            the app as one offline file (dist/<project>.html), verified
                                    from file:// with the network blocked against its baseline
  blocks supersede PROJECT NAME     keep a copy of the current app as superseded/NAME
  blocks check FILE.html            static integrity check of a built page
  blocks convert SRC DEST.parquet [--format F -o KEY=VALUE]
                                    convert a dataset to Parquet with DuckDB or a plugin's adapter (in Pyodide)

TARGET is `project` (its current app), `project/name` (a superseded version), or nothing
for every project's current app.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from . import build, find_repo, spec


def _targets(repo: Path, names: list[str]) -> list[tuple[str, str | None]]:
    return spec.find_apps(repo, names or None)


def cmd_serve(repo: Path, args) -> int:
    from .server import make_server
    srv = make_server(repo, port=args.port)
    print(f"blocks: serving {repo} at http://127.0.0.1:{srv.server_address[1]}/ (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_run(repo: Path, args, record_baseline=False) -> int:
    from . import harvest
    res = harvest.run_apps(repo, _targets(repo, args.targets), record_baseline=record_baseline)
    bad = [r["app"] for r in res if r["verified"] in ("error", "differs") or (not record_baseline and r["verified"] == "no-baseline")]
    if bad and not record_baseline:
        print(f"not verified: {', '.join(bad)}", file=sys.stderr)
    return 1 if bad else 0


SKELETON = {
    "app.yaml": "title: {project}\nquestion: >-\n  What the app answers.\ndescription: >-\n  How it answers it.\ndata: {{}}\n",
    "nodes/numbers.py": '"""Makes the numbers the app works on."""\nfrom typing import Annotated\n\nfrom blocks import Range\n\n\n'
                        "def numbers(*, n: Annotated[int, Range(1, 100)] = 10):\n    return list(range(1, n + 1))\n",
    "nodes/total.py": '"""Adds them up."""\nfrom blocks import ui\n\nMETRICS = {{"total": {{"label": "total", "goal": "max", "headline": True}}}}\n\n\n'
                      "def total(numbers):\n    return {{\"total\": sum(numbers), \"count\": len(numbers)}}\n\n\n"
                      "def view(out):\n    return [ui.metrics(), ui.markdown(f\"{{out['count']}} numbers.\")]\n",
}
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def cmd_new(repo: Path, args) -> int:
    project = args.project
    if not _PLAIN.match(project) or "--" in project:
        raise SystemExit("want a plain project name (letters, digits, '.', '_', '-'; no '--')")
    dest = spec.app_dir(repo, project)
    if dest.exists():
        raise SystemExit(f"{dest.relative_to(repo)} already exists")
    for rel, text in SKELETON.items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(text.format(project=project))
    print(f"created {dest.relative_to(repo)}; open it with `blocks serve`, then record a baseline with `blocks baseline {project}`")
    return 0


def cmd_supersede(repo: Path, args) -> int:
    """A copy of the current app (code, app.yaml, plugins, baseline; not its data, outputs or
    other superseded versions) under superseded/NAME, where it keeps running on the
    project's data so that its runs can be compared with the app's next version."""
    if not _PLAIN.match(args.name):
        raise SystemExit("want a plain name for the superseded version")
    a = spec.load_app(repo, args.project)
    dest = a["dir"] / "superseded" / args.name
    if dest.exists():
        raise SystemExit(f"{dest.relative_to(repo)} already exists")
    keep = set(a["files"]) | {"app.yaml"} | ({spec.BASELINE} if a["baseline"] else set())
    for rel in sorted(keep):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a["dir"] / rel, dest / rel)
    cfg = spec._yaml(dest / "app.yaml")
    if any(str(r).startswith("superseded/") for r in cfg.get("runs") or []):
        # the copy has no superseded/ of its own: it ships only its own runs
        import yaml
        cfg["runs"] = [r for r in cfg["runs"] if not str(r).startswith("superseded/")] or None
        (dest / "app.yaml").write_text(yaml.safe_dump({k: v for k, v in cfg.items() if v is not None}, sort_keys=False, allow_unicode=True))
    if (a["dir"] / "plugins").is_dir():
        shutil.copytree(a["dir"] / "plugins", dest / "plugins", ignore=shutil.ignore_patterns(".*", "__pycache__"))
    spec.load_app(repo, args.project, args.name)   # it must load as it is
    print(f"kept {a['id']} as {dest.relative_to(repo)}; serve it at /{args.project}/superseded/{args.name}/. "
          f"To ship its baseline with the app for comparison, add superseded/{args.name}/{spec.BASELINE} to runs: in app.yaml")
    return 0


def cmd_build(repo: Path, args) -> int:
    """The app as one offline file, verified: from file:// with every request blocked, every
    node must reproduce the app's baseline (metrics within tolerance, its output's digest),
    every view must be ready, and nothing may break the CSP or the integrity check."""
    from . import harvest
    from .runtime import Runtime
    failed = 0
    for project, version in _targets(repo, args.targets):
        a = spec.load_app(repo, project, version)
        base = a["baseline"]
        if not args.no_verify:
            if not base:
                print(f"{a['id']}: no baseline; run `blocks baseline {a['id']}` first (or build with --no-verify)", file=sys.stderr)
                failed += 1
                continue
            if base.get("code_sha") != a["code_sha"]:
                print(f"{a['id']}: the baseline was recorded for other code or data; re-record it with "
                      f"`blocks baseline {a['id']}` (or build with --no-verify)", file=sys.stderr)
                failed += 1
                continue
        dest = build.write(repo, project, version, inline=True, out=Path(args.out) if args.out else None)
        probs = build.check(dest.read_bytes())
        if probs:
            print("\n".join(probs), file=sys.stderr)
            failed += 1
            continue
        size = f"{dest.stat().st_size / 1048576:.1f} MB"
        if args.no_verify:
            print(f"{a['id']}: wrote {dest.relative_to(repo) if dest.is_relative_to(repo) else dest} ({size}), not verified")
            continue
        print(f"{a['id']}: wrote {dest.relative_to(repo) if dest.is_relative_to(repo) else dest} ({size}); verifying from file:// offline…")
        with harvest.browser() as b:
            res = harvest.drive(b, dest.resolve().as_uri(), provide=harvest.user_data(a, inline=True), offline=True, source="build",
                                screenshot=dest.with_suffix(".png") if args.screenshot else None)
        r = harvest.results(a, res, Runtime(repo))
        bad = {n: s["verdict"] for n, s in r["nodes"].items() if s["verdict"] != "match"}
        problems = []
        if r["verified"] != "match" or bad:
            problems.append(f"nodes do not reproduce the baseline: {bad or r['verified']}")
        if res["network_requests"]:
            problems.append(f"network requests: {res['network_requests']}")
        if res["csp_violations"]:
            problems.append(f"CSP violations: {res['csp_violations']}")
        if (res.get("integrity") or {}).get("bad"):
            problems.append(f"integrity: {res['integrity']['bad']}")
        problems += harvest.problems(res)
        if problems or r.get("error"):
            print("\n".join(problems + ([r["error"]] if r.get("error") else [])), file=sys.stderr)
            print(f"{a['id']}: NOT verified (the file is left at {dest} for inspection)", file=sys.stderr)
            failed += 1
            continue
        print(f"{a['id']}: verified. Every node reproduces the baseline from file:// with no network access "
              f"(start-up {r['startup_seconds']} s, run {r['run_seconds']} s)"
              + (f"; its {len(r['views'])} views are ready." if r["views"] else "."))
    return 1 if failed else 0


def cmd_check(repo: Path, args) -> int:
    if not Path(args.file).is_file():
        raise SystemExit(f"no file {args.file}")
    probs = build.check(Path(args.file).read_bytes())
    print("OK: every component matches its manifest hash" if not probs else "\n".join(probs))
    return 1 if probs else 0


def cmd_convert(repo: Path, args) -> int:
    from . import harvest
    if args.format:
        opts = {}
        for o in args.option or []:
            k, eq, v = o.partition("=")
            if not eq:
                raise SystemExit(f"--option {o!r}: want KEY=VALUE")
            opts[k] = v
        res = harvest.adapt(repo, Path(args.src), Path(args.dest), args.format, opts)
        print(f"{args.dest}: {res['rows']:,} {res['unit']}, {res['size'] / 2**20:.1f} MB in {res['seconds']:.1f} s")
        return 0
    out = harvest.to_parquet(repo, Path(args.src), Path(args.dest))
    print(f"{out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="blocks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve", help="dev server for linked builds")
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("new", help="start a project")
    p.add_argument("project")
    for name in ("run", "baseline"):
        sub.add_parser(name, help=f"{name} apps headlessly").add_argument("targets", nargs="*")
    p = sub.add_parser("build", help="the app as one offline file, verified against its baseline")
    p.add_argument("targets", nargs="*")
    p.add_argument("--out", help="where to write it (one target only; default dist/<project>.html)")
    p.add_argument("--no-verify", action="store_true", help="write the file without running it")
    p.add_argument("--screenshot", action="store_true")
    p = sub.add_parser("supersede", help="keep a copy of the current app as superseded/NAME")
    p.add_argument("project")
    p.add_argument("name")
    p = sub.add_parser("check", help="static integrity check")
    p.add_argument("file")
    p = sub.add_parser("convert", help="convert a dataset to Parquet (DuckDB, or a plugin's adapter, in Pyodide)")
    p.add_argument("src")
    p.add_argument("dest")
    p.add_argument("--format", help="a dataset format of a built-in plugin, e.g. gdb-zip (default: DuckDB reads SRC)")
    p.add_argument("--option", "-o", action="append", metavar="KEY=VALUE", help="adapter option, e.g. -o layer=Parcels")
    args = ap.parse_args(argv)
    if args.cmd == "build" and args.out and len(args.targets) != 1:
        raise SystemExit("--out needs exactly one target")
    repo = find_repo()
    fn = {"serve": cmd_serve, "new": cmd_new, "run": cmd_run, "baseline": lambda r, a: cmd_run(r, a, True),
          "build": cmd_build, "supersede": cmd_supersede, "check": cmd_check, "convert": cmd_convert}[args.cmd]
    sys.exit(fn(repo, args))
