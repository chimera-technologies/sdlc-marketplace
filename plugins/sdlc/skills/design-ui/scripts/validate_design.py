#!/usr/bin/env python3
"""Validate designs/<slug>/design.md (UI design, a Design sub-stage).

Deterministic gate used by the design-ui skill, the design-check workflow
and the build-story skill. Standard library only.

Usage (from the product repo root):
  validate_design.py designs/<slug>/design.md
  validate_design.py --owners .sdlc/owners.yaml designs/<slug>/design.md
  validate_design.py --no-images designs/<slug>/design.md   # before export

Checks the manifest structure, that every screen has a stored PNG under
designs/<slug>/screens/, that every story in the spec is either on a
screen or listed under "No UI", and that referenced stories and REQs exist.

`source: figma` (the default) screens name a Figma node; `source: mockup`
screens name an HTML mockup, designs/<slug>/mockups/<screen>.html, which must
be self-contained and static: no scripts, frames or remote resources, so
render_mockups.py can screenshot it safely with scripts and network off.

Exit code 0 = valid (warnings allowed), 1 = at least one error.
"""
import argparse
import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

_VS_PATH = Path(__file__).resolve().parents[2] / "write-spec" / "scripts" / "validate_spec.py"
_spec = importlib.util.spec_from_file_location("validate_spec", _VS_PATH)
vs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vs)
vi = vs.vi

