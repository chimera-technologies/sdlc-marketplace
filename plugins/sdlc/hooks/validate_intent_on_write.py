#!/usr/bin/env python3
"""PostToolUse hook: validate intent/*.md every time Claude writes one.

The write-intent skill already tells Claude to run the validator; this hook
makes it hold even when the skill's advice is skipped. On failure it exits 2
so the validator's errors go back to Claude to fix. Other files are ignored.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE.parent / "skills" / "write-intent" / "scripts" / "validate_intent.py"


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()).resolve()
    path = Path(file_path)
    if not path.is_absolute():
        path = project / path
    path = path.resolve()
    try:
        rel = path.relative_to(project)
    except ValueError:
        return 0
    if len(rel.parts) != 2 or rel.parts[0] != "intent" or rel.suffix != ".md" or not path.is_file():
        return 0

    cmd = [sys.executable, str(VALIDATOR), str(path)]
    owners = project / ".sdlc" / "owners.yaml"
    if owners.is_file():
        cmd[2:2] = ["--owners", str(owners)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return 0
    print(f"{rel.as_posix()} does not pass validate_intent.py. Fix every error below:", file=sys.stderr)
    print(proc.stderr.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
