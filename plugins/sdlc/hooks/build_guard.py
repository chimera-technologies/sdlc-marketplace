#!/usr/bin/env python3
"""PreToolUse hook: no code before the Build preflight and a plan.

Active only in a repo with `.sdlc/build.yaml` (a product repo that has
opted in). A write under one of its `code_paths` (e.g. src/, tests/) is
blocked unless:
  1. the Graphify knowledge graph exists (graphify-out/graph.json), or the
     preflight found no code to index yet (graphify-out/NO-CODE-YET),
  2. Ponytail is enabled in .claude/settings.json and active this session,
  3. the current git branch is a story branch (story/<jira-key>-<name>, or
     story/<spec-slug>-s<n> without Jira),
  4. a plan for that story exists (plans/*.md whose `branch:` is this
     branch, or, for older plans, whose `jira:` is the branch's key).
Exit 2 blocks the write and tells Claude how to fix it. Everything else
passes. The build-story skill's preflight script sets up 1 and 2.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STORY_BRANCH_RE = re.compile(r"^story/[a-z0-9]+(?:-[a-z0-9]+)*$")
JIRA_BRANCH_RE = re.compile(r"^story/([a-z][a-z0-9]*-\d+)(?:-|$)")
_PREFLIGHT_PY = Path(__file__).resolve().parents[1] / "skills" / "build-story" / "scripts" / "build_preflight.py"
PREFLIGHT = f'python "{_PREFLIGHT_PY.as_posix()}"'


def load_build_config(project):
    """Parse .sdlc/build.yaml (flat `key: value` and `key: [a, b]`); None if absent."""
    path = Path(project) / ".sdlc" / "build.yaml"
    if not path.is_file():
        return None
    cfg = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line or line.startswith((" ", "\t")):
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            cfg[key.strip()] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            cfg[key.strip()] = val.strip("'\"")
    cfg.setdefault("code_paths", ["src/", "tests/"])
    return cfg


def no_code_marker(project):
    """Left by the preflight when there was no code to index (the first story)."""
    return Path(project) / "graphify-out" / "NO-CODE-YET"


def ponytail_flag():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / ".ponytail-active"


def ponytail_enabled(project):
    try:
        settings = json.loads((Path(project) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return settings.get("enabledPlugins", {}).get("ponytail@ponytail") is True


def current_branch(project):
    try:
        # --show-current also works before the first commit; detached HEAD gives "".
        out = subprocess.run(["git", "branch", "--show-current"], cwd=project,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None  # no git: the branch and plan checks cannot apply
    return out.stdout.strip() if out.returncode == 0 else None


def plan_for(project, branch):
    """The plan whose `branch:` is this branch (or, for older plans, whose `jira:` is its key)."""
    plans = Path(project) / "plans"
    if not plans.is_dir():
        return None
    m = JIRA_BRANCH_RE.match(branch)
    patterns = [rf"^branch:\s*['\"]?{re.escape(branch)}['\"]?\s*$"]
    if m:
        patterns.append(rf"^jira:\s*['\"]?{re.escape(m.group(1).upper())}['\"]?\s*$")
    for p in sorted(plans.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if any(re.search(pat, text, re.MULTILINE) for pat in patterns):
            return p
    return None


def check(project, rel):
    """Return a list of unmet requirements (empty = allowed)."""
    cfg = load_build_config(project)
    if cfg is None:
        return []
    prefixes = [c.strip("/") for c in cfg["code_paths"]]
    if not any(rel == p or rel.startswith(p + "/") for p in prefixes):
        return []
    problems = []
    graph = Path(project) / "graphify-out" / "graph.json"
    if not graph.is_file() and not no_code_marker(project).is_file():
        problems.append(f"No Graphify graph (graphify-out/graph.json). Run the preflight: {PREFLIGHT}")
    if not ponytail_enabled(project):
        problems.append(f"Ponytail is not enabled in .claude/settings.json. Run the preflight: {PREFLIGHT}")
    elif not ponytail_flag().is_file():
        problems.append("Ponytail is enabled but not active in this session: run `/plugin install ponytail@ponytail`, "
                        "then `/clear`, and start again with /sdlc:build-story.")
    branch = current_branch(project)
    if branch is not None:
        if not STORY_BRANCH_RE.match(branch):
            problems.append(f"Branch {branch!r} is not a story branch. Code is written on story/<jira-key>-<name> "
                            "(or story/<spec-slug>-s<n> without Jira), created by /sdlc:build-story after the "
                            "plan is approved.")
        elif plan_for(project, branch) is None:
            problems.append(f"No plan in plans/ for branch {branch!r}. Write and approve the plan first "
                            "(/sdlc:build-story Step 2).")
    return problems


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()).resolve()
    path = Path(file_path)
    if not path.is_absolute():
        path = project / path
    try:
        rel = path.resolve().relative_to(project).as_posix()
    except ValueError:
        return 0
    problems = check(project, rel)
    if not problems:
        return 0
    print(f"Blocked by the SDLC build guard: {rel} is code, and Build requirements are not met:", file=sys.stderr)
    for p in problems:
        print(f"- {p}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
