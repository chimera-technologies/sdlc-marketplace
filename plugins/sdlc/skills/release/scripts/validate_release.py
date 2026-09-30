#!/usr/bin/env python3
"""Validate releases/<version>.md (Deploy stage release record).

Deterministic gate used by the release skill and the release workflow.
Standard library only.

Usage (from the project root):
  validate_release.py releases/v1.2.0.md
  validate_release.py --owners .sdlc/owners.yaml releases/v1.2.0.md
  validate_release.py --json releases/v1.2.0.md      # print the frontmatter

Checks: frontmatter (version matches the file name and is newer than
previous, commit sha, type, owner), the section headings, and that a
release or hotfix lists at least one change.

Exit code 0 = valid, 1 = at least one error.
"""
import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

_VI_PATH = Path(__file__).resolve().parents[2] / "write-intent" / "scripts" / "validate_intent.py"
_spec = importlib.util.spec_from_file_location("validate_intent", _VI_PATH)
vi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vi)

REQUIRED_KEYS = ["version", "previous", "commit", "type", "owner", "created"]
TYPES = {"release", "hotfix", "rollback"}
SECTIONS = ["Summary", "Changes", "Risk and rollback", "Verification", "Approvals"]
MUST_BE_REAL = ["Summary", "Risk and rollback", "Verification"]
VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CHANGE_ROW_RE = re.compile(r"^\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$", re.MULTILINE)


def parse_version(v):
    m = VERSION_RE.match(v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def changes(body):
    """Rows of the Changes table: [{'jira','story','pr'}]."""
    _, sections = vi.split_sections(body)
    rows = []
    for m in CHANGE_ROW_RE.finditer(sections.get("Changes", "")):
        jira, story, pr = (c.strip() for c in m.groups())
        if jira.lower() == "jira" or set(jira) <= set("-: ") and set(story) <= set("-: "):
            continue
        rows.append({"jira": jira, "story": story, "pr": pr})
    return rows


def validate(path, owners=None):
    errors = []
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    fm, body = vi.parse_frontmatter(text)
    if fm is None:
        return {}, ["missing YAML frontmatter block (--- ... ---) at top of file"]
    for bad in fm.pop("__bad__", []):
        errors.append(f"unparseable frontmatter line: {bad!r}")
    for key in REQUIRED_KEYS:
        if not fm.get(key):
            errors.append(f"frontmatter: '{key}' is required")

    version = parse_version(fm.get("version"))
    if fm.get("version") and not version:
        errors.append(f"frontmatter: version must be vMAJOR.MINOR.PATCH, got {fm['version']!r}")
    if fm.get("version") and path.stem != fm["version"]:
        errors.append(f"frontmatter: version {fm['version']!r} must match the file name {path.name!r}")
    prev = fm.get("previous", "")
    if prev and prev != "none":
        pv = parse_version(prev)
        if not pv:
            errors.append(f"frontmatter: previous must be a vMAJOR.MINOR.PATCH tag or none, got {prev!r}")
        elif version and fm.get("type") != "rollback" and not version > pv:
            errors.append(f"frontmatter: version {fm['version']} must be newer than previous {prev}")
    if fm.get("commit") and not SHA_RE.match(fm["commit"]):
        errors.append("frontmatter: commit must be the full 40-character sha on the base branch")
    if fm.get("type") and fm["type"] not in TYPES:
        errors.append(f"frontmatter: type must be one of {sorted(TYPES)}, got {fm['type']!r}")
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

    if not re.search(r"^# Release: v\d+\.\d+\.\d+\s*$", body, re.MULTILINE):
        errors.append("missing H1 '# Release: vMAJOR.MINOR.PATCH'")
    order, sections = vi.split_sections(body)
    if order != SECTIONS:
        missing = [s for s in SECTIONS if s not in order]
        extra = [s for s in order if s not in SECTIONS]
        detail = ([f"missing {missing}"] if missing else []) + ([f"unexpected {extra}"] if extra else [])
        errors.append(f"section headings must be exactly {SECTIONS} ({'; '.join(detail) or 'wrong order'})")
    for ph in vi.placeholders(text):
        errors.append(f"unfilled template placeholder: {ph[:60]}")
    for name in MUST_BE_REAL:
        content = sections.get(name, "")
        if not content:
            errors.append(f"section '{name}' is empty")
        elif vi.FILLER_RE.search(content):
            errors.append(f"section '{name}' contains filler (TBD/TODO); it needs real content")
    rows = changes(body)
    if fm.get("type") in ("release", "hotfix") and not rows:
        errors.append("section 'Changes' needs at least one '| <Jira> | <story> | <PR> |' row for a release or hotfix")
    for r in rows:
        if r["jira"] not in ("-", "none") and not vi.JIRA_RE.match(r["jira"]):
            errors.append(f"Changes: {r['jira']!r} must be a Jira key (ABC-123) or '-'")
    return fm, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--owners", help="owners file; owner must appear in it")
    ap.add_argument("--json", action="store_true", help="print the frontmatter (and Jira keys) as JSON")
    args = ap.parse_args()
    owners = vi.load_owners(args.owners) if args.owners else None
    failed, out = False, {}
    for f in args.files:
        fm, errors = validate(f, owners)
        _, body = vi.parse_frontmatter(Path(f).read_text(encoding="utf-8"))
        out[f] = {**fm, "jira_keys": [r["jira"] for r in changes(body or "") if vi.JIRA_RE.match(r["jira"])]}
        for e in errors:
            print(f"::error file={f}::{e}", file=sys.stderr)
        if errors:
            failed = True
        elif not args.json:
            print(f"OK {f}")
    if args.json:
        print(json.dumps(out if len(args.files) > 1 else next(iter(out.values())), indent=2))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
