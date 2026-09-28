#!/usr/bin/env python3
"""PreToolUse hook: in headless runs, block file writes outside allowed paths.

Active only when SDLC_HEADLESS=1 (set by the SDLC workflows). Interactive
sessions are unaffected. Allowed path prefixes, relative to the project, come
from SDLC_WRITE_ALLOW (comma-separated): a folder prefix ("intent/") or one
exact file. Default "intent/,.sdlc-output/duplicate.txt".
Exit 2 blocks the tool call and tells Claude why.
"""
import json
import os
import sys
from pathlib import Path

DEFAULT_ALLOW = "intent/,.sdlc-output/duplicate.txt"


def main():
    if os.environ.get("SDLC_HEADLESS") != "1":
        return 0
    try:
        event = json.load(sys.stdin)
    except ValueError:
        print("headless write guard: unreadable hook input; blocking.", file=sys.stderr)
        return 2
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return 0

    allow = [p.strip().strip("/") for p in os.environ.get("SDLC_WRITE_ALLOW", DEFAULT_ALLOW).split(",") if p.strip()]
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()).resolve()
    path = Path(file_path)
    if not path.is_absolute():
        path = project / path
    path = path.resolve()
    try:
        rel = path.relative_to(project).as_posix()
    except ValueError:
        rel = None
    if rel and any(rel == a or rel.startswith(a + "/") for a in allow):
        return 0
    shown = rel or str(path)
    print(
        f"Blocked: headless SDLC runs may only write to {', '.join(allow)}; "
        f"'{shown}' is outside that. Write your output to an allowed path instead.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
