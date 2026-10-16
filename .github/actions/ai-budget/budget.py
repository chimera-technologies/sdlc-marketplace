#!/usr/bin/env python3
"""AI spend limits for the sdlc workflows (the ai-budget action).

Two modes, run around every headless Claude step:

  budget.py check --stage build
      Before the step. Prints the step output `flag`: `--max-budget-usd <n>`,
      the per-run cap for the stage, or empty for none. Fails (exit 1) when
      the project has spent its monthly limit, so the AI step never starts;
      warns once at 80%.
  budget.py record --stage build --transcript "<glob>"
      After the step (always). Adds the run's cost (total_cost_usd, the last
      line of each stream-json transcript) to this month's ledger.

Limits come from `budgets` in .sdlc/sdlc.json:

  "budgets": {"per_run_usd": {"build": 20, "review": 10}, "monthly_usd": 300}

A stage missing from per_run_usd uses DEFAULT_PER_RUN; 0 means no cap.
monthly_usd 0 or missing means no monthly limit.

The ledger is one issue per month, labelled sdlc-spend, whose body holds
the running totals (by stage) as JSON in an HTML comment. It needs a token
with Issues write (the sdlc-bot App) in GH_TOKEN, and the gh CLI. Two runs
that finish at once can lose one update: the monthly limit is soft. The hard
ceiling is the spend limit of the Anthropic Console workspace the API key
belongs to.

Standard library only.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LABEL = "sdlc-spend"
STATE_RE = re.compile(r"<!-- sdlc-spend (\{.*?\}) -->", re.S)
# About 5-10 times what a normal run costs, so only a runaway run is stopped.
DEFAULT_PER_RUN = {
    "intake": 5, "requirements": 15, "spec": 10, "review-spec": 10, "design": 10, "stack": 5,
    "plan": 10, "review-plan": 15, "plan-revise": 10, "build": 30, "review": 10, "advisory": 5,
    "revise": 10, "prescreen": 10, "autofix": 20, "review-fix": 20,
}
WARN_AT = 0.8


def load_budgets(root="."):
    try:
        cfg = json.loads((Path(root) / ".sdlc" / "sdlc.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    b = cfg.get("budgets") or {}
    per_run = {**DEFAULT_PER_RUN, **(b.get("per_run_usd") or {})}
    return per_run, float(b.get("monthly_usd") or 0)


def per_run_flag(stage, per_run):
    cap = float(per_run.get(stage, 0) or 0)
    return f"--max-budget-usd {cap:g}" if cap > 0 else ""


def transcript_cost(paths):
    """Sum total_cost_usd from the last result line of each stream-json transcript."""
    total = 0.0
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            whole = json.loads(text)   # claude-code-action's execution file: one JSON array
        except ValueError:
            whole = None
        lines = [json.dumps(e) for e in whole] if isinstance(whole, list) else [l for l in text.splitlines() if l.strip()]
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and "total_cost_usd" in event:
                total += float(event.get("total_cost_usd") or 0)
                break
    return round(total, 4)


def month(today=None):
    return (today or dt.date.today()).strftime("%Y-%m")


def parse_state(body, this_month):
    m = STATE_RE.search(body or "")
    state = json.loads(m.group(1)) if m else {}
    if state.get("month") != this_month:
        state = {"month": this_month, "total": 0.0, "runs": 0, "stages": {}, "warned": False, "blocked": False}
    return state


def render(state, monthly):
    rows = "\n".join(f"| {k} | ${v:.2f} |" for k, v in sorted(state["stages"].items(), key=lambda kv: -kv[1]))
    limit = f"${monthly:.2f}" if monthly else "none"
    return (f"AI spend of the SDLC workflows in {state['month']} (updated after every run).\n\n"
            f"**Total: ${state['total']:.2f}** of {limit} monthly limit, {state['runs']} runs.\n\n"
            f"| Stage | Spend |\n|---|---|\n{rows}\n\n"
            "The limit is `budgets.monthly_usd` in `.sdlc/sdlc.json`. With a subscription token the figures are what "
            "the runs would cost at API prices.\n\n"
            f"<!-- sdlc-spend {json.dumps(state, sort_keys=True)} -->\n")


def apply_record(state, stage, cost):
    state["total"] = round(state["total"] + cost, 4)
    state["runs"] += 1
    state["stages"][stage] = round(state["stages"].get(stage, 0) + cost, 4)
    return state


def verdict(state, monthly):
    """'blocked', 'warn' (first time past 80%), or 'ok'."""
    if monthly <= 0:
        return "ok"
    if state["total"] >= monthly:
        return "blocked"
    if state["total"] >= WARN_AT * monthly and not state.get("warned"):
        return "warn"
    return "ok"


# ------------------------------------------------------------ the ledger issue

def gh(*args):
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip()[:300])
    return res.stdout


def find_issue(this_month):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    out = gh("issue", "list", "-R", repo, "--label", LABEL, "--state", "all", "--limit", "20",
             "--json", "number,title,body")
    for issue in json.loads(out or "[]"):
        if issue["title"].endswith(this_month):
            return issue
    return None


def save(issue, state, monthly):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    body = render(state, monthly)
    if issue:
        gh("issue", "edit", str(issue["number"]), "-R", repo, "--body", body)
        return issue["number"]
    subprocess.run(["gh", "label", "create", LABEL, "-R", repo, "--color", "C5DEF5",
                    "--description", "Monthly AI spend of the SDLC workflows"], capture_output=True)
    out = gh("issue", "create", "-R", repo, "--title", f"SDLC AI spend {state['month']}", "--label", LABEL, "--body", body)
    return out.strip().rsplit("/", 1)[-1]


def comment(number, text):
    gh("issue", "comment", str(number), "-R", os.environ.get("GITHUB_REPOSITORY", ""), "--body", text)


def write_output(name, value):
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["check", "record"])
    ap.add_argument("--stage", required=True)
    ap.add_argument("--transcript", default="", help="record: glob of the step's stream-json transcripts")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    per_run, monthly = load_budgets(args.root)
    this_month = month()

    if args.mode == "check":
        write_output("flag", per_run_flag(args.stage, per_run))
        if monthly <= 0:
            return 0
        try:
            issue = find_issue(this_month)
        except RuntimeError as e:
            print(f"::warning::AI budget: could not read the spend ledger ({e}); not enforcing the monthly limit.")
            return 0
        state = parse_state(issue and issue.get("body"), this_month)
        v = verdict(state, monthly)
        if v == "blocked":
            if issue and not state.get("blocked"):
                state["blocked"] = True
                save(issue, state, monthly)
                comment(issue["number"], f"Monthly AI limit reached (${state['total']:.2f} of ${monthly:.2f}). "
                                         "AI steps stop until next month or until `budgets.monthly_usd` is raised.")
            print(f"::error::Monthly AI budget reached: ${state['total']:.2f} of ${monthly:.2f} in {this_month}. "
                  f"The {args.stage} step does not run. Raise budgets.monthly_usd in .sdlc/sdlc.json to continue.")
            return 1
        if v == "warn" and issue:
            state["warned"] = True
            save(issue, state, monthly)
            comment(issue["number"], f"80% of the monthly AI limit used (${state['total']:.2f} of ${monthly:.2f}).")
        return 0

    paths = sorted({p for pattern in args.transcript.split() for p in glob.glob(pattern)})
    cost = transcript_cost(paths)
    print(f"AI spend: {args.stage} ${cost:.4f} ({len(paths)} transcript(s))")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"AI spend, {args.stage}: ${cost:.4f}\n")
    if cost <= 0:
        return 0
    try:
        issue = find_issue(this_month)
        state = apply_record(parse_state(issue and issue.get("body"), this_month), args.stage, cost)
        save(issue, state, monthly)
    except RuntimeError as e:
        print(f"::warning::AI budget: could not update the spend ledger ({e}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
