#!/usr/bin/env python3
"""Write the test report of one merged story (test-reports/<plan-id>/).

Deterministic, standard library only. The sdlc-main-tests workflow runs it
after a story PR merges and the tests on the base branch have run, then
opens the report as a test-report PR. Every input but the plan is optional;
what is missing shows as "unknown".

  python test_report.py --plan plans/<id>.md \
      --story-pr story-pr.json      # gh pr view --json number,title,url,body,comments,headRefName,mergedAt,mergeCommit
      --story-checks checks.json    # gh pr checks --json name,state,link
      --plan-pr plan-pr.json        # gh pr view --json number,url,body,mergedAt
      --pr-log pr-tests.log         # log of the PR's test job
      --main-log main-tests.log     # log of the base branch's test job
      --main-result success --main-url <job url> [--out test-reports]

It writes, for the story:
  README.md          the story, its PRs and the result of each testing flow
  test-cases.md      every test named for the story, with its status per flow
  review-findings.md the plan review, the verifier report and the PR review gate
  summary.json       read back to rebuild the index
and rebuilds test-reports/README.md, the index of every story's report.

Test cases are the tests whose names start with the story (S<n> ...) in the
repo's test paths, in any language's style (see validate_plan.py). Their
status per flow is the result of the run that included them: CI logs give
counts, not names, so a passing suite marks each of its tests passing.
"""
import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

_VP_PATH = Path(__file__).resolve().parent / "validate_plan.py"
_spec = importlib.util.spec_from_file_location("validate_plan", _VP_PATH)
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)
vi = vp.vi

ICON = {"pass": "✅", "fail": "❌", "skipped": "⏸", "missing": "❌ missing", "unknown": "❔"}
GATE_MARKER = "<!-- sdlc-review-gate -->"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOG_PREFIX_RE = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ")
# Summary lines of common test runners: Vitest/Jest, Playwright, pytest,
# unittest, Maven/Gradle, go test, dotnet test, npm audit.
SUMMARY_RE = re.compile(
    r"(?i)^\s*(test files|tests?)\s+\d+|^\s*\d+ (passed|failed|skipped|flaky)\b|\b\d+ (passed|failed)\b.* in [\d.]+s"
    r"|^ran \d+ tests?|^(ok|failed) \(|^tests run: \d+|^(ok|fail)\s+\S+\s+[\d.]+s|^(passed|failed)!\s+-"
    r"|found \d+ vulnerabilit|^npm audit:")
ID_ROW_RE = re.compile(r"^\|\s*((?:AC|EC|BUG)-\d+)\s*\|.*\|\s*([^|]*?)\s*\|\s*$", re.MULTILINE)
GROUP_RE = re.compile(r"\b(describe|context|suite)(\.\w+)?\s*\(")


def read_json(path):
    if not path or not Path(path).is_file():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace") if path and Path(path).is_file() else ""


def state(value):
    """A check or job conclusion as pass / fail / skipped / unknown."""
    v = (value or "").strip().lower()
    if v in ("success", "pass", "passed", "ok", "yes"):
        return "pass"
    if v in ("failure", "fail", "failed", "error", "timed_out", "cancelled", "action_required", "no"):
        return "fail"
    if v in ("skipped", "neutral"):
        return "skipped"
    return "unknown"


def story_tests(root, story):
    """[(name, file)] of every test named for the story, in file order, without duplicates."""
    n = story[1:]
    patterns = [
        # "S1 AC-1: ..." (JS, TS, JUnit, xUnit); the other quote kinds may appear inside
        *(re.compile(rf"({q})({story}(?!\d)[^{q}\n]{{0,200}}){q}") for q in "\"'`"),
        re.compile(rf"(?i)\b()(test_s{n}(?!\d)_[a-z0-9_]+)"),            # test_s1_ac_1_... (pytest)
        re.compile(rf"\b()(Test_?S{n}(?!\d)[A-Za-z0-9_]*)"),             # TestS1Ac1... (Go)
    ]
    found, seen = [], set()
    for rel in vp.test_paths(root):
        base = Path(root) / rel
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in vp.TEST_SUFFIXES or "node_modules" in p.parts:
                continue
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if GROUP_RE.search(line):
                    continue
                for pat in patterns:
                    for m in pat.finditer(line):
                        name = m.group(2).strip()
                        if name not in seen:
                            seen.add(name)
                            found.append((name, p.relative_to(root).as_posix()))
    return found


