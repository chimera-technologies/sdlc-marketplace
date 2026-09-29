#!/usr/bin/env python3
"""Validate intent/*.md files against the write-intent template.

Deterministic gate used by the write-intent skill (self-check), the
create-intent workflow (before opening a PR) and the intent-check workflow
(on every intent PR). Standard library only so it runs on any CI runner.

Usage:
  validate_intent.py intent/foo.md [intent/bar.md ...]
  validate_intent.py --json intent/foo.md        # print parsed frontmatter
  validate_intent.py --owners .sdlc/owners.yaml intent/foo.md

Exit code 0 = valid (warnings allowed), 1 = at least one error.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REQUIRED_KEYS = [
    "id", "title", "author", "source", "record_id", "owner",
    "owner_role", "risk", "systems", "created",
]
ENUMS = {
    "source": {"human", "jira", "maintain", "claude-security", "claude-tag"},
    "owner_role": {"product-owner", "service-owner"},
    "risk": {"low", "medium", "high"},
}
SECTIONS = [
    "Problem",
    "Proposed outcome",
    "Affected users and systems",
    "Constraints",
    "Out of scope",
    "Evidence",
    "Open questions",
    "Success looks like",
]
MUST_BE_REAL = ["Problem", "Proposed outcome", "Affected users and systems"]
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
JIRA_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
OWNER_RE = re.compile(r"^@[A-Za-z0-9-]+(/[A-Za-z0-9._-]+)?$")
OWNERS_LINE_RE = re.compile(
    r"""^\s*[A-Za-z_]+\s*:\s*["']?(@[A-Za-z0-9-]+(?:/[A-Za-z0-9._-]+)?)["']?\s*(?:#.*)?$"""
)
FINGERPRINT_RE = re.compile(r"^[a-z0-9-]{1,60}$")
COMPONENT_RE = re.compile(r"^  ([a-z0-9][a-z0-9-]*)\s*:\s*(#.*)?$")
UNKNOWN_SYSTEM = "unknown"  # documented value when no owners.yaml component matches
PLACEHOLDER_RE = re.compile(r"<[^<>\n]{2,}>")
CODE_RE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)  # fenced blocks and inline code


def placeholders(text):
    """Template placeholders like <short title>, ignoring anything inside code
    (so `<label>` or an HTML snippet in a fenced block is not flagged)."""
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(CODE_RE.sub("", text))]
FILLER_RE = re.compile(r"\b(TBD|TODO|FIXME|lorem ipsum)\b", re.IGNORECASE)
MAX_WORDS = 700  # "under one page"


def parse_frontmatter(text):
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None, text
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return None, text
    data = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            data.setdefault("__bad__", []).append(raw)
            continue
        key, _, val = raw.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            data[key.strip()] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()] if inner else []
        else:
            data[key.strip()] = val.strip("'\"")
    return data, "\n".join(lines[end + 1:])


def split_sections(body):
    sections, order, current = {}, [], None
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            order.append(current)
            sections[current] = []
        elif current:
            sections[current].append(line)
    return order, {k: "\n".join(v).strip() for k, v in sections.items()}


def load_owners(path):
    """Every @user or @org/team value in the owners file, e.g. product_owner: "@org/team"."""
    owners = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = OWNERS_LINE_RE.match(line)
        if m:
            owners.add(m.group(1))
    return owners


