#!/usr/bin/env python3
"""Render .sdlc-output/plan-review.json (sdlc:review-plan) as markdown for a plan PR.

Deterministic, standard library only. Used by the sdlc-build workflow.

  render_plan_review.py .sdlc-output/plan-review.json --markdown out.md

Prints the verdict (clean, concerns, blocking, or failed when the review did
not run or wrote something unusable) and writes the markdown section.
Exit 0 always: the review informs the owner; a critical bug makes the
workflow open the plan PR as a draft.
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


def render(data, reason=None):
    if data is None:
        return ("### Plan review: ⚠️ did not run\n\n"
                f"The edge-case and bug review could not be read ({reason}). Review the plan by hand, "
                "or re-run it: `/sdlc:review-plan plan=<this plan>`.\n")
    v = verdict(data)
    bugs = sorted(data.get("bugs", []), key=lambda b: SEVERITIES.index(b["severity"]))
    edges = data.get("edge_cases", [])
    counts = " · ".join(f"{sum(b['severity'] == s for b in bugs)} {s}" for s in SEVERITIES)
    head = {"clean": "✅ clean", "concerns": "⚠️ concerns", "blocking": "🔴 blocking"}[v]
    out = [f"### Plan review: {head}", "", cell(data.get("summary")), "",
           f"Potential bugs: {counts}. Missed edge cases: {len(edges)}.", ""]
    if v == "blocking":
        out += ["> [!CAUTION]", "> A **critical** bug: this plan PR is a draft. Fix the plan on this branch, "
                "then mark it ready for review.", ""]
    if edges:
        out += ["#### Missed edge cases", "", "| Case | What goes wrong | Suggestion |", "|---|---|---|"]
        out += [f"| {cell(e.get('case'))} | {cell(e.get('why'))} | {cell(e.get('suggestion'))} |" for e in edges]
        out.append("")
    if bugs:
        out += ["#### Potential bugs", "", "| Severity | Bug | Where | Scenario | Suggestion |", "|---|---|---|---|---|"]
        out += [f"| {ICON[b['severity']]} {b['severity']} | {cell(b.get('title'))} | {cell(b.get('where'))} | "
                f"{cell(b.get('scenario'))} | {cell(b.get('suggestion'))} |" for b in bugs]
        out.append("")
    out.append("_The review flags; it does not approve. Add what you accept to the plan before merging: "
               "the build follows the plan as merged._")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review")
    ap.add_argument("--markdown", required=True, help="where to write the markdown section")
    args = ap.parse_args()
    data, reason = load(args.review)
    Path(args.markdown).write_text(render(data, reason), encoding="utf-8")
    print("failed" if data is None else verdict(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
