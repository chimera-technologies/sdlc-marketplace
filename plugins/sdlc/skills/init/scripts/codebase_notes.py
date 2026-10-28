#!/usr/bin/env python3
"""The codebase notes Build reads in an existing project: PATTERNS.md (how
this codebase does things) and the Architecture section of CLAUDE.md (what
is where). `/sdlc:init learn` writes them from the code; this script tells
whether they are needed and checks them. Standard library only.

  codebase_notes.py status [--root .]
      JSON: has_code (source files outside the SDLC's own folders),
      patterns ("missing", "template", "partial" or "filled"),
      architecture (true when CLAUDE.md has one outside the sdlc block).

  codebase_notes.py check [--root .]
      Exit 0 when both are written: every PATTERNS.md section has an entry
      citing a file that exists, or says why it does not apply ("None: ...",
      "Not used: ..."); CLAUDE.md has a "## Architecture" section, outside
      the regenerated sdlc block, with at least three points and two files
      that exist. Every cited path must exist (a made-up path is an error).
      Exit 1 with the errors otherwise.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

PATTERN_SECTIONS = ["Project structure", "Errors and validation", "Data access and external calls",
                    "UI components", "State and configuration", "Testing"]
BEGIN, END = "<!-- sdlc:begin -->", "<!-- sdlc:end -->"
NOT_APPLICABLE_RE = re.compile(r"^\s*[-*]?\s*\**(none|not used|not applicable|n/a)\b", re.I | re.M)
CODE_RE = re.compile(r"`([^`\n]+)`")
PATHLIKE_RE = re.compile(r"^[\w.@*-][\w./@*-]*(?::\d+(?:-\d+)?)?$")
SOURCE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".kts", ".scala", ".cs", ".fs",
               ".vb", ".go", ".rb", ".php", ".rs", ".swift", ".m", ".c", ".h", ".cc", ".cpp", ".hpp", ".vue",
               ".svelte", ".dart", ".ex", ".exs", ".erl", ".clj", ".lua", ".pl", ".r", ".sql", ".sh", ".ps1"}
SKIP_DIRS = {".git", ".github", ".claude", ".sdlc", ".sdlc-plugin", ".sdlc-output", "node_modules", "vendor",
             ".venv", "venv", "env", "__pycache__", "dist", "build", "target", "bin", "obj", "out", "coverage",
             "graphify-out", "test-results", "playwright-report", "docs", "intent", "specs", "tickets", "plans",
             "designs", "requirements", "releases", "runbooks", "test-reports"}


def has_code(root, limit=1):
    """True when the repo has at least `limit` source files outside the SDLC's own folders."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            if Path(f).suffix.lower() in SOURCE_EXTS:
                n += 1
                if n >= limit:
                    return True
    return False


def sections(text):
    """{heading: body} of the '## ' sections, HTML comments removed."""
    out, current = {}, None
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            out[current] = []
        elif current:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def cited_paths(text):
    """Backticked tokens that look like repo paths (a folder, a file, file:line, or a glob)."""
    paths = []
    for tok in CODE_RE.findall(text):
        tok = tok.strip()
        if (" " in tok or "(" in tok or "=" in tok or tok.startswith("-") or "://" in tok
                or not PATHLIKE_RE.match(tok)):
            continue
        if "/" in tok or re.search(r"\.[A-Za-z0-9]{1,6}(:\d+(-\d+)?)?$", tok):
            paths.append(tok)
    return paths


def path_exists(root, tok):
    tok = re.sub(r":\d+(-\d+)?$", "", tok).rstrip("/")
    if any(c in tok for c in "*?["):
        return any(Path(root).glob(tok))
    return (Path(root) / tok).exists()


def check_paths(root, text, where):
    """(errors, how many cited paths exist). A path with a folder (`src/lib/db.ts`) must exist; a bare
    name (`config.json`, but also `.csv`, `.btn` or `res.json`, which are often not files) only counts
    when it does."""
    errors, good = [], 0
    for tok in cited_paths(text):
        if path_exists(root, tok):
            good += 1
        elif "/" in tok:
            errors.append(f"{where}: `{tok}` does not exist in the repo")
    return errors, good


def patterns_state(root):
    """('missing' | 'template' | 'partial' | 'filled', errors)."""
    p = Path(root) / "PATTERNS.md"
    if not p.is_file():
        return "missing", ["PATTERNS.md is missing"]
    secs = sections(p.read_text(encoding="utf-8"))
    errors, filled = [], 0
    for name in PATTERN_SECTIONS:
        body = secs.get(name)
        if body is None:
            errors.append(f"PATTERNS.md: section '## {name}' is missing")
            continue
        if not body:
            errors.append(f"PATTERNS.md: '{name}' is still empty: describe how this codebase does it, "
                          "or write 'None: <why>'")
            continue
        path_errors, good = check_paths(root, body, f"PATTERNS.md '{name}'")
        errors += path_errors
        if not good and not NOT_APPLICABLE_RE.search(body):
            errors.append(f"PATTERNS.md: '{name}' must name at least one real file (in backticks), "
                          "or say 'None: <why>'")
        else:
            filled += 1
    state = "filled" if not errors else ("template" if filled == 0 else "partial")
    return state, errors


def architecture(root):
    """(present, errors) for the '## Architecture' section of CLAUDE.md, outside the sdlc block."""
    p = Path(root) / "CLAUDE.md"
    if not p.is_file():
        return False, ["CLAUDE.md is missing"]
    text = p.read_text(encoding="utf-8")
    if BEGIN in text and END in text:
        text = text[:text.index(BEGIN)] + text[text.index(END) + len(END):]
    body = sections(text).get("Architecture")
    if body is None:
        return False, ["CLAUDE.md: no '## Architecture' section (outside the sdlc block): what is where in this codebase"]
    errors, good = check_paths(root, body, "CLAUDE.md Architecture")
    bullets = len(re.findall(r"^\s*[-*]\s+\S", body, re.M))
    if bullets < 3:
        errors.append(f"CLAUDE.md Architecture: at least 3 points (modules, entry points, how to run), found {bullets}")
    if good < 2:
        errors.append("CLAUDE.md Architecture: name at least 2 real files or folders (in backticks)")
    return True, errors


def status(root):
    state, _ = patterns_state(root)
    present, _ = architecture(root)
    return {"has_code": has_code(root), "patterns": state, "architecture": present}


def check(root):
    _, errors = patterns_state(root)
    _, arch_errors = architecture(root)
    return errors + arch_errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["status", "check"])
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    if args.mode == "status":
        print(json.dumps(status(args.root)))
        return 0
    errors = check(args.root)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    print("OK: PATTERNS.md and the CLAUDE.md Architecture section are written" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
