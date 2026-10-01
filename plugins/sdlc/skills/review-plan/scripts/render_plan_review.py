#!/usr/bin/env python3
"""Render .sdlc-output/plan-review.json (sdlc:review-plan) as markdown for a plan PR.

Deterministic, standard library only. Used by the sdlc-build workflow.

  render_plan_review.py .sdlc-output/plan-review.json --markdown out.md \
      [--must-fix must-fix.json] [--low low.txt]

Prints the verdict (clean, concerns, blocking, or failed when the review did
not run or wrote something unusable) and writes the markdown section.

Findings are numbered: edge cases EC-1.., bugs BUG-1.. (critical first).
Every edge case and every critical or high bug **must be fixed** in the
story: --must-fix writes them as [{"id", "kind", "severity", "text"}] for
the planner to add to the plan's Review findings section (validate_plan.py
--review checks it). Low bugs need no fix: --low writes them as a short text
for the Jira story. Exit 0 always.
"""
import argparse
import json
import sys
from pathlib import Path

SEVERITIES = ["critical", "high", "low"]
ICON = {"critical": "🔴", "high": "🟠", "low": "⚪"}


def load(path):
    """(review dict, None) or (None, reason)."""
    p = Path(path)
    if not p.is_file():
        return None, "the reviewer wrote no output"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        return None, f"output is not JSON ({e})"
    if not isinstance(data, dict):
        return None, "output is not a JSON object"
    for key in ("edge_cases", "bugs"):
        if not isinstance(data.get(key, []), list):
            return None, f"'{key}' is not a list"
    for b in data.get("bugs", []):
        if not isinstance(b, dict) or b.get("severity") not in SEVERITIES:
            return None, f"bug severity must be one of {SEVERITIES}"
    return data, None


def verdict(data):
    bugs = data.get("bugs", [])
    if any(b["severity"] == "critical" for b in bugs):
        return "blocking"
    if any(b["severity"] == "high" for b in bugs) or data.get("edge_cases"):
        return "concerns"
    return "clean"


def cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def numbered(data):
    """(edge cases, bugs) with ids: EC-1.. in review order, BUG-1.. critical first."""
    edges = [{**e, "id": f"EC-{i}"} for i, e in enumerate(data.get("edge_cases", []), 1)]
    bugs = sorted(data.get("bugs", []), key=lambda b: SEVERITIES.index(b["severity"]))
    return edges, [{**b, "id": f"BUG-{i}"} for i, b in enumerate(bugs, 1)]


def must_fix(data):
    """Everything the story must fix: every edge case, every critical or high bug."""
    edges, bugs = numbered(data)
    out = [{"id": e["id"], "kind": "edge case", "severity": "", "text": f"{e.get('case')}: {e.get('why')} (suggestion: {e.get('suggestion')})"}
           for e in edges]
    out += [{"id": b["id"], "kind": "bug", "severity": b["severity"],
             "text": f"{b.get('title')} ({b.get('where')}): {b.get('scenario')} (suggestion: {b.get('suggestion')})"}
            for b in bugs if b["severity"] in ("critical", "high")]
    return out


def low_text(data):
    """The low bugs as a plain-text note for the Jira story, or '' if none."""
    lows = [b for b in numbered(data)[1] if b["severity"] == "low"]
    if not lows:
        return ""
    lines = ["Low-severity findings from the plan review (not required to fix):"]
    lines += [f"- {b['id']} {b.get('title')} ({b.get('where')}): {b.get('scenario')} Suggestion: {b.get('suggestion')}"
              for b in lows]
    return "\n".join(lines)


def render(data, reason=None):
    if data is None:
        return ("### Plan review: ⚠️ did not run\n\n"
                f"The edge-case and bug review could not be read ({reason}). Review the plan by hand, "
                "or re-run it: `/sdlc:review-plan plan=<this plan>`.\n")
    v = verdict(data)
    edges, bugs = numbered(data)
    fix = must_fix(data)
    counts = " · ".join(f"{sum(b['severity'] == s for b in bugs)} {s}" for s in SEVERITIES)
    head = {"clean": "✅ clean", "concerns": "⚠️ concerns", "blocking": "🔴 blocking"}[v]
    out = [f"### Plan review: {head}", "", cell(data.get("summary")), "",
           f"Potential bugs: {counts}. Missed edge cases: {len(edges)}.", ""]
    if fix:
        out += [f"**Must be fixed in this story ({len(fix)}):** {', '.join(f['id'] for f in fix)}: every edge case and "
                "every critical or high bug. The plan's **Review findings** section says how each is handled and "
                "names its test; the story PR's traceability check requires those tests. Low bugs are optional "
                "and go to the Jira story as a comment.", ""]
    if v == "blocking":
        out += ["> [!CAUTION]", "> A **critical** bug: this plan PR is a draft. Check that the revised plan "
                "really fixes it, then mark it ready for review.", ""]
    if edges:
        out += ["#### Missed edge cases (must fix)", "", "| ID | Case | What goes wrong | Suggestion |", "|---|---|---|---|"]
        out += [f"| {e['id']} | {cell(e.get('case'))} | {cell(e.get('why'))} | {cell(e.get('suggestion'))} |" for e in edges]
        out.append("")
    if bugs:
        out += ["#### Potential bugs (critical and high must fix; low optional)", "",
                "| ID | Severity | Bug | Where | Scenario | Suggestion |", "|---|---|---|---|---|---|"]
        out += [f"| {b['id']} | {ICON[b['severity']]} {b['severity']} | {cell(b.get('title'))} | {cell(b.get('where'))} | "
                f"{cell(b.get('scenario'))} | {cell(b.get('suggestion'))} |" for b in bugs]
        out.append("")
    out.append("_The review flags; it does not approve. The build follows the plan as merged._")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review")
    ap.add_argument("--markdown", required=True, help="where to write the markdown section")
    ap.add_argument("--must-fix", help="where to write the must-fix findings as JSON")
    ap.add_argument("--low", help="where to write the low bugs as text for the Jira story")
    args = ap.parse_args()
    data, reason = load(args.review)
    Path(args.markdown).write_text(render(data, reason), encoding="utf-8")
    if args.must_fix:
        Path(args.must_fix).write_text(json.dumps(must_fix(data) if data else [], indent=2) + "\n", encoding="utf-8")
    if args.low:
        Path(args.low).write_text(low_text(data) if data else "", encoding="utf-8")
    print("failed" if data is None else verdict(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
