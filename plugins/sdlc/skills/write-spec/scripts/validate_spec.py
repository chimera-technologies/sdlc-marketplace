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
# Repository layout, decided like the stack (init_project.py --stack records it).
# Longest value first: "one repo per service" also starts with "one repo".
LAYOUT_RE = re.compile(r"^(?:- )?\**Repository layout:?\**:?\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
LAYOUTS = [("one repo per service", "per-service"), ("one repo", "one-repo"), ("decision needed", "open")]
SERVICE_MAP_COLUMNS = ["Component", "Responsibility", "Owns data", "Repo", "Stack", "UI",
                       "Product owner", "Service owner", "Tech lead"]
COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REPO_RE = re.compile(r"^(?:[A-Za-z0-9-]+/)?[A-Za-z0-9._-]+$")
# The data decision: 'Data store:' and, when there is one, how it is changed, tested and run.
DATA_LINES = ["Data store", "Migrations", "Test database", "Test data", "Run locally"]


def data_line(text, label):
    """The value of a '- **<label>:** value' line (bold and bullet optional), or None if absent."""
    m = re.search(rf"^(?:- )?\**{re.escape(label)}:?\**:?[ \t]*(.*?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip("* ") if m else None


def check_data(text):
    """Errors in the data lines of 'Technology and architecture' (all optional until 'Data store:' names one)."""
    store = data_line(text, "Data store")
    if store is None or store.lower() == "none" or store.lower().startswith("decision needed"):
        return []
    if not store:
        return ["'Data store:' needs a value: the database, 'none', or 'decision needed'"]
    return [f"Data store is {store!r}: add '{label}:' (see the write-spec skill's Data item)"
            for label in DATA_LINES[1:] if not data_line(text, label)]


def parse_layout(text):
    """(layout, raw) from the 'Repository layout:' line: one-repo, per-service, open; (None, None) if absent."""
    m = LAYOUT_RE.search(text)
    if not m:
        return None, None
    raw = m.group(1).strip("* ")
    for words, key in LAYOUTS:
        if raw.lower().startswith(words):
            return key, raw
    return "invalid", raw


def parse_service_map(text):
    """Rows of the Service map table (header starting '| Component |'): [{column: cell}], or None if absent."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and cells and cells[0].lower() == "component":
            rows = []
            for row in lines[i + 1:]:
                if not row.lstrip().startswith("|"):
                    break
                vals = [c.strip() for c in row.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{3,}:?", v) for v in vals):
                    continue
                rows.append(dict(zip(cells, vals)))
            return cells, rows
    return None, None


def check_layout(text):
    """Errors in the Repository layout line and the Service map of 'Technology and architecture'."""
    errors = []
    layout, raw = parse_layout(text)
    header, rows = parse_service_map(text)
    if layout == "invalid":
        errors.append(f"'Repository layout: {raw}' must start with one of: {', '.join(w for w, _ in LAYOUTS)}")
    if header is None:
        if layout == "per-service":
            errors.append("Repository layout is one repo per service: add the Service map table "
                          f"(| {' | '.join(SERVICE_MAP_COLUMNS)} |) with one row per service")
        return errors
    if layout == "one-repo":
        errors.append("a Service map is only for 'Repository layout: one repo per service'")
    if header != SERVICE_MAP_COLUMNS:
        errors.append(f"Service map columns must be exactly | {' | '.join(SERVICE_MAP_COLUMNS)} |")
        return errors
    if not rows:
        errors.append("Service map needs one row per service")
    seen, repos = set(), set()
    for r in rows:
        name, repo = r.get("Component", "").strip("`"), r.get("Repo", "").strip("`")
        if not COMPONENT_RE.match(name):
            errors.append(f"Service map: component {name!r} must be kebab-case")
        if not REPO_RE.match(repo):
            errors.append(f"Service map: repo {repo!r} for {name!r} must be a repo name or owner/name")
        if name in seen or repo.split("/")[-1].lower() in repos:
            errors.append(f"Service map: {name!r} and its repo must appear once")
        seen.add(name)
        repos.add(repo.split("/")[-1].lower())
        if r.get("UI", "").lower() not in ("yes", "no"):
            errors.append(f"Service map: UI for {name!r} must be yes or no")
        for col in ("Product owner", "Service owner", "Tech lead"):
            if not vi.OWNER_RE.match(r.get(col, "").strip('`"')):
                errors.append(f"Service map: {col} for {name!r} must be @user or @org/team")
        if not r.get("Responsibility") or not r.get("Owns data"):
            errors.append(f"Service map: say what {name!r} is responsible for and which data it owns (or 'none')")
    return errors


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
    errors += check_layout(sections.get("Technology and architecture", ""))
    errors += check_data(sections.get("Technology and architecture", ""))
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
