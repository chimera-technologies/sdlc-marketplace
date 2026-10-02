#!/usr/bin/env python3
"""Validate specs/*.md files against the write-spec template.

Deterministic gate used by the write-spec skill (self-check), the
intent-to-spec workflow (before opening the PR) and the spec-check workflow
(on every spec PR). Standard library only.

Usage:
  validate_spec.py specs/foo.md [specs/bar.md ...]
  validate_spec.py --json specs/foo.md          # print parsed frontmatter
  validate_spec.py --owners .sdlc/owners.yaml specs/foo.md

The intent named in the frontmatter is read relative to the current
directory (the repo root) to check that every intent open question is
carried into the spec.

Exit code 0 = valid (warnings allowed), 1 = at least one error.
"""
import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

# Reuse the intent validator's parsing so the two can never drift apart.
_VI_PATH = Path(__file__).resolve().parents[2] / "write-intent" / "scripts" / "validate_intent.py"
_spec = importlib.util.spec_from_file_location("validate_intent", _VI_PATH)
vi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vi)

REQUIRED_KEYS = ["id", "title", "intent", "record_id", "owner", "risk", "systems", "created"]
SECTIONS = [
    "Summary",
    "Context",
    "Requirements",
    "Technology and architecture",
    "Design",
    "Security considerations",
    "Open questions",
    "Areas of concern",
    "Work breakdown",
    "Out of scope",
]
MUST_BE_REAL = ["Summary", "Requirements", "Technology and architecture", "Design", "Work breakdown"]
OQ_STATUSES = {"answered", "carried forward", "open"}
REQ_ROW_RE = re.compile(r"^\|\s*REQ-\d+\s*\|", re.MULTILINE)
SEC_ROW_RE = re.compile(r"^\|\s*(SEC|INF)-\d", re.MULTILINE)  # security-policy or infra-policy rule
OQ_ROW_RE = re.compile(r"^\|\s*OQ-\d+\s*\|(.*)$", re.MULTILINE)
STORY_RE = re.compile(r"^###\s+(S\d+):\s*(\S.*?)\s*$", re.MULTILINE)
MAX_WORDS = 2000
MAX_STORIES = 12


def parse_stories(body):
    """Stories under '## Work breakdown': [{'id', 'title', 'body'}] in order."""
    _, sections = vi.split_sections(body)
    text = sections.get("Work breakdown", "")
    matches = list(STORY_RE.finditer(text))
    stories = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        stories.append({"id": m.group(1), "title": m.group(2), "body": text[m.end():end].strip()})
    return stories


def intent_open_questions(intent_text):
    """Top-level bullets in the intent's Open questions section."""
    _, body = vi.parse_frontmatter(intent_text)
    _, sections = vi.split_sections(body)
    return [l for l in sections.get("Open questions", "").splitlines() if l.startswith("- ")]


