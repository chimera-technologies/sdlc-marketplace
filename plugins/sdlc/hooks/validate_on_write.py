#!/usr/bin/env python3
"""PostToolUse hook: validate intent/*.md and specs/*.md every time Claude
writes one.

The skills already tell Claude to run their validator; this hook makes it
hold even when the skill's advice is skipped. On failure it exits 2 so the
validator's errors go back to Claude to fix. Other files are ignored.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent / "skills"
VALIDATORS = {
    "intent": SKILLS / "write-intent" / "scripts" / "validate_intent.py",
    "specs": SKILLS / "write-spec" / "scripts" / "validate_spec.py",
}


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
    if len(rel.parts) != 2 or rel.parts[0] not in VALIDATORS or rel.suffix != ".md" or not path.is_file():
        return 0

    cmd = [sys.executable, str(VALIDATORS[rel.parts[0]])]
    owners = project / ".sdlc" / "owners.yaml"
    if owners.is_file():
        cmd += ["--owners", str(owners)]
    cmd.append(str(path))
    # Run from the project root so a spec can find the intent it names.
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=project)
    if proc.returncode == 0:
        return 0
    print(f"{rel.as_posix()} does not pass {VALIDATORS[rel.parts[0]].name}. Fix every error below:", file=sys.stderr)
    print(proc.stderr.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
