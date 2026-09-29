#!/usr/bin/env python3
"""Turn .sdlc-output/spec-review.json into PR markdown and a verdict.

Deterministic, standard library only. A missing or malformed review never
fails the workflow: it becomes verdict "failed" so a human knows the
pre-screen did not run.

Usage:
  render_review.py .sdlc-output/spec-review.json --markdown review.md
Prints the verdict (clean | concerns | failed) on stdout.
"""
import argparse
import json
import sys
from pathlib import Path

SEVERITIES = ["high", "medium", "low"]
ICON = {"high": "🔴", "medium": "🟠", "low": "⚪"}


def load(path):
    """Return (review dict, problem string or None)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "the reviewer did not write a review file"
    except ValueError as e:
        return None, f"the review file is not valid JSON ({e})"
    if not isinstance(data, dict) or not isinstance(data.get("findings", []), list):
        return None, "the review file does not have the expected shape"
    findings = []
    for f in data.get("findings", []):
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "low")).lower()
        findings.append({
            "severity": sev if sev in SEVERITIES else "low",
            "section": str(f.get("section", "")).strip() or "General",
            "issue": str(f.get("issue", "")).strip(),
            "evidence": str(f.get("evidence", "")).strip(),
            "suggestion": str(f.get("suggestion", "")).strip(),
        })
    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    # The verdict is derived from the findings, not trusted from the model.
    verdict = "concerns" if any(f["severity"] in ("high", "medium") for f in findings) else "clean"
    return {"verdict": verdict, "summary": str(data.get("summary", "")).strip(), "findings": findings}, None


def render(review, problem):
    if problem:
        return ("### Adversarial pre-screen: ⚠️ did not complete\n\n"
                f"{problem}. Review this spec without the pre-screen, or re-run the workflow.\n"), "failed"
    counts = {s: sum(f["severity"] == s for f in review["findings"]) for s in SEVERITIES}
    head = "✅ clean" if review["verdict"] == "clean" else "⚠️ concerns"
    lines = [f"### Adversarial pre-screen: {head}", ""]
    if review["summary"]:
        lines += [review["summary"], ""]
    lines += [f"{counts['high']} high · {counts['medium']} medium · {counts['low']} low. "
              "The pre-screen flags; it does not approve. The owner decides.", ""]
    for i, f in enumerate(review["findings"], 1):
        lines.append(f"{i}. {ICON[f['severity']]} **{f['severity']}**, *{f['section']}*: {f['issue']}")
        if f["evidence"]:
            lines.append(f"   - Evidence: {f['evidence']}")
        if f["suggestion"]:
            lines.append(f"   - Suggestion: {f['suggestion']}")
    return "\n".join(lines) + "\n", review["verdict"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review")
    ap.add_argument("--markdown", required=True, help="write the PR markdown here")
    args = ap.parse_args()
    review, problem = load(args.review)
    md, verdict = render(review, problem)
    Path(args.markdown).write_text(md, encoding="utf-8")
    print(verdict)


if __name__ == "__main__":
    sys.exit(main())