def test_id(story, name):
    """AC-k, EC-k or BUG-k when the test is named for one, else None."""
    name = re.sub(r"^Test_?(?=S\d)", "", name)   # Go: TestS1Ac2...
    m = re.search(rf"(?i)(?<![a-z0-9]){story}[ _-]?(ac|ec|bug)[ _-]?(\d+)(?!\d)", name)
    return f"{m.group(1).upper()}-{m.group(2)}" if m else None


def build_status(body):
    """From the story PR body: (overall, verdict, {ID: pass/fail}) as the build reported them."""
    overall = "unknown"
    m = re.search(r"(?m)^RESULT:\s*(PASS|INCOMPLETE)\b", body)
    if m:
        overall = "pass" if m.group(1) == "PASS" else "fail"
    v = re.search(r"VERDICT:\**\s*(PASS|FAIL)\b", body)
    verdict = ("pass" if v.group(1) == "PASS" else "fail") if v else "unknown"
    per_id = {}
    for m in ID_ROW_RE.finditer(body):
        cell = m.group(2).lower()
        if cell.startswith(("yes", "pass", "✅")):
            per_id[m.group(1)] = "pass"
        elif cell.startswith(("no", "fail", "❌")):
            per_id[m.group(1)] = "fail"
    return overall, verdict, per_id


def checks_by_name(checks):
    """{check name: (state, link)} from `gh pr checks --json name,state,link`."""
    return {c.get("name", ""): (state(c.get("state")), c.get("link", "")) for c in checks or []}


def find_check(checks, suffix):
    """The check whose name ends with '/ <suffix>' (or is <suffix>), as (state, link)."""
    for name, val in checks.items():
        if name == suffix or name.endswith(f"/ {suffix}"):
            return val
    return ("unknown", "")


def summary_lines(log, limit=20):
    """Test-runner summary lines from a CI job log (counts, not names)."""
    out = []
    for raw in log.splitlines():
        line = LOG_PREFIX_RE.sub("", ANSI_RE.sub("", raw)).rstrip()
        if SUMMARY_RE.search(line) and line.strip() not in out:
            out.append(line.strip())
    return out[:limit]


