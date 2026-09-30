#!/usr/bin/env python3
"""Decide the next Build step for every accepted spec (automatic Build).

Deterministic, standard library only. The sdlc-build workflow runs it on
every push to the base branch. State comes only from git and the PR list
(open PR = proposed, merged = accepted, closed = rejected); nothing is
written to the specs or plans.

  gh pr list --state all --limit 1000 --json headRefName,state > prs.json
  python next_story.py --prs prs.json [--spec specs/<slug>.md]

For each spec, its stories are built one at a time, in order. For the first
story that is not done:
  - no plan in plans/ and no plan PR   -> "plan": open a plan PR (plan/<id>)
  - plan PR open                       -> wait for the owner to merge it
  - plan merged, no story PR           -> "build": build it (story PR on the
                                          plan's branch)
  - story PR open                      -> wait for review and merge
  - a plan or story PR closed unmerged -> wait: someone rejected it; re-run
                                          by hand (/sdlc:build-story)
A story is done when a PR from its plan's branch is merged. Nothing moves
while .sdlc/build.yaml has no test_command (record the stack first), or
while a story PR is open that no plan on the base branch explains (a
manual build in progress).

Prints JSON: {"actions": [...], "waiting": [...]}.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_VP_PATH = Path(__file__).resolve().parent / "validate_plan.py"
_spec = importlib.util.spec_from_file_location("validate_plan", _VP_PATH)
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)
vs, vi, bg = vp.vs, vp.vi, vp.bg


def pr_states(prs):
    """{head branch: set of states} from `gh pr list --json headRefName,state`."""
    out = {}
    for pr in prs:
        out.setdefault(pr.get("headRefName", ""), set()).add((pr.get("state") or "").upper())
    return out


def plan_branch(plan_path):
    fm, _ = vi.parse_frontmatter(Path(plan_path).read_text(encoding="utf-8"))
    return (fm or {}).get("branch", "")


def decide(root, prs, only_spec=None):
    root = Path(root)
    states = pr_states(prs)
    actions, waiting = [], []
    cfg = bg.load_build_config(root) or {}
    specs = sorted((root / "specs").glob("*.md")) if (root / "specs").is_dir() else []
    if only_spec:
        specs = [root / only_spec]
    known = {plan_branch(p) for p in (root / "plans").glob("*.md")} if (root / "plans").is_dir() else set()
    untracked = sorted(b for b, s in states.items() if b.startswith("story/") and "OPEN" in s and b not in known)

    for spec in specs:
        if not vi.SLUG_RE.match(spec.stem) or not spec.is_file():
            continue  # not a spec file name the loop can use in branches and paths
        rel = spec.relative_to(root).as_posix()
        _, body = vi.parse_frontmatter(spec.read_text(encoding="utf-8"))
        stories = vs.parse_stories(body or "")
        if not stories:
            continue
        if not cfg.get("test_command"):
            waiting.append({"spec": rel, "reason": "no test_command in .sdlc/build.yaml: record the stack "
                                                   f"with /sdlc:init stack={rel}"})
            continue
        if untracked:
            waiting.append({"spec": rel, "reason": f"story PR open without a plan on the base branch "
                                                   f"({', '.join(untracked)}): a manual build is in progress"})
            continue
        slug = spec.stem
        for story in stories:
            sid = f"{slug}-{story['id'].lower()}"
            item = {"spec": rel, "slug": slug, "story": story["id"], "title": story["title"], "id": sid}
            plan = root / "plans" / f"{sid}.md"
            if plan.is_file():
                branch = plan_branch(plan)
                got = states.get(branch, set())
                if "MERGED" in got:
                    continue  # done
                if "OPEN" in got:
                    waiting.append({**item, "reason": f"story PR open ({branch})"})
                elif "CLOSED" in got:
                    waiting.append({**item, "reason": f"story PR closed without merge ({branch}); "
                                                      f"rebuild with /sdlc:build-story {story['id']}"})
                else:
                    actions.append({**item, "action": "build", "plan": plan.relative_to(root).as_posix(),
                                    "branch": branch})
                break
            got = states.get(f"plan/{sid}", set())
            if "OPEN" in got:
                waiting.append({**item, "reason": f"plan PR open (plan/{sid})"})
            elif "CLOSED" in got and "MERGED" not in got:
                waiting.append({**item, "reason": f"plan PR closed without merge (plan/{sid}); "
                                                  f"plan it with /sdlc:build-story {story['id']}"})
            else:
                actions.append({**item, "action": "plan"})
            break
    return {"actions": actions, "waiting": waiting}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--prs", required=True, help="JSON from gh pr list --json headRefName,state")
    ap.add_argument("--spec", help="only this spec (specs/<slug>.md)")
    args = ap.parse_args()
    if args.spec and not re.match(r"^specs/[a-z0-9]+(-[a-z0-9]+)*\.md$", args.spec):
        print("--spec must look like specs/<slug>.md", file=sys.stderr)
        return 1
    prs = json.loads(Path(args.prs).read_text(encoding="utf-8") or "[]")
    print(json.dumps(decide(args.root, prs, args.spec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
