#!/usr/bin/env python3
"""Validate plans/*.md (Build stage) against the spec story they implement.

Deterministic gate used by the build-story skill, the verifier subagent and
the product repo's story-check workflow. Standard library only.

Usage (from the product repo root):
  validate_plan.py plans/foo-s1.md
  validate_plan.py --check-tests plans/foo-s1.md   # also: every AC has a test

The plan must map every acceptance criterion of its story (in the spec) to a
test named after "S<n> AC-<k>". --check-tests then looks for those names in
the repo's test paths (`test_paths` in .sdlc/build.yaml, default tests/).

Test names are matched in any language's style, case-insensitive:
"S1 AC-2: ..." (Playwright, Jest, JUnit @DisplayName), test_s1_ac_2_...
(pytest, Go), S1Ac2... (C#, Java method names).

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

_BG_PATH = Path(__file__).resolve().parents[3] / "hooks" / "build_guard.py"
_bspec = importlib.util.spec_from_file_location("build_guard", _BG_PATH)
bg = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(bg)

REQUIRED_KEYS = ["id", "spec", "story", "jira", "branch", "created"]
SECTIONS = ["Story", "Files", "Tests", "Steps", "Risks and rollback", "Out of scope"]
MUST_BE_REAL = ["Story", "Files", "Tests", "Steps"]
STORY_ID_RE = re.compile(r"^S\d+$")
AC_ROW_RE = re.compile(r"^\|\s*AC-(\d+)\s*\|([^|]*)\|([^|]*)\|\s*$", re.MULTILINE)
FILE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|([^|]*)\|\s*$", re.MULTILINE)
TEST_SUFFIXES = {
    ".js", ".mjs", ".cjs", ".ts", ".mts", ".jsx", ".tsx", ".py", ".java", ".kt", ".kts", ".scala",
    ".groovy", ".cs", ".fs", ".vb", ".go", ".rb", ".php", ".rs", ".swift", ".dart", ".ex", ".exs",
    ".feature", ".robot", ".spec", ".sh",
}
DEFAULT_TEST_PATHS = ["tests/"]


def test_paths(root):
    """Where tests live, from .sdlc/build.yaml (`test_paths`), default tests/."""
    cfg = bg.load_build_config(root) or {}
    paths = cfg.get("test_paths") or DEFAULT_TEST_PATHS
    if isinstance(paths, str):
        paths = [paths]
    return [p.strip("/") + "/" for p in paths if p.strip("/")]


def name_pattern(story_id, k):
    """Regex for the test of AC-k in any naming style: 'S1 AC-2', 's1_ac_2', 'S1Ac2', 'S1-AC-2'."""
    n = story_id[1:]
    return re.compile(rf"(?i)(?<![a-z0-9])s{n}[ _-]?ac[ _-]?{k}(?!\d)")


def story_criteria(spec_text, story_id):
    """Acceptance-criterion bullets of one story in the spec, or None if absent."""
    _, body = vi.parse_frontmatter(spec_text)
    for s in vs.parse_stories(body or ""):
        if s["id"] == story_id:
            after = s["body"].split("Acceptance criteria:", 1)
            if len(after) < 2:
                return []
            return [l[2:].strip() for l in after[1].splitlines() if l.startswith("- ")]
    return None


def story_screens(root, spec_slug, story_id):
    """Screen ids in designs/<spec-slug>/design.md whose Stories column names this story."""
    manifest = Path(root) / "designs" / spec_slug / "design.md"
    if not manifest.is_file():
        return []
    _, body = vi.parse_frontmatter(manifest.read_text(encoding="utf-8"))
    _, sections = vi.split_sections(body or "")
    screens = []
    for line in sections.get("Screens", "").splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and re.search(rf"\b{re.escape(story_id)}\b", cells[3]) and cells[0].lower() != "screen":
            screens.append(cells[0])
    return screens


def design_created(root, spec_slug):
    """The design manifest's `created` date (YYYY-MM-DD string), or None."""
    manifest = Path(root) / "designs" / spec_slug / "design.md"
    if not manifest.is_file():
        return None
    fm, _ = vi.parse_frontmatter(manifest.read_text(encoding="utf-8"))
    return (fm or {}).get("created")


def test_names_found(root, names):
    """Which of the given test names ("S<n> AC-<k>") appear in the repo's test files."""
    texts = []
    for rel in test_paths(root):
        base = Path(root) / rel
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in TEST_SUFFIXES and "node_modules" not in p.parts:
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(texts)
    found = set()
    for n in names:
        story, ac = n.split(" AC-")
        if name_pattern(story, ac).search(blob):
            found.add(n)
    return found