def load_components(path):
    """Component names (keys under `components:`) in the owners file."""
    names, inside = set(), False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if re.match(r"^components\s*:", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            break
        m = COMPONENT_RE.match(line) if inside else None
        if m:
            names.add(m.group(1))
    return names


def validate(path, owners=None, components=None):
    errors, warnings = [], []
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if fm is None:
        return {}, ["missing YAML frontmatter block (--- ... ---) at top of file"], warnings

    for bad in fm.pop("__bad__", []):
        errors.append(f"unparseable frontmatter line: {bad!r}")
    for key in REQUIRED_KEYS:
        if key not in fm or fm[key] in ("", []):
            errors.append(f"frontmatter: '{key}' is required")
    for key, allowed in ENUMS.items():
        if key in fm and fm[key] not in allowed:
            errors.append(f"frontmatter: '{key}' must be one of {sorted(allowed)}, got {fm[key]!r}")

    stem = Path(path).stem
    if fm.get("id") and fm["id"] != stem:
        errors.append(f"frontmatter: id {fm['id']!r} must match file name {stem!r}")
    if fm.get("id") and not SLUG_RE.match(fm["id"]):
        errors.append("frontmatter: id must be a lowercase kebab-case slug")

    rid = fm.get("record_id", "")
    if rid and rid != "none" and not JIRA_RE.match(rid):
        errors.append(f"frontmatter: record_id {rid!r} must be a Jira key (ABC-123) or 'none'")
    if fm.get("source") == "jira" and rid in ("", "none"):
        errors.append("frontmatter: source 'jira' requires a record_id")

    fp = fm.get("fingerprint", "none")
    if fp != "none" and not FINGERPRINT_RE.match(fp):
        errors.append(f"frontmatter: fingerprint {fp!r} must match ^[a-z0-9-]{{1,60}}$ or be 'none'")

    owner = fm.get("owner", "")
    if owner and not OWNER_RE.match(owner):
        errors.append(f"frontmatter: owner {owner!r} must be @user or @org/team")
    elif owner and owners is not None and owner not in owners:
        errors.append(f"frontmatter: owner {owner!r} is not listed in owners file")

    if fm.get("created"):
        try:
            dt.date.fromisoformat(fm["created"])
        except ValueError:
            errors.append("frontmatter: created must be YYYY-MM-DD")
    if "systems" in fm and not isinstance(fm["systems"], list):
        errors.append("frontmatter: systems must be a list, e.g. [claims-core, portal]")
    elif components is not None and isinstance(fm.get("systems"), list):
        for name in fm["systems"]:
            if name != UNKNOWN_SYSTEM and name not in components:
                warnings.append(
                    f"system {name!r} is not a component in the owners file; use a listed "
                    f"component or '{UNKNOWN_SYSTEM}' (and ask who owns it under Open questions)"
                )

    if not re.search(r"^# Intent: \S", body, re.MULTILINE):
        errors.append("missing H1 '# Intent: <title>'")
    order, sections = split_sections(body)
    if order != SECTIONS:
        missing = [s for s in SECTIONS if s not in order]
        extra = [s for s in order if s not in SECTIONS]
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if extra:
            detail.append(f"unexpected {extra}")
        if not missing and not extra:
            detail.append("wrong order")
        errors.append(f"section headings must be exactly {SECTIONS} ({'; '.join(detail)})")

    for ph in placeholders(text):
        errors.append(f"unfilled template placeholder: {ph[:60]}")
    for name in MUST_BE_REAL:
        content = sections.get(name, "")
        if not content:
            errors.append(f"section '{name}' is empty")
        elif FILLER_RE.search(content):
            errors.append(f"section '{name}' contains filler (TBD/TODO); it needs real content")
    if fm.get("source") not in (None, "human"):
        ev = sections.get("Evidence", "").strip().rstrip(".").lower()
        if ev in ("", "none"):
            errors.append("section 'Evidence' is required when source is not 'human'")

    words = len(re.findall(r"\w+", body))
    if words > MAX_WORDS:
        warnings.append(f"{words} words (> {MAX_WORDS}); consider splitting into two intents")

    return fm, errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true", help="print parsed frontmatter as JSON")
    ap.add_argument("--owners", help="owners file; owner must appear in it")
    args = ap.parse_args()

    owners = load_owners(args.owners) if args.owners else None
    components = load_components(args.owners) if args.owners else None
    failed, out = False, {}
    for f in args.files:
        fm, errors, warnings = validate(f, owners, components)
        out[f] = fm
        for w in warnings:
            print(f"::warning file={f}::{w}", file=sys.stderr)
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