REQUIRED_KEYS = ["id", "spec", "owner", "created"]
FIGMA_KEYS = ["figma_file", "figma_file_key"]   # required when source is figma
SOURCES = ["figma", "mockup"]
SECTIONS = ["Screens", "States", "Tokens", "No UI"]
FIGMA_URL_RE = re.compile(r"^https://(?:www\.)?figma\.com/(?:design|file)/([A-Za-z0-9]+)(?:/|\?|$)")
NODE_RE = re.compile(r"^\d+[:-]\d+$")
SCREEN_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ROW_RE = re.compile(r"^\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$", re.MULTILINE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
STORY_REF_RE = re.compile(r"\bS\d+\b")
REQ_REF_RE = re.compile(r"\bREQ-\d+\b")
# Mockups are rendered with scripts and network off; reject anything that
# would need either, so the PNG is exactly what the HTML says.
MOCKUP_FORBIDDEN = [
    (re.compile(r"<\s*(script|iframe|frame|object|embed|base|form)\b", re.I), "must not contain <{0}>"),
    (re.compile(r"\bon[a-z]+\s*=", re.I), "must not use inline event handlers ({0})"),
    (re.compile(r"javascript\s*:", re.I), "must not use {0} URLs"),
    (re.compile(r"(?:\b(?:src|href|srcset|action|poster)\s*=\s*[\"']?|url\(\s*[\"']?|@import\s+[\"']?)(?:https?:)?//", re.I),
     "must not load remote resources (inline them: CSS in <style>, images as data: URIs)"),
]
SIZE_META_RE = re.compile(r"<meta\s+name=[\"']sdlc-size[\"']\s+content=[\"'](\d{3,4})x(\d{3,5})[\"']", re.I)


def mockup_problems(html):
    """Reasons an HTML mockup is not safe to render (empty list = fine)."""
    problems = []
    for pattern, message in MOCKUP_FORBIDDEN:
        m = pattern.search(html)
        if m:
            problems.append(message.format(m.group(0).strip()[:30]))
    if not re.search(r"<html\b", html, re.I):
        problems.append("must be a complete HTML document (<html>...</html>)")
    return problems


def mockup_size(html, default=(1280, 800)):
    """(width, height) from <meta name="sdlc-size" content="1280x800">."""
    m = SIZE_META_RE.search(html)
    return (int(m.group(1)), int(m.group(2))) if m else default


def parse_screens(body):
    """Rows of the Screens table: [{'screen','node','screenshot','stories','requirements'}]."""
    _, sections = vi.split_sections(body)
    rows = []
    for m in ROW_RE.finditer(sections.get("Screens", "")):
        cells = [c.strip() for c in m.groups()]
        if cells[0].lower() == "screen" or set(cells[0]) <= set("-: "):
            continue
        rows.append({
            "screen": cells[0].strip("`"),
            "node": cells[1].strip("`"),
            "screenshot": cells[2].strip("`"),
            "stories": STORY_REF_RE.findall(cells[3]),
            "requirements": REQ_REF_RE.findall(cells[4]),
        })
    return rows


def normalize_node(node):
    """Figma URLs use 1-2, the API uses 1:2."""
    return node.replace("-", ":")


def spec_facts(spec_text):
    """Story ids and REQ ids defined in the spec."""
    _, body = vi.parse_frontmatter(spec_text)
    body = body or ""
    stories = [s["id"] for s in vs.parse_stories(body)]
    _, sections = vi.split_sections(body)
    reqs = re.findall(r"^\|\s*(REQ-\d+)\s*\|", sections.get("Requirements", ""), re.MULTILINE)
    return stories, set(reqs)


def validate(path, owners=None, root=".", check_images=True):
    errors, warnings = [], []
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    fm, body = vi.parse_frontmatter(text)
    if fm is None:
        return {}, ["missing YAML frontmatter block (--- ... ---) at top of file"], warnings
    for bad in fm.pop("__bad__", []):
        errors.append(f"unparseable frontmatter line: {bad!r}")
    source = fm.get("source") or "figma"
    if source not in SOURCES:
        errors.append(f"frontmatter: source must be one of {SOURCES}, got {source!r}")
    for key in REQUIRED_KEYS + (FIGMA_KEYS if source == "figma" else []):
        if not fm.get(key):
            errors.append(f"frontmatter: '{key}' is required")
    if source == "mockup":
        # Not in Figma yet: the keys may be absent or "none".
        for key in FIGMA_KEYS:
            if fm.get(key) == "none":
                fm.pop(key)

    if path.name != "design.md":
        errors.append("the manifest must be named design.md (designs/<slug>/design.md)")
    if fm.get("id") and fm["id"] != path.parent.name:
        errors.append(f"frontmatter: id {fm['id']!r} must match its folder designs/{path.parent.name}/")
    if fm.get("id") and not vi.SLUG_RE.match(fm["id"]):
        errors.append("frontmatter: id must be a lowercase kebab-case slug")
    if fm.get("spec") and fm.get("id") and fm["spec"] != f"specs/{fm['id']}.md":
        errors.append(f"frontmatter: spec must be 'specs/{fm['id']}.md', got {fm['spec']!r}")

    url_m = FIGMA_URL_RE.match(fm.get("figma_file", ""))
    if fm.get("figma_file") and not url_m:
        errors.append("frontmatter: figma_file must be a https://www.figma.com/design/<key>/... URL")
    elif url_m and fm.get("figma_file_key") and url_m.group(1) != fm["figma_file_key"]:
        errors.append(f"frontmatter: figma_file_key {fm['figma_file_key']!r} differs from the URL's {url_m.group(1)!r}")

    owner = fm.get("owner", "")
    if owner and not vi.OWNER_RE.match(owner):
        errors.append(f"frontmatter: owner {owner!r} must be @user or @org/team")
    elif owner and owners is not None and owner not in owners:
        errors.append(f"frontmatter: owner {owner!r} is not listed in owners file")
    if fm.get("created"):
        try:
            dt.date.fromisoformat(fm["created"])
        except ValueError:
            errors.append("frontmatter: created must be YYYY-MM-DD")

    if not re.search(r"^# Design: \S", body, re.MULTILINE):
        errors.append("missing H1 '# Design: <title>'")
    order, sections = vi.split_sections(body)
    if order != SECTIONS:
        missing = [s for s in SECTIONS if s not in order]
        extra = [s for s in order if s not in SECTIONS]
        detail = ([f"missing {missing}"] if missing else []) + ([f"unexpected {extra}"] if extra else [])
        errors.append(f"section headings must be exactly {SECTIONS} ({'; '.join(detail) or 'wrong order'})")
    for ph in vi.placeholders(text):
        errors.append(f"unfilled template placeholder: {ph[:60]}")
    for name in ("Screens", "Tokens"):
        content = sections.get(name, "")
        if not content:
            errors.append(f"section '{name}' is empty")
        elif vi.FILLER_RE.search(content):
            errors.append(f"section '{name}' contains filler (TBD/TODO); it needs real content")

    rows = parse_screens(body)
    if "Screens" in sections and not rows:
        errors.append("section 'Screens' needs at least one row")
    seen = set()
    for r in rows:
        sid = r["screen"]
        if not SCREEN_ID_RE.match(sid):
            errors.append(f"screen {sid!r}: id must be kebab-case (e.g. plan-list-empty)")
        if sid in seen:
            errors.append(f"screen {sid!r} is listed twice")
        seen.add(sid)
        if source == "figma" and not NODE_RE.match(r["node"]):
            errors.append(f"screen {sid!r}: Figma node must look like 1:2, got {r['node']!r}")
        elif source == "mockup":
            if r["node"] != f"mockups/{sid}.html":
                errors.append(f"screen {sid!r}: source must be mockups/{sid}.html, got {r['node']!r}")
            else:
                html = path.parent / r["node"]
                if not html.is_file():
                    errors.append(f"screen {sid!r}: {html.as_posix()} not found")
                else:
                    for p in mockup_problems(html.read_text(encoding="utf-8", errors="replace")):
                        errors.append(f"screen {sid!r}: {html.as_posix()} {p}")
        if r["screenshot"] != f"screens/{sid}.png":
            errors.append(f"screen {sid!r}: screenshot must be screens/{sid}.png, got {r['screenshot']!r}")
        elif check_images:
            png = path.parent / r["screenshot"]
            if not png.is_file():
                tool = "render_mockups.py" if source == "mockup" else "export_screens.py"
                errors.append(f"screen {sid!r}: {png.as_posix()} not found (run {tool})")
            elif png.read_bytes()[:8] != PNG_MAGIC:
                errors.append(f"screen {sid!r}: {png.as_posix()} is not a PNG")
        if not r["stories"]:
            errors.append(f"screen {sid!r}: name at least one story (S<n>)")

    spec_path = Path(root) / fm.get("spec", "")
    if fm.get("spec") and not spec_path.is_file():
        errors.append(f"spec {fm['spec']} not found")
    elif fm.get("spec"):
        stories, reqs = spec_facts(spec_path.read_text(encoding="utf-8"))
        no_ui = set(STORY_REF_RE.findall(sections.get("No UI", "")))
        on_screen = {s for r in rows for s in r["stories"]}
        for r in rows:
            for s in r["stories"]:
                if s not in stories:
                    errors.append(f"screen {r['screen']!r}: story {s} is not in the spec")
            for q in r["requirements"]:
                if q not in reqs:
                    errors.append(f"screen {r['screen']!r}: {q} is not in the spec's Requirements")
        for s in stories:
            if s not in on_screen and s not in no_ui:
                errors.append(f"spec story {s} is on no screen; add a screen or list it under 'No UI' with a reason")
        for s in no_ui & on_screen:
            warnings.append(f"story {s} is on a screen and also under 'No UI'")

    # Stray images that no screen references are usually stale exports.
    shots = path.parent / "screens"
    if shots.is_dir():
        listed = {r["screenshot"] for r in rows}
        for p in sorted(shots.glob("*.png")):
            if f"screens/{p.name}" not in listed:
                warnings.append(f"{p.as_posix()} is not referenced by any screen")
    return fm, errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--owners", help="owners file; owner must appear in it")
    ap.add_argument("--root", default=".", help="product repo root (default: current dir)")
    ap.add_argument("--no-images", action="store_true", help="skip the PNG checks (before export)")
    args = ap.parse_args()
    owners = vi.load_owners(args.owners) if args.owners else None
    failed = False
    for f in args.files:
        _, errors, warnings = validate(f, owners, args.root, not args.no_images)
        for w in warnings:
            print(f"::warning file={f}::{w}", file=sys.stderr)
        for e in errors:
            print(f"::error file={f}::{e}", file=sys.stderr)
        if errors:
            failed = True
        else:
            print(f"OK {f}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