def validate(path, owners=None, root="."):
    errors, warnings = [], []
    text = Path(path).read_text(encoding="utf-8")
    fm, body = vi.parse_frontmatter(text)
    if fm is None:
        return {}, ["missing YAML frontmatter block (--- ... ---) at top of file"], warnings

    for bad in fm.pop("__bad__", []):
        errors.append(f"unparseable frontmatter line: {bad!r}")
    for key in REQUIRED_KEYS:
        if key not in fm or fm[key] in ("", []):
            errors.append(f"frontmatter: '{key}' is required")
    if fm.get("risk") and fm["risk"] not in vi.ENUMS["risk"]:
        errors.append(f"frontmatter: 'risk' must be one of {sorted(vi.ENUMS['risk'])}, got {fm['risk']!r}")

    stem = Path(path).stem
    if fm.get("id") and fm["id"] != stem:
        errors.append(f"frontmatter: id {fm['id']!r} must match file name {stem!r}")
    if fm.get("id") and not vi.SLUG_RE.match(fm["id"]):
        errors.append("frontmatter: id must be a lowercase kebab-case slug")
    if fm.get("intent") and fm.get("id") and fm["intent"] != f"intent/{fm['id']}.md":
        errors.append(f"frontmatter: intent must be 'intent/{fm['id']}.md' (same slug as the spec), got {fm['intent']!r}")

    rid = fm.get("record_id", "")
    if rid and rid != "none" and not vi.JIRA_RE.match(rid):
        errors.append(f"frontmatter: record_id {rid!r} must be a Jira key (ABC-123) or 'none'")

    for key in ("owner", "tech_lead"):
        who = fm.get(key, "")
        if who and not vi.OWNER_RE.match(who):
            errors.append(f"frontmatter: {key} {who!r} must be @user or @org/team")
        elif who and owners is not None and who not in owners:
            errors.append(f"frontmatter: {key} {who!r} is not listed in owners file")
    if fm.get("risk") == "high" and not fm.get("tech_lead"):
        errors.append("frontmatter: tech_lead is required when risk is high")

    if fm.get("created"):
        try:
            dt.date.fromisoformat(fm["created"])
        except ValueError:
            errors.append("frontmatter: created must be YYYY-MM-DD")
    if "systems" in fm and not isinstance(fm["systems"], list):
        errors.append("frontmatter: systems must be a list, e.g. [claims-core, portal]")

    # The intent it came from
    intent_path = Path(root) / fm.get("intent", "")
    if fm.get("intent") and intent_path.is_file():
        intent_text = intent_path.read_text(encoding="utf-8")
        ifm, _ = vi.parse_frontmatter(intent_text)
        ifm = ifm or {}
        if rid and ifm.get("record_id") and rid != ifm["record_id"]:
            errors.append(f"frontmatter: record_id {rid!r} differs from the intent's {ifm['record_id']!r}")
        oq_needed = len(intent_open_questions(intent_text))
    else:
        oq_needed = None
        if fm.get("intent"):
            warnings.append(f"intent {fm['intent']} not found; open-question carry-over not checked")

    # Body structure
    if not re.search(r"^# Spec: \S", body, re.MULTILINE):
        errors.append("missing H1 '# Spec: <title>'")
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

    if "Requirements" in sections and not REQ_ROW_RE.search(sections["Requirements"]):
        errors.append("section 'Requirements' needs at least one '| REQ-<n> | ... |' row")
    if "Security considerations" in sections and not SEC_ROW_RE.search(sections["Security considerations"]):
        errors.append("section 'Security considerations' needs at least one '| SEC-<n> | ... |' or '| INF-<n> | ... |' row (security-policy, infra-policy)")

    oq_rows = [r.group(1) for r in OQ_ROW_RE.finditer(sections.get("Open questions", ""))]
    from_intent = 0
    for row in oq_rows:
        cells = [c.strip().strip("*").strip().lower() for c in row.split("|")]
        if len(cells) < 3:
            errors.append(f"open question row has too few columns: {row[:60]!r}")
            continue
        if cells[0] == "intent":
            from_intent += 1
        if cells[2] not in OQ_STATUSES:
            errors.append(f"open question status must be one of {sorted(OQ_STATUSES)}, got {cells[2]!r}")
    if oq_needed is not None and from_intent < oq_needed:
        errors.append(
            f"the intent has {oq_needed} open questions but only {from_intent} rows with Source 'intent'; "
            "answer or carry forward every one"
        )

    stories = parse_stories(body)
    if "Work breakdown" in sections and not stories:
        errors.append("section 'Work breakdown' needs at least one '### S<n>: <title>' story")
    seen = set()
    for s in stories:
        if s["id"] in seen:
            errors.append(f"story id {s['id']} is used twice")
        seen.add(s["id"])
        criteria = s["body"].split("Acceptance criteria:", 1)
        if len(criteria) < 2 or not re.search(r"^- \S", criteria[1], re.MULTILINE):
            errors.append(f"story {s['id']} needs 'Acceptance criteria:' followed by at least one '- ' bullet")
    if len(stories) > MAX_STORIES:
        warnings.append(f"{len(stories)} stories (> {MAX_STORIES}); consider splitting the intent")

    words = len(re.findall(r"\w+", body))
    if words > MAX_WORDS:
        warnings.append(f"{words} words (> {MAX_WORDS}); tighten it so reviewers can read it in one sitting")

    return fm, errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true", help="print parsed frontmatter as JSON")
    ap.add_argument("--owners", help="owners file; owner and tech_lead must appear in it")
    ap.add_argument("--root", default=".", help="repo root, for finding the intent (default: current dir)")
    args = ap.parse_args()

    owners = vi.load_owners(args.owners) if args.owners else None
    failed, out = False, {}
    for f in args.files:
        fm, errors, warnings = validate(f, owners, args.root)
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
