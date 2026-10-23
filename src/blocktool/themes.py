"""Themes: one token set per theme drives the whole UI, the pele DAG and the charts.

Each theme has a light and a dark palette, chosen by data-mode="light" | "dark" on the
root. The app always sets it (the viewer's choice, else the system's); a page without
script (the dev server's project index) follows the system preference.

Token roles
  bg            app chrome (toolbar, page)        surface / surface-2   header, inputs, wells
  report        the report beside the graph       dag-bg                behind the graph
  dag-node / dag-group / dag-border / dag-line / dag-text   the graph itself (fed to pele)
  text / muted / faint, line / line-2, accent (+ -soft, on-accent)
  ok / warn / err / run / diff (+ -soft)   status;  s1..s4 chart series
  font-ui / font-report   system font stacks only (the final build allows no font loading)
"""
from __future__ import annotations

SANS = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
SERIF = 'Charter, "Bitstream Charter", "Iowan Old Style", "Sitka Text", Cambria, Georgia, serif'
HUMANIST = '"Avenir Next", Avenir, "Segoe UI", "Trebuchet MS", system-ui, sans-serif'

THEMES: dict[str, dict] = {
    "paper": {
        "label": "Paper",
        "description": "Warm paper tones after pele's Flexoki palette; the default.",
        "fonts": {"font-ui": SANS, "font-report": SANS},
        "light": {
            "bg": "#f2f0e5", "surface": "#fffcf0", "surface-2": "#e6e4d9", "report": "#fffef9",
            "line": "#dad8ce", "line-2": "#cecdc3", "text": "#100f0f", "muted": "#6f6e69", "faint": "#9f9d96",
            "accent": "#205ea6", "accent-soft": "#e1ecf5", "on-accent": "#fffcf0",
            "ok": "#66800b", "ok-soft": "#edeecf", "warn": "#ad8301", "warn-soft": "#faeec6",
            "err": "#af3029", "err-soft": "#ffe1d5", "run": "#205ea6", "run-soft": "#e1ecf5",
            "diff": "#bc5215", "diff-soft": "#ffe7ce", "idle": "#878580",
            "s1": "#205ea6", "s2": "#bc5215", "s3": "#66800b", "s4": "#5e409d",
            "dag-bg": "#fffcf0", "dag-node": "#f2f0e5", "dag-group": "#e6e4d9", "dag-border": "#cecdc3",
            "dag-line": "#403e3c", "dag-text": "#100f0f",
        },
        "dark": {
            "bg": "#100f0f", "surface": "#1c1b1a", "surface-2": "#282726", "report": "#1a1918",
            "line": "#343331", "line-2": "#403e3c", "text": "#cecdc3", "muted": "#878580", "faint": "#575653",
            "accent": "#4385be", "accent-soft": "#12253b", "on-accent": "#100f0f",
            "ok": "#879a39", "ok-soft": "#1a1e0c", "warn": "#d0a215", "warn-soft": "#241e08",
            "err": "#d14d41", "err-soft": "#261312", "run": "#4385be", "run-soft": "#12253b",
            "diff": "#da702c", "diff-soft": "#27180e", "idle": "#878580",
            "s1": "#4385be", "s2": "#da702c", "s3": "#879a39", "s4": "#8b7ec8",
            "dag-bg": "#100f0f", "dag-node": "#1c1b1a", "dag-group": "#282726", "dag-border": "#403e3c",
            "dag-line": "#b7b5ac", "dag-text": "#cecdc3",
        },
    },
    "slate": {
        "label": "Slate",
        "description": "Cool blue-grey engineering look; the report is a lighter tint of the graph's blue-grey.",
        "fonts": {"font-ui": SANS, "font-report": SANS},
        "light": {
            "bg": "#e7ecf1", "surface": "#f8fafc", "surface-2": "#e2e8ef", "report": "#f4f7fa",
            "line": "#d3dbe4", "line-2": "#b8c4d1", "text": "#17212b", "muted": "#5b6876", "faint": "#8a96a3",
            "accent": "#2f6db5", "accent-soft": "#dde9f6", "on-accent": "#ffffff",
            "ok": "#2f7d5b", "ok-soft": "#dcefe6", "warn": "#a86b00", "warn-soft": "#f7ebd2",
            "err": "#b4322f", "err-soft": "#f8dedc", "run": "#2f6db5", "run-soft": "#dde9f6",
            "diff": "#c25a1c", "diff-soft": "#fae4d4", "idle": "#8a96a3",
            "s1": "#2f6db5", "s2": "#d0712e", "s3": "#2f7d5b", "s4": "#7b57b5",
            "dag-bg": "#e9eef3", "dag-node": "#ffffff", "dag-group": "#d9e1ea", "dag-border": "#b8c4d1",
            "dag-line": "#2b3a4a", "dag-text": "#17212b",
        },
        "dark": {
            "bg": "#0e131a", "surface": "#151c25", "surface-2": "#1d2631", "report": "#141b24",
            "line": "#263140", "line-2": "#33404f", "text": "#dbe3ec", "muted": "#8b99a8", "faint": "#5d6a78",
            "accent": "#6aa5e8", "accent-soft": "#16263a", "on-accent": "#0e131a",
            "ok": "#5fbf8f", "ok-soft": "#11241b", "warn": "#e0a23a", "warn-soft": "#2a2010",
            "err": "#ec6d68", "err-soft": "#2c1514", "run": "#6aa5e8", "run-soft": "#16263a",
            "diff": "#f08a4b", "diff-soft": "#2c1a10", "idle": "#6b7886",
            "s1": "#6aa5e8", "s2": "#f08a4b", "s3": "#5fbf8f", "s4": "#a98be0",
            "dag-bg": "#0f151c", "dag-node": "#1a222d", "dag-group": "#1f2935", "dag-border": "#33404f",
            "dag-line": "#9fb0c2", "dag-text": "#dbe3ec",
        },
    },
    "sage": {
        "label": "Sage",
        "description": "Field-notebook greens with a teal accent; the report is a lighter tint of the graph's sage.",
        "fonts": {"font-ui": HUMANIST, "font-report": HUMANIST},
        "light": {
            "bg": "#e4e9df", "surface": "#f7f9f3", "surface-2": "#dfe6d8", "report": "#f4f7ef",
            "line": "#d2dacb", "line-2": "#b9c4af", "text": "#1d241b", "muted": "#5d6858", "faint": "#8e9887",
            "accent": "#2d6a6e", "accent-soft": "#d9ebea", "on-accent": "#f7f9f3",
            "ok": "#4a7a24", "ok-soft": "#e2edd5", "warn": "#9c6f06", "warn-soft": "#f4e9cc",
            "err": "#a63d2f", "err-soft": "#f5ddd7", "run": "#2d6a6e", "run-soft": "#d9ebea",
            "diff": "#b65a22", "diff-soft": "#f6e1d1", "idle": "#8e9887",
            "s1": "#2d6a6e", "s2": "#b65a22", "s3": "#4a7a24", "s4": "#7a5a8c",
            "dag-bg": "#e8eee3", "dag-node": "#fbfcf8", "dag-group": "#d6dfcd", "dag-border": "#b9c4af",
            "dag-line": "#313b2e", "dag-text": "#1d241b",
        },
        "dark": {
            "bg": "#11150f", "surface": "#181d15", "surface-2": "#20271c", "report": "#171c14",
            "line": "#2a3325", "line-2": "#36412f", "text": "#d9e0d1", "muted": "#8f9a86", "faint": "#5f6958",
            "accent": "#6fb7b5", "accent-soft": "#15282a", "on-accent": "#11150f",
            "ok": "#8cbf5a", "ok-soft": "#1b2612", "warn": "#d6a73c", "warn-soft": "#28210e",
            "err": "#e07a68", "err-soft": "#2b1713", "run": "#6fb7b5", "run-soft": "#15282a",
            "diff": "#e39158", "diff-soft": "#2b1c11", "idle": "#6f7a68",
            "s1": "#6fb7b5", "s2": "#e39158", "s3": "#8cbf5a", "s4": "#b49ac4",
            "dag-bg": "#12170f", "dag-node": "#1c2318", "dag-group": "#222b1d", "dag-border": "#36412f",
            "dag-line": "#a9b59e", "dag-text": "#d9e0d1",
        },
    },
    "ink": {
        "label": "Ink",
        "description": "Monochrome and print-friendly with a serif report; colour is kept for status only.",
        "fonts": {"font-ui": SANS, "font-report": SERIF},
        "light": {
            "bg": "#ededed", "surface": "#ffffff", "surface-2": "#f0f0f0", "report": "#ffffff",
            "line": "#dcdcdc", "line-2": "#b0b0b0", "text": "#111111", "muted": "#555555", "faint": "#8a8a8a",
            "accent": "#111111", "accent-soft": "#ebebeb", "on-accent": "#ffffff",
            "ok": "#2d6a2d", "ok-soft": "#e3eee3", "warn": "#8a6100", "warn-soft": "#f3ebd8",
            "err": "#a11d1d", "err-soft": "#f5dcdc", "run": "#111111", "run-soft": "#ebebeb",
            "diff": "#a8480f", "diff-soft": "#f5e3d6", "idle": "#8a8a8a",
            "s1": "#111111", "s2": "#a8480f", "s3": "#2d6a2d", "s4": "#6b6b6b",
            "dag-bg": "#f6f6f6", "dag-node": "#ffffff", "dag-group": "#ececec", "dag-border": "#111111",
            "dag-line": "#111111", "dag-text": "#111111",
        },
        "dark": {
            "bg": "#0a0a0a", "surface": "#141414", "surface-2": "#1e1e1e", "report": "#121212",
            "line": "#2a2a2a", "line-2": "#444444", "text": "#ededed", "muted": "#a3a3a3", "faint": "#6b6b6b",
            "accent": "#ededed", "accent-soft": "#262626", "on-accent": "#0a0a0a",
            "ok": "#7fbf7f", "ok-soft": "#142014", "warn": "#d9b25c", "warn-soft": "#231d0e",
            "err": "#f07a7a", "err-soft": "#2a1212", "run": "#ededed", "run-soft": "#262626",
            "diff": "#ef9a5d", "diff-soft": "#2a1a0e", "idle": "#6b6b6b",
            "s1": "#ededed", "s2": "#ef9a5d", "s3": "#7fbf7f", "s4": "#9a9a9a",
            "dag-bg": "#0d0d0d", "dag-node": "#161616", "dag-group": "#1c1c1c", "dag-border": "#ededed",
            "dag-line": "#ededed", "dag-text": "#ededed",
        },
    },
    "observatory": {
        "label": "Observatory",
        "description": "Dark-first navy with an amber accent; the report is a lighter navy than the graph.",
        "fonts": {"font-ui": SANS, "font-report": SANS},
        "light": {
            "bg": "#e6ebf3", "surface": "#ffffff", "surface-2": "#dde4ef", "report": "#f5f7fb",
            "line": "#d0d8e6", "line-2": "#b7c3d6", "text": "#0f1a2b", "muted": "#53627a", "faint": "#8592a8",
            "accent": "#a8650a", "accent-soft": "#f6e8d2", "on-accent": "#ffffff",
            "ok": "#23845a", "ok-soft": "#d8efe4", "warn": "#9a7a00", "warn-soft": "#f3ecc9",
            "err": "#c0392b", "err-soft": "#f8dcd8", "run": "#2a64c5", "run-soft": "#dce7f8",
            "diff": "#c4561a", "diff-soft": "#f9e1d2", "idle": "#8592a8",
            "s1": "#2a64c5", "s2": "#a8650a", "s3": "#23845a", "s4": "#7d4fc4",
            "dag-bg": "#e9eef7", "dag-node": "#ffffff", "dag-group": "#dde5f1", "dag-border": "#b7c3d6",
            "dag-line": "#1d2b44", "dag-text": "#0f1a2b",
        },
        "dark": {
            "bg": "#0a1220", "surface": "#101b2d", "surface-2": "#172539", "report": "#13203a",
            "line": "#1f2e45", "line-2": "#2b3d58", "text": "#e6edf7", "muted": "#93a4bd", "faint": "#5f7190",
            "accent": "#f2b45a", "accent-soft": "#33280f", "on-accent": "#0a1220",
            "ok": "#6fcf97", "ok-soft": "#0f2a1f", "warn": "#f2c94c", "warn-soft": "#2d2710",
            "err": "#ff7b72", "err-soft": "#341615", "run": "#7cb3ff", "run-soft": "#132a4a",
            "diff": "#ff9e5e", "diff-soft": "#341f10", "idle": "#5f7190",
            "s1": "#7cb3ff", "s2": "#f2b45a", "s3": "#6fcf97", "s4": "#c39bff",
            "dag-bg": "#0c1628", "dag-node": "#142238", "dag-group": "#182943", "dag-border": "#2b3d58",
            "dag-line": "#8fa6c6", "dag-text": "#e6edf7",
        },
    },
}

