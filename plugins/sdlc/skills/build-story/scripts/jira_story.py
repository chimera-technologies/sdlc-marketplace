#!/usr/bin/env python3
"""Keep a Jira story's status and comments in step with automatic Build.

Deterministic, standard library only. The sdlc-build workflow calls it when
a plan PR opens, when the build starts, and when the story PR opens (the
story-link workflow moves it to Done on merge).

  jira_story.py <KEY> comment "<text>"
  jira_story.py <KEY> move in-progress     # build started
  jira_story.py <KEY> move in-review       # story PR opened

Needs JIRA_BASE_URL, JIRA_USER_EMAIL and JIRA_API_TOKEN in the environment.
Works with any Jira workflow: "in-progress" takes a transition into the
in-progress status category (preferring one named like "progress"),
"in-review" a transition into a status named like "review". A story never
moves backwards: a Done story, or one already past the target, is left
alone. If the workflow has no matching transition, it says so and changes
nothing.

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


def status(jira, key):
    fields = jira.call("GET", f"/rest/api/2/issue/{key}?fields=status")["fields"]["status"]
    return fields["name"], fields["statusCategory"]["key"]


def pick(transitions, target):
    """The transition id for the target, or None."""
    if target == "in-progress":
        into = [t for t in transitions if t["to"]["statusCategory"]["key"] == "indeterminate"]
        named = [t for t in into if PROGRESS_RE.search(t["to"]["name"]) or PROGRESS_RE.search(t["name"])]
        chosen = (named or into)[:1]
    else:
        chosen = [t for t in transitions if REVIEW_RE.search(t["to"]["name"])][:1]
    return chosen[0]["id"] if chosen else None


def move(jira, key, target):
    name, category = status(jira, key)
    if category == "done":
        return f"{key} is {name} (done); left alone"
    if target == "in-progress" and category == "indeterminate":
        return f"{key} is already {name}"
    if target == "in-review" and REVIEW_RE.search(name):
        return f"{key} is already {name}"
    transitions = jira.call("GET", f"/rest/api/2/issue/{key}/transitions").get("transitions") or []
    tid = pick(transitions, target)
    if tid is None:
        return f"{key}: the workflow has no {target} transition from {name}; left as {name}"
    jira.call("POST", f"/rest/api/2/issue/{key}/transitions", {"transition": {"id": tid}})
    new = next(t["to"]["name"] for t in transitions if t["id"] == tid)
    return f"{key}: {name} -> {new}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("comment")
    c.add_argument("text")
    m = sub.add_parser("move")
    m.add_argument("target", choices=["in-progress", "in-review"])
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
            print(move(jira, args.key, args.target))
    except SystemExit as e:
        print(f"::warning::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