def validate(path, root=".", check_tests=False):
    errors, warnings = [], []
    text = Path(path).read_text(encoding="utf-8")
    fm, body = vi.parse_frontmatter(text)
    if fm is None:
        return {}, ["missing YAML frontmatter block (--- ... ---) at top of file"], warnings
    for bad in fm.pop("__bad__", []):
        errors.append(f"unparseable frontmatter line: {bad!r}")
    for key in REQUIRED_KEYS:
        if not fm.get(key):
            errors.append(f"frontmatter: '{key}' is required")

    story, jira = fm.get("story", ""), fm.get("jira", "")
    if story and not STORY_ID_RE.match(story):
        errors.append(f"frontmatter: story must look like S1, got {story!r}")
    if jira and jira != "none" and not vi.JIRA_RE.match(jira):
        errors.append(f"frontmatter: jira must be a Jira key (ABC-123) or none, got {jira!r}")
    branch = fm.get("branch", "")
    if branch and jira == "none" and fm.get("id"):
        # No Jira: the branch is named after the plan (story/<spec-slug>-s<n>).
        if not re.match(rf"^story/{re.escape(fm['id'])}(-[a-z0-9]+)*$", branch):
            errors.append(f"frontmatter: branch must be story/{fm['id']} (jira: none), got {branch!r}")
    elif branch and jira and not re.match(rf"^story/{re.escape(jira.lower())}(-[a-z0-9]+)+$", branch):
        errors.append(f"frontmatter: branch must be story/{jira.lower()}-<short-name>, got {branch!r}")
    if fm.get("created"):
        try:
            dt.date.fromisoformat(fm["created"])
        except ValueError:
            errors.append("frontmatter: created must be YYYY-MM-DD")

    stem = Path(path).stem
    if fm.get("id") and fm["id"] != stem:
        errors.append(f"frontmatter: id {fm['id']!r} must match file name {stem!r}")
    spec_rel = fm.get("spec", "")
    spec_slug = Path(spec_rel).stem if spec_rel else ""
    if fm.get("id") and spec_slug and story and fm["id"] != f"{spec_slug}-{story.lower()}":
        errors.append(f"frontmatter: id must be '{spec_slug}-{story.lower()}' (spec slug + story), got {fm['id']!r}")

    criteria = None
    spec_path = Path(root) / spec_rel
    if spec_rel and not spec_path.is_file():
        errors.append(f"spec {spec_rel} not found")
    elif spec_rel and story:
        criteria = story_criteria(spec_path.read_text(encoding="utf-8"), story)
        if criteria is None:
            errors.append(f"story {story} not found in {spec_rel}")
        elif not criteria:
            errors.append(f"story {story} in {spec_rel} has no acceptance criteria")

    if not re.search(r"^# Plan: S\d+ \S", body, re.MULTILINE):
        errors.append("missing H1 '# Plan: S<n> <story title>'")
    order, sections = vi.split_sections(body)
    # "Design" is optional, right after "Story"; it is required when the story has screens.
    expected = SECTIONS[:1] + ["Design"] + SECTIONS[1:] if "Design" in order else SECTIONS
    if order != expected:
        missing = [s for s in expected if s not in order]
        extra = [s for s in order if s not in expected]
        detail = ([f"missing {missing}"] if missing else []) + ([f"unexpected {extra}"] if extra else [])
        errors.append(f"section headings must be exactly {expected} ({'; '.join(detail) or 'wrong order'})")

    screens = story_screens(root, spec_slug, story) if spec_slug and story else []
    if screens:
        design = sections.get("Design", "")
        # A plan written before the design existed cannot reference it: warn, don't fail.
        design_date = design_created(root, spec_slug)
        predates = bool(design_date and fm.get("created") and fm["created"] < design_date)
        report = warnings if predates else errors
        note = f" (plan {fm.get('created')} predates the design {design_date}; reference it next time this story changes)" if predates else ""
        if not design:
            report.append(f"story {story} has design screens {screens} in designs/{spec_slug}/design.md; "
                          f"add a '## Design' section after '## Story' naming each one{note}")
        for sid in screens:
            if design and not re.search(rf"(?<![a-z0-9-]){re.escape(sid)}(?![a-z0-9-])", design):
                report.append(f"Design section must reference screen {sid!r} (designs/{spec_slug}/screens/{sid}.png){note}")
    for ph in vi.placeholders(text):
        errors.append(f"unfilled template placeholder: {ph[:60]}")
    for name in MUST_BE_REAL:
        content = sections.get(name, "")
        if not content:
            errors.append(f"section '{name}' is empty")
        elif vi.FILLER_RE.search(content):
            errors.append(f"section '{name}' contains filler (TBD/TODO); it needs real content")

    file_rows = [m for m in FILE_ROW_RE.finditer(sections.get("Files", ""))
                 if m.group(1).lower() != "file" and not set(m.group(1)) <= set("-: ")]
    if "Files" in sections and not file_rows:
        errors.append("section 'Files' needs at least one '| <path> | <change> |' row")

    rows = {int(m.group(1)): (m.group(2).strip(), m.group(3).strip()) for m in AC_ROW_RE.finditer(sections.get("Tests", ""))}
    if criteria:
        want = set(range(1, len(criteria) + 1))
        if set(rows) != want:
            missing = sorted(want - set(rows))
            extra = sorted(set(rows) - want)
            errors.append(
                f"Tests must have one row per acceptance criterion of {story} (AC-1..AC-{len(criteria)})"
                + (f"; missing {['AC-%d' % k for k in missing]}" if missing else "")
                + (f"; not in the spec {['AC-%d' % k for k in extra]}" if extra else ""))
        paths = test_paths(root)
        for k, (_, test) in sorted(rows.items()):
            name = f"{story} AC-{k}"
            if not any(p in test for p in paths):
                errors.append(f"AC-{k}: the Test column must name a file under {' or '.join(paths)} "
                              "(test_paths in .sdlc/build.yaml)")
            if not name_pattern(story, k).search(test):
                errors.append(f"AC-{k}: the Test column must name a test for \"{name}\" "
                              f"(e.g. \"{name}: ...\" or test_{story.lower()}_ac_{k}_...)")
        if check_tests:
            names = [f"{story} AC-{k}" for k in sorted(want)]
            found = test_names_found(root, names)
            for n in names:
                if n not in found:
                    errors.append(f"no test titled \"{n}: ...\" found under tests/")
    return fm, errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--check-tests", action="store_true", help="also require every AC's test to exist under tests/")
    ap.add_argument("--root", default=".", help="product repo root (default: current dir)")
    args = ap.parse_args()
    failed = False
    for f in args.files:
        _, errors, warnings = validate(f, args.root, args.check_tests)
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
