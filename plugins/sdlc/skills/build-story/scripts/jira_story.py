#!/usr/bin/env python3
"""Keep a Jira story's status and comments in step with the SDLC stages.

Deterministic, standard library only. Called by the workflows as a story
moves through the stages (the story-link workflow moves it to Done on merge):

  jira_story.py <KEY> comment "<text>"
  jira_story.py <KEY> move planning        # plan PR opened (sdlc-build)
  jira_story.py <KEY> move in-progress     # build started (sdlc-build)
  jira_story.py <KEY> move dev-complete    # story PR opened, build PASS (sdlc-build)
  jira_story.py <KEY> move in-qa           # the PR's tests started (sdlc-pr)
  jira_story.py <KEY> move in-review       # tests and review gate passed (sdlc-pr)
  jira_story.py <KEY> move in-progress --back   # a check failed, or the reviewer asked for a fix

Needs JIRA_BASE_URL, JIRA_USER_EMAIL and JIRA_API_TOKEN in the environment.
The status name of each stage comes from .sdlc/jira.yaml (--config), else
the default: status_planning "In Planning", status_in_progress "In
Progress", status_dev_complete "Dev Completed", status_in_qa "In QA",
status_in_review "In Review", status_done "Done". A transition into a status
with that name is taken. Without one, in-progress takes any transition into
the in-progress category (preferring one named like "progress"), in-review
one into a status named like "review"; other stages say so and change
nothing, so a board without the status keeps working.

A story moves forward only: a Done story, or one already at or past the
stage, is left alone. --back allows a move backwards (never out of Done).

Exit 0 = done or nothing to do, 1 = Jira error.
"""
import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

_SS_PATH = Path(__file__).resolve().parents[2] / "write-spec" / "scripts" / "spec_stories.py"
_spec = importlib.util.spec_from_file_location("spec_stories", _SS_PATH)
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
REVIEW_RE = re.compile(r"review", re.I)
PROGRESS_RE = re.compile(r"progress", re.I)

STAGES = ["planning", "in-progress", "dev-complete", "in-qa", "in-review", "done"]
DEFAULT_NAMES = {"planning": "In Planning", "in-progress": "In Progress", "dev-complete": "Dev Completed",
                 "in-qa": "In QA", "in-review": "In Review", "done": "Done"}


def status_names(cfg=None):
    """{stage: status name} from .sdlc/jira.yaml keys status_<stage>, else the defaults."""
    cfg = cfg or {}
    return {s: cfg.get("status_" + s.replace("-", "_")) or DEFAULT_NAMES[s] for s in STAGES}


def status(jira, key):
    fields = jira.call("GET", f"/rest/api/2/issue/{key}?fields=status")["fields"]["status"]
    return fields["name"], fields["statusCategory"]["key"]


def stage_of(name, category, names):
    """The stage a status name stands for, or None."""
    for s in STAGES:
        if names[s].lower() == name.lower():
            return s
    return "done" if category == "done" else None


def pick(transitions, target, names=None):
    """The transition id for the target stage, or None."""
    names = names or DEFAULT_NAMES
    exact = [t for t in transitions if t["to"]["name"].lower() == names[target].lower()]
    if exact:
        return exact[0]["id"]
    if target == "in-progress":
        into = [t for t in transitions if t["to"]["statusCategory"]["key"] == "indeterminate"]
        named = [t for t in into if PROGRESS_RE.search(t["to"]["name"]) or PROGRESS_RE.search(t["name"])]
        chosen = (named or into)[:1]
    elif target == "in-review":
        chosen = [t for t in transitions if REVIEW_RE.search(t["to"]["name"])][:1]
    elif target == "done":
        chosen = [t for t in transitions if t["to"]["statusCategory"]["key"] == "done"][:1]
    else:
        chosen = []
    return chosen[0]["id"] if chosen else None


def move(jira, key, target, names=None, back=False):
    names = names or DEFAULT_NAMES
    name, category = status(jira, key)
    if category == "done":
        return f"{key} is {name} (done); left alone"
    current = stage_of(name, category, names)
    if current == target:
        return f"{key} is already {name}"
    if not back:
        if current is not None and STAGES.index(current) > STAGES.index(target):
            return f"{key} is {name}, past {names[target]}; left alone"
        if target == "in-progress" and current is None and category == "indeterminate":
            return f"{key} is already {name}"
        if target == "in-review" and REVIEW_RE.search(name):
            return f"{key} is already {name}"
    transitions = jira.call("GET", f"/rest/api/2/issue/{key}/transitions").get("transitions") or []
    tid = pick(transitions, target, names)
    if tid is None:
        return (f"{key}: the workflow has no transition to \"{names[target]}\" from {name}; left as {name} "
                f"(add the status to the Jira workflow, or name it in .sdlc/jira.yaml status_{target.replace('-', '_')})")
    jira.call("POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": tid}})
    new = next(t["to"]["name"] for t in transitions if t["id"] == tid)
    return f"{key}: {name} -> {new}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key")
    ap.add_argument("--config", default=".sdlc/jira.yaml", help="status names (status_<stage>); defaults if absent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("comment")
    c.add_argument("text")
    m = sub.add_parser("move")
    m.add_argument("target", choices=STAGES)
    m.add_argument("--back", action="store_true", help="allow a move backwards (a check failed, a fix was asked for)")
    args = ap.parse_args()
    if not KEY_RE.match(args.key):
        print(f"not a Jira key: {args.key!r}", file=sys.stderr)
        return 1
    env = {k: os.environ.get(k, "") for k in ("JIRA_BASE_URL", "JIRA_USER_EMAIL", "JIRA_API_TOKEN")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        print(f"Jira not configured ({', '.join(missing)} missing); skipping.")
        return 0
    jira = ss.Jira(env["JIRA_BASE_URL"], env["JIRA_USER_EMAIL"], env["JIRA_API_TOKEN"])
    try:
        if args.cmd == "comment":
            jira.call("POST", f"/rest/api/2/issue/{args.key}/comment", {"body": args.text})
            print(f"{args.key}: commented")
        else:
            print(move(jira, args.key, args.target, status_names(ss.load_jira_config(args.config)), args.back))
    except SystemExit as e:
        print(f"::warning::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
