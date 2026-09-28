#!/usr/bin/env python3
"""Run a skill's eval cases end to end and score them deterministically.

Each case under evals/<skill>/cases/<name>/ has:
  case.json    args for the skill and the expected outcome (see README.md)
  record.json  the source record the workflow would have fetched
  existing/    optional intents already in the repo (for duplicate cases)

For every case the runner builds a throwaway product repo, runs the real
skill headless with `claude -p` exactly as create-intent.yml does, and checks
the files it leaves behind. No model grades another model here.

Usage:
  python evals/run_evals.py --skill write-intent             # run all cases
  python evals/run_evals.py --skill write-intent --case jira-claims-status
  python evals/run_evals.py --skill write-intent --check-fixtures   # no API calls
Exit 1 if the pass rate is below min_pass_rate in evals/<skill>/config.json.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
SKILL_DIR = PLUGIN / "skills" / "write-intent"

_spec = importlib.util.spec_from_file_location("validate_intent", SKILL_DIR / "scripts" / "validate_intent.py")
vi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vi)

ALLOWED_TOOLS = "Read,Glob,Grep,Write,Edit,Bash(python3 *validate_intent.py*),Bash(python *validate_intent.py*)"
WRITE_ALLOW = ["intent/", ".sdlc-output/duplicate.txt"]


def load_case(case_dir):
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    json.loads((case_dir / "record.json").read_text(encoding="utf-8"))  # must parse
    return case


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def setup_workspace(case_dir, owners):
    # resolve(): expand Windows 8.3 names (ABALAM~1), which Claude Code treats as suspicious
    ws = Path(tempfile.mkdtemp(prefix=f"eval-{case_dir.name}-")).resolve()
    (ws / ".sdlc").mkdir()
    shutil.copy(owners, ws / ".sdlc" / "owners.yaml")
    (ws / "intent").mkdir()
    (ws / ".sdlc-input").mkdir()
    (ws / ".sdlc-output").mkdir()
    shutil.copy(case_dir / "record.json", ws / ".sdlc-input" / "record.json")
    existing = case_dir / "existing"
    if existing.is_dir():
        for f in existing.glob("*.md"):
            shutil.copy(f, ws / "intent" / f.name)
    return ws


def run_skill(ws, args, model, max_turns, timeout):
    prompt = (
        f"/sdlc:write-intent mode=headless source={args['source']} "
        f"record_id={args.get('record_id', 'none')} fingerprint={args.get('fingerprint', 'none')} "
        "input=.sdlc-input/record.json"
    )
    cmd = [
        shutil.which("claude") or "claude", "-p", prompt,
        "--plugin-dir", str(PLUGIN),
        "--model", model,
        "--max-turns", str(max_turns),
        "--strict-mcp-config",
        "--allowedTools", ALLOWED_TOOLS,
        "--output-format", "json",
    ]
    env = {**os.environ, "SDLC_HEADLESS": "1", "SDLC_WRITE_ALLOW": ",".join(WRITE_ALLOW)}
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout}s", "seconds": round(time.time() - started)}
    out = {"exit_code": proc.returncode, "seconds": round(time.time() - started)}
    try:
        result = json.loads(proc.stdout)
        out.update({k: result.get(k) for k in ("num_turns", "total_cost_usd", "is_error")})
    except ValueError:
        out["stdout_tail"] = proc.stdout[-500:]
    if proc.returncode != 0:
        out["stderr_tail"] = proc.stderr[-500:]
    return out


def matches(actual, expected):
    """Expected may be a value or a list meaning 'any of these'."""
    return actual in expected if isinstance(expected, list) else actual == expected


def score(ws, before, owners, expect):
    """Return a list of failed-check messages (empty = pass)."""
    fails = []
    after = snapshot(ws)
    changed = [p for p, m in after.items() if before.get(p) != m]
    outside = [p for p in changed if not any(p.startswith(a) for a in WRITE_ALLOW)]
    if outside:
        fails.append(f"wrote outside allowed paths: {outside}")

    new_intents = [p for p in changed if p.startswith("intent/") and p.endswith(".md")]
    dup_file = ws / ".sdlc-output" / "duplicate.txt"
    if expect.get("duplicate"):
        if not dup_file.is_file():
            fails.append("expected .sdlc-output/duplicate.txt")
        elif expect.get("duplicate_of") and expect["duplicate_of"] not in dup_file.read_text(encoding="utf-8"):
            fails.append(f"duplicate.txt does not name {expect['duplicate_of']}")
        if new_intents:
            fails.append(f"expected no new intent, got {new_intents}")
        return fails

    if dup_file.is_file():
        fails.append(f"unexpected duplicate.txt: {dup_file.read_text(encoding='utf-8').strip()}")
    if len(new_intents) != 1:
        fails.append(f"expected exactly one new intent file, got {new_intents}")
        return fails

    path = ws / new_intents[0]
    fm, errors, _ = vi.validate(path, vi.load_owners(owners))
    if errors and expect.get("valid", True):
        fails.append(f"validator errors: {errors}")
    text = path.read_text(encoding="utf-8")
    _, body = vi.parse_frontmatter(text)
    _, sections = vi.split_sections(body)
    lower = text.lower()

    for key, want in expect.get("frontmatter", {}).items():
        if not matches(fm.get(key), want):
            fails.append(f"frontmatter {key}={fm.get(key)!r}, want {want!r}")
    for key, bad in expect.get("frontmatter_not", {}).items():
        if matches(fm.get(key), bad):
            fails.append(f"frontmatter {key}={fm.get(key)!r} must not be {bad!r}")
    missing = [s for s in expect.get("systems_include", []) if s not in (fm.get("systems") or [])]
    if missing:
        fails.append(f"systems missing {missing}, got {fm.get('systems')}")
    if "author_contains" in expect and expect["author_contains"].lower() not in fm.get("author", "").lower():
        fails.append(f"author {fm.get('author')!r} should contain {expect['author_contains']!r}")
    if "author_not" in expect and expect["author_not"].lower() in fm.get("author", "").lower():
        fails.append(f"author {fm.get('author')!r} must not contain {expect['author_not']!r}")
    if "title_prefix" in expect and not fm.get("title", "").startswith(expect["title_prefix"]):
        fails.append(f"title {fm.get('title')!r} should start with {expect['title_prefix']!r}")
    for s in expect.get("body_contains", []):
        if s.lower() not in lower:
            fails.append(f"missing text {s!r}")
    for s in expect.get("body_not_contains", []):
        if s.lower() in lower:
            fails.append(f"must not contain {s!r}")
    for section, needles in expect.get("section_contains_any", {}).items():
        content = sections.get(section, "").lower()
        if not any(n.lower() in content for n in needles):
            fails.append(f"section {section!r} should mention one of {needles}")
    return fails


def check_fixtures(cases, owners):
    known = vi.load_owners(owners)
    problems = []
    for case_dir in cases:
        try:
            case = load_case(case_dir)
        except (OSError, ValueError) as e:
            problems.append(f"{case_dir.name}: {e}")
            continue
        want = case.get("expect", {}).get("frontmatter", {}).get("owner")
        for o in (want if isinstance(want, list) else [want] if want else []):
            if o not in known:
                problems.append(f"{case_dir.name}: expected owner {o} not in {owners.name}")
        for f in (case_dir / "existing").glob("*.md") if (case_dir / "existing").is_dir() else []:
            _, errors, _ = vi.validate(f, known)
            if errors:
                problems.append(f"{case_dir.name}: existing/{f.name} invalid: {errors}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", default="write-intent")
    ap.add_argument("--case", action="append", help="run only these cases (repeatable)")
    ap.add_argument("--model", default=os.environ.get("EVAL_MODEL", "claude-sonnet-5"))
    ap.add_argument("--max-turns", type=int, default=30)
    ap.add_argument("--timeout", type=int, default=900, help="seconds per case")
    ap.add_argument("--report", help="write JSON results here")
    ap.add_argument("--keep", action="store_true", help="keep workspaces for inspection")
    ap.add_argument("--check-fixtures", action="store_true", help="only check case files; no API calls")
    args = ap.parse_args()

    skill_evals = ROOT / "evals" / args.skill
    config = json.loads((skill_evals / "config.json").read_text(encoding="utf-8"))
    owners = (skill_evals / config["owners"]).resolve()
    cases = sorted(p for p in (skill_evals / "cases").iterdir() if p.is_dir())
    if args.case:
        cases = [c for c in cases if c.name in args.case]
    if not cases:
        sys.exit("no cases found")

    if args.check_fixtures:
        problems = check_fixtures(cases, owners)
        for p in problems:
            print(f"::error::{p}")
        print(f"{len(cases)} cases, {len(problems)} fixture problems")
        sys.exit(1 if problems else 0)

    results = []
    for case_dir in cases:
        case = load_case(case_dir)
        ws = setup_workspace(case_dir, owners)
        before = snapshot(ws)
        run = run_skill(ws, case["args"], args.model, args.max_turns, args.timeout)
        fails = [run["error"]] if "error" in run else score(ws, before, owners, case["expect"])
        results.append({"case": case_dir.name, "passed": not fails, "fails": fails, "run": run,
                        "workspace": str(ws) if args.keep else None})
        print(f"{'PASS' if not fails else 'FAIL'} {case_dir.name} ({run.get('seconds')}s)")
        for f in fails:
            print(f"     - {f}")
        if not args.keep:
            shutil.rmtree(ws, ignore_errors=True)

    passed = sum(r["passed"] for r in results)
    rate = passed / len(results)
    minimum = config["min_pass_rate"]
    ok = rate >= minimum
    summary = f"{args.skill}: {passed}/{len(results)} passed ({rate:.0%}), minimum {minimum:.0%} -> {'OK' if ok else 'BLOCKED'}"
    print(summary)

    if args.report:
        Path(args.report).write_text(json.dumps({"summary": summary, "model": args.model, "results": results}, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### Evals: {summary}\n\n| Case | Result | Failed checks |\n|---|---|---|\n")
            for r in results:
                fh.write(f"| {r['case']} | {'pass' if r['passed'] else 'FAIL'} | {'<br>'.join(r['fails']) or ''} |\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