DEFAULT = "paper"


def _block(sel: str, tokens: dict, scheme: str, fonts: dict) -> str:
    body = "".join(f"--{k}:{v};" for k, v in tokens.items())
    body += "".join(f"--{k}:{v};" for k, v in fonts.items())
    return f"{sel}{{{body}color-scheme:{scheme};}}\n"


def merged(name: str, overrides: dict | None = None) -> dict:
    t = THEMES[name]
    o = overrides or {}
    return {**t, "light": {**t["light"], **(o.get("light") or {})}, "dark": {**t["dark"], **(o.get("dark") or {})},
            "fonts": {**t["fonts"], **(o.get("fonts") or {})}}


def css(default: str = DEFAULT, overrides: dict | None = None, names: list[str] | None = None) -> str:
    """CSS for the given themes. `overrides` ({light:{}, dark:{}, fonts:{}}) adjusts the default theme."""
    out = ["/* generated by proto.themes; edit src/proto/themes.py, not this file */\n"]
    for name in names or list(THEMES):
        t = merged(name, overrides if name == default else None)
        sel = lambda extra: f':root[data-theme="{name}"]{extra}' + (f", :root:not([data-theme]){extra}" if name == default else "")
        out.append(_block(sel(""), t["light"], "light", t["fonts"]))
        out.append("@media (prefers-color-scheme: dark){" + _block(sel(":not([data-mode])"), t["dark"], "dark", t["fonts"]) + "}\n")
        out.append(_block(sel('[data-mode="dark"]'), t["dark"], "dark", t["fonts"]))
    return "".join(out)


def catalog() -> list[dict]:
    return [{"name": n, "label": t["label"], "description": t["description"]} for n, t in THEMES.items()]