def section_after(body, heading_re, stop_re=r"^(#{1,3} |<details>|Plan: `|_The review flags)"):
    """The text from the first line matching heading_re to the next stop line (exclusive)."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if re.search(heading_re, line):
            out = [line]
            for nxt in lines[i + 1:]:
                if re.match(stop_re, nxt):
                    break
                out.append(nxt)
            return "\n".join(out).strip()
    return ""


def plan_review(plan_body):
    """The plan review section of the plan PR body (it is markdown already)."""
    lines = plan_body.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("### Plan review")), None)
    if start is None:
        return ""
    out = []
    for line in lines[start:]:
        if line.startswith("### Review checklist") or line.startswith("<details>"):
            break
        out.append(line)
    return "\n".join(out).strip()


def review_gate(comments):
    for c in comments or []:
        body = (c.get("body") or "").strip()
        if body.startswith(GATE_MARKER):
            return body[len(GATE_MARKER):].strip()
    return ""


def link(text, url):
    return f"[{text}]({url})" if url else text


def collect(args):
    """Everything the report needs, as one dict (also written as summary.json)."""
    root = Path(args.root)
    plan_path = Path(args.plan)
    fm, body = vi.parse_frontmatter(plan_path.read_text(encoding="utf-8"))
    fm = fm or {}
    story = fm.get("story", "")
    title_m = re.search(r"^# Plan: (S\d+) (.+)$", body or "", re.MULTILINE)
    _, sections = vi.split_sections(body or "")
    acs = {f"AC-{m.group(1)}": m.group(2).strip()
           for m in vp.AC_ROW_RE.finditer(sections.get("Tests", ""))}
    findings = vp.review_findings(body or "")

    spr = read_json(args.story_pr) or {}
    ppr = read_json(args.plan_pr) or {}
    checks = checks_by_name(read_json(args.story_checks))
    overall, verdict, per_id = build_status(spr.get("body") or "")
    pr_tests, pr_tests_url = find_check(checks, args.test_check)
    trace, trace_url = find_check(checks, "traceability")
    gate, gate_url = find_check(checks, "review-gate")
    advisory = [(n, s, l) for n, (s, l) in checks.items() if "advisory" in n]
    main = state(args.main_result)

    tests = []
    for name, file in story_tests(root, story):
        tid = test_id(story, name)
        tests.append({"id": tid, "name": name, "file": file,
                      "build": per_id.get(tid, overall) if tid else overall,
                      "pr": pr_tests, "main": main})
    have = {t["id"] for t in tests if t["id"]}
    for tid in list(acs) + [f for f in findings if not vp.DECISION_RE.match(findings[f]["handling"])]:
        if tid not in have:
            tests.append({"id": tid, "name": f"{story} {tid}: (no test found)", "file": "",
                          "build": "missing", "pr": "missing", "main": "missing"})

    merge = spr.get("mergeCommit") or {}
    return {
        "id": fm.get("id") or plan_path.stem, "story": story, "title": title_m.group(2).strip() if title_m else "",
        "spec": fm.get("spec", ""), "jira": fm.get("jira", ""), "branch": fm.get("branch", ""),
        "plan": plan_path.as_posix(), "date": args.date,
        "story_pr": {"number": spr.get("number"), "url": spr.get("url", ""),
                     "merged": (spr.get("mergedAt") or "")[:10], "commit": (merge.get("oid") or "")[:7]},
        "plan_pr": {"number": ppr.get("number"), "url": ppr.get("url", ""), "merged": (ppr.get("mergedAt") or "")[:10]},
        "acs": acs, "findings": findings, "tests": tests,
        "build": {"overall": overall, "verdict": verdict, "run": run_url(spr.get("body") or "")},
        "pr": {"tests": pr_tests, "tests_url": pr_tests_url, "traceability": trace, "traceability_url": trace_url,
               "gate": gate, "gate_url": gate_url, "advisory": advisory,
               "summary": summary_lines(read_text(args.pr_log))},
        "main": {"result": main, "url": args.main_url, "summary": summary_lines(read_text(args.main_log))},
        "plan_review": plan_review(ppr.get("body") or ""),
        "verifier": section_after(spr.get("body") or "", r"(?i)^#+ .*verifier") or
                    section_after(spr.get("body") or "", r"VERDICT:", stop_re=r"^$"),
        "gate_comment": review_gate(spr.get("comments")),
    }


def run_url(body):
    m = re.search(r"Run: (https://\S+/actions/runs/\d+)", body)
    return m.group(1) if m else ""


def overall_result(r):
    flows = [r["build"]["overall"], r["pr"]["tests"], r["pr"]["traceability"], r["pr"]["gate"], r["main"]["result"]]
    statuses = {t[k] for t in r["tests"] for k in ("build", "pr", "main")}
    if "fail" in flows or statuses & {"fail", "missing"}:
        return "fail"
    return "pass" if all(f == "pass" for f in flows) else "unknown"


def render_readme(r):
    sp, pp, b, pr, mn = r["story_pr"], r["plan_pr"], r["build"], r["pr"], r["main"]
    res = overall_result(r)
    n_tests = len([t for t in r["tests"] if t["file"]])
    word = {"pass": "**PASS**", "fail": "**FAIL**", "unknown": "**INCOMPLETE** (some results are unknown)"}[res]
    jira = f" (Jira {r['jira']})" if r["jira"] and r["jira"] != "none" else ""
    lines = [
        f"# {r['story']}: {r['title']} — test report", "",
        "| | |", "|---|---|",
        f"| Story | {r['story']} of `{r['spec']}`{jira} |",
        f"| Plan | `{r['plan']}`" + (f" (plan PR {link('#' + str(pp['number']), pp['url'])}, merged {pp['merged']})" if pp["number"] else "") + " |",
        f"| Story PR | {link('#' + str(sp['number']), sp['url'])}, branch `{r['branch']}`, merged {sp['merged']} as `{sp['commit']}` |"
        if sp["number"] else f"| Story PR | branch `{r['branch']}` |",
        f"| Overall | {ICON.get(res, '❔')} {word}: {n_tests} test cases |", "",
        f"Generated {r['date']} after the merge, from the plan, the plan and story PRs, and the CI runs.", "",
        "## Status per testing flow", "",
        "| # | Flow | Result | Evidence |", "|---|---|---|---|",
        f"| 1 | Test planning (plan Tests table, `review-plan`) | {len(r['acs'])} acceptance criteria, "
        f"{len(r['findings'])} review findings to fix | [review-findings.md](review-findings.md) |",
        f"| 2 | Build tests + verifier (before the story PR) | {ICON[b['overall']]} build {b['overall']}, verifier {ICON[b['verdict']]} {b['verdict']} | "
        + (link("build run", b["run"]) if b["run"] else "story PR body") + " |",
        f"| 3a | PR review gate | {ICON[pr['gate']]} {pr['gate']} | {link('job', pr['gate_url']) or '—'} |",
        f"| 3b | Traceability (every AC, EC and BUG has its test) | {ICON[pr['traceability']]} {pr['traceability']} | {link('job', pr['traceability_url']) or '—'} |",
        f"| 3c | PR tests | {ICON[pr['tests']]} {pr['tests']} | {link('job', pr['tests_url']) or '—'} |",
        f"| 4 | Tests on the base branch after the merge | {ICON[mn['result']]} {mn['result']} | {link('job', mn['url']) or '—'} |",
    ]
    for name, s, l in pr["advisory"]:
        lines.append(f"| — | Advisory: `{name}` (comments only) | {ICON[s]} {s} | {link('job', l) or '—'} |")
    lines += ["", "Per-test detail: [test-cases.md](test-cases.md)."]
    for label, summary in (("PR tests", pr["summary"]), ("Base branch tests", mn["summary"])):
        if summary:
            lines += ["", f"<details><summary>{label}: runner summary</summary>", "", "```", *summary, "```", "</details>"]
    problems = [f"- {t['id'] or t['name']}: {t['name']} ({t['file'] or 'no test file'})" for t in r["tests"]
                if {"fail", "missing"} & {t["build"], t["pr"], t["main"]}]
    if problems:
        lines += ["", "## Needs attention", "", *problems]
    return "\n".join(lines) + "\n"


def render_test_cases(r):
    def row(t):
        return (f"| {t['id'] or '—'} | {t['name']} | {t['file'] or '—'} | "
                f"{ICON[t['build']]} | {ICON[t['pr']]} | {ICON[t['main']]} |")
    head = ["| ID | Test | File | Build | PR | Main |", "|---|---|---|---|---|---|"]
    order = {k: i for i, k in enumerate(list(r["acs"]) + list(r["findings"]))}
    acs = sorted((t for t in r["tests"] if t["id"] in r["acs"]), key=lambda t: order[t["id"]])
    fixes = sorted((t for t in r["tests"] if t["id"] in r["findings"]), key=lambda t: order[t["id"]])
    other = [t for t in r["tests"] if t not in acs and t not in fixes]
    lines = [f"# {r['story']} test cases and status", "",
             "Every test named for the story, with its status in each flow that ran it:", "",
             "- **Build**: the build's own runs and the verifier, before the story PR opened",
             "- **PR**: the PR's test check after the review gate",
             "- **Main**: the tests on the base branch after the merge", "",
             "CI logs give counts, not names: a passing suite marks each of its tests passing "
             "(see the runner summaries in [README.md](README.md)).", ""]
    for title, rows in (("Acceptance criteria", acs), ("Review findings (must fix)", fixes), ("Other tests", other)):
        if rows:
            lines += [f"## {title}", "", *head, *[row(t) for t in rows], ""]
    if not r["tests"]:
        lines += [f"No test named for {r['story']} was found under the test paths.", ""]
    return "\n".join(lines)


def render_findings(r):
    lines = [f"# {r['story']} review findings and verification", "", "## Plan review", ""]
    lines += [r["plan_review"] or "No plan review found in the plan PR.", ""]
    if r["findings"]:
        lines += ["### Must-fix findings in the plan", "", "| ID | Finding | Handling | Test |", "|---|---|---|---|"]
        lines += [f"| {k} | {v['finding']} | {v['handling']} | {v['test']} |" for k, v in r["findings"].items()]
        lines += ["", "Low bugs are optional and go to the Jira story as a comment; check there whether each was fixed.", ""]
    lines += ["## Verifier", "", r["verifier"] or "No verifier report found in the story PR body.", "",
              "## PR review gate", "", r["gate_comment"] or "No review gate comment found on the story PR.", ""]
    return "\n".join(lines)


def render_index(out):
    rows = []
    for p in sorted(out.glob("*/summary.json")):
        s = read_json(p) or {}
        jira = s.get("jira") if s.get("jira") not in (None, "", "none") else "—"
        rows.append((s.get("story", ""), f"| [{s.get('story', '')}: {s.get('title', '')}]({p.parent.name}/README.md) | {jira} | "
                     f"{s.get('tests', 0)} | {ICON.get(s.get('result'), '❔')} {s.get('result', 'unknown')} | {s.get('date', '')} |"))
    rows.sort(key=lambda r: int(re.sub(r"\D", "", r[0]) or 0))
    return "\n".join([
        "# Test reports", "",
        "One folder per merged story, generated by the sdlc plugin after each story PR merges:",
        "every test case and its status in each testing flow.", "",
        "| Story | Jira | Test cases | Result | Generated |", "|---|---|---|---|---|",
        *[r[1] for r in rows], ""])


def write(r, out):
    folder = out / r["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "README.md").write_text(render_readme(r), encoding="utf-8")
    (folder / "test-cases.md").write_text(render_test_cases(r), encoding="utf-8")
    (folder / "review-findings.md").write_text(render_findings(r), encoding="utf-8")
    summary = {"id": r["id"], "story": r["story"], "title": r["title"], "jira": r["jira"], "date": r["date"],
               "tests": len([t for t in r["tests"] if t["file"]]), "result": overall_result(r)}
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "README.md").write_text(render_index(out), encoding="utf-8")
    return folder


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--story-pr")
    ap.add_argument("--story-checks")
    ap.add_argument("--plan-pr")
    ap.add_argument("--pr-log")
    ap.add_argument("--main-log")
    ap.add_argument("--main-result", default="")
    ap.add_argument("--main-url", default="")
    ap.add_argument("--test-check", default="e2e", help="name of the PR's test check (default: e2e)")
    ap.add_argument("--out", default="test-reports")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args(argv)
    if not Path(args.plan).is_file():
        print(f"::error::plan {args.plan} not found", file=sys.stderr)
        return 1
    folder = write(collect(args), Path(args.root) / args.out)
    print(folder.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
