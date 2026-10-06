#!/usr/bin/env python3
"""Build preflight: make Graphify and Ponytail ready in this product repo.

Run from the product repo root before any code is written (the build-story
skill does this in Step 0; the build guard hook blocks code until it has):

  python <plugin>/skills/build-story/scripts/build_preflight.py [--json]

Reads .sdlc/build.yaml for the pinned versions. Idempotent:
  1. Graphify: installs `graphifyy==<graphify_version>` with pip if missing
     or a different version; builds or updates graphify-out/graph.json
     (code only: local tree-sitter parsing, no LLM, no tokens). With no code
     under code_paths yet (a first story), it warns, writes the marker
     graphify-out/NO-CODE-YET instead, and continues; runs
     `graphify claude install` once, then moves its machine-specific hooks
     from the shared .claude/settings.json into .claude/settings.local.json
     (not in headless CI runs, SDLC_HEADLESS=1: it edits CLAUDE.md).
  2. Ponytail: declares the marketplace (pinned to <ponytail_ref>) and
     enables `ponytail@ponytail` in .claude/settings.json; checks that it is
     active in the current session.
  3. .gitignore: graphify-out/ and the local settings files stay out of git.

Exit 0 = ready. Exit 3 = one manual step is needed (printed). Exit 1 = error.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_GUARD = Path(__file__).resolve().parents[3] / "hooks" / "build_guard.py"
_spec = importlib.util.spec_from_file_location("build_guard", _GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

PONYTAIL_REPO = "DietrichGebert/ponytail"
GITIGNORE_LINES = ["graphify-out/", ".claude/settings.local.json", ".claude/*.graphify-bak"]
GRAPHIFY_ALLOW = ["Bash(graphify *)", "Bash(python -m graphify *)", "Bash(python3 -m graphify *)"]


# ---------------------------------------------------------------- helpers

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_lf(path, text):
    """Write text with LF line endings (Path.write_text has no newline= before 3.10)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_lf(path, json.dumps(data, indent=2) + "\n")


def run(cmd, cwd, timeout=600):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def graphify_cmd(*args):
    # `python -m graphify` works even when pip's scripts dir is not on PATH (common on Windows).
    return [sys.executable, "-m", "graphify", *args]


# ------------------------------------------------------ pure, unit-tested

def is_graphify_hook(entry):
    return any("graphify" in str(h.get("command", "")) for h in entry.get("hooks", []))


def relocate_graphify_hooks(shared, local):
    """Move Graphify's hook entries from shared settings to local settings.

    Graphify writes an absolute path to its executable, which is only valid on
    this machine, so it must not live in the committed settings.json.
    Returns (shared, local, moved_count). Non-Graphify hooks are untouched.
    """
    moved = 0
    hooks = shared.get("hooks", {})
    for event in list(hooks):
        keep, move = [], []
        for entry in hooks[event]:
            (move if is_graphify_hook(entry) else keep).append(entry)
        if move:
            moved += len(move)
            local.setdefault("hooks", {}).setdefault(event, [])
            existing = {json.dumps(e, sort_keys=True) for e in local["hooks"][event]}
            local["hooks"][event] += [e for e in move if json.dumps(e, sort_keys=True) not in existing]
        if keep:
            hooks[event] = keep
        else:
            del hooks[event]
    if "hooks" in shared and not shared["hooks"]:
        del shared["hooks"]
    return shared, local, moved


def local_has_graphify_hooks(local):
    return any(is_graphify_hook(e) for entries in local.get("hooks", {}).values() for e in entries)


def ensure_ponytail(settings, ref):
    """Declare the Ponytail marketplace (pinned) and enable the plugin. Returns changed?"""
    want = {"source": {"source": "github", "repo": PONYTAIL_REPO, "ref": ref}}
    changed = False
    markets = settings.setdefault("extraKnownMarketplaces", {})
    if markets.get("ponytail") != want:
        markets["ponytail"] = want
        changed = True
    plugins = settings.setdefault("enabledPlugins", {})
    if plugins.get("ponytail@ponytail") is not True:
        plugins["ponytail@ponytail"] = True
        changed = True
    return changed


def ensure_allow(settings, rules):
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    added = [r for r in rules if r not in allow]
    allow.extend(added)
    return bool(added)


def ensure_gitignore(text, lines):
    present = {l.strip() for l in text.splitlines()}
    missing = [l for l in lines if l not in present]
    if not missing:
        return text, False
    block = "\n# Build preflight: local Graphify graph and machine-specific settings\n" + "\n".join(missing) + "\n"
    return (text.rstrip("\n") + "\n" + block) if text.strip() else block.lstrip("\n"), True


# ------------------------------------------------------------ the graph

def stale_marker(project):
    """Code files changed since the graph was last built, one per line (written by the code hooks)."""
    return Path(project) / "graphify-out" / "STALE"


def update_graph(project):
    """Build or update graphify-out/graph.json from the code (local, no tokens).

    Returns a report line; raises SystemExit on failure. Clears the stale and
    no-code markers once the graph is current.
    """
    graph = Path(project) / "graphify-out" / "graph.json"
    args = ("update", ".") if graph.is_file() else ("extract", ".", "--code-only")
    res = run(graphify_cmd(*args), project)
    if args[0] == "update" and res.returncode != 0:
        # update refuses when the graph would shrink (e.g. after deleting code): rebuild instead.
        args = ("extract", ".", "--code-only")
        res = run(graphify_cmd(*args), project)
    if res.returncode != 0 or not graph.is_file():
        raise SystemExit(f"graphify {' '.join(args)} failed:\n{(res.stderr or res.stdout)[-1500:]}")
    for marker in (guard.no_code_marker(project), stale_marker(project)):
        if marker.is_file():
            marker.unlink()
    m = re.search(r"(\d+) nodes, (\d+) edges", res.stdout + res.stderr)
    return (f"graphify: graph {'updated' if args[0] == 'update' else 'built'}"
            + (f" ({m.group(1)} nodes, {m.group(2)} edges)" if m else ""))


def refresh_if_stale(project):
    """Update the graph when the code hooks marked it stale. Returns a report line, or None if it was current."""
    if not stale_marker(project).is_file():
        return None
    if run(graphify_cmd("--version"), project, 60).returncode != 0:
        return "graphify: not installed, graph left stale (run the Build preflight)"
    cfg = guard.load_build_config(project) or {"code_paths": []}
    if not has_code(project, cfg):
        stale_marker(project).unlink()
        return None
    return update_graph(project)


# ------------------------------------------------------------- the steps

def has_code(project, cfg):
    """True if any code_path is a file, or a folder with at least one file in it."""
    for rel in cfg.get("code_paths") or []:
        path = Path(project) / rel.strip("/")
        if path.is_file() or (path.is_dir() and any(p.is_file() for p in path.rglob("*"))):
            return True
    return False


def step_graphify(project, cfg, report):
    version = cfg.get("graphify_version", "")
    got = run(graphify_cmd("--version"), project, 60)
    installed = got.stdout.strip().split()[-1] if got.returncode == 0 and got.stdout.strip() else None
    if installed != version:
        if sys.version_info < (3, 10):
            raise SystemExit("Graphify needs Python 3.10+; this is " + sys.version.split()[0])
        spec = f"graphifyy=={version}" if version else "graphifyy"
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", spec] + ([] if in_venv else ["--user"])
        res = run(cmd, project)
        if res.returncode != 0:
            raise SystemExit(f"pip install {spec} failed:\n{res.stderr[-1500:]}")
        report.append(f"graphify: installed {spec} (was {installed or 'missing'})")
    else:
        report.append(f"graphify: {installed} already installed")

    marker = guard.no_code_marker(project)
    if not has_code(project, cfg):
        # The first story creates the code: there is nothing to index yet. The
        # marker lets the build guard allow this session's writes; the code
        # hooks build the real graph once the story has written code.
        marker.parent.mkdir(parents=True, exist_ok=True)
        write_lf(marker, "No code under code_paths when the preflight ran; the next preflight builds the graph.\n")
        report.append(f"graphify: WARNING no code under {', '.join(cfg['code_paths'])} yet, so no graph; "
                      "continuing (the graph is built once the story has code)")
        return
    report.append(update_graph(project))

    if os.environ.get("SDLC_HEADLESS") == "1":
        # CI (automatic Build): the skill already tells Claude to query the graph,
        # and the integration would edit CLAUDE.md, a file the build may not change.
        report.append("graphify: Claude Code integration skipped (headless)")
        return
    settings_path = Path(project) / ".claude" / "settings.json"
    local_path = Path(project) / ".claude" / "settings.local.json"
    claude_md = Path(project) / "CLAUDE.md"
    has_section = claude_md.is_file() and "## graphify" in claude_md.read_text(encoding="utf-8")
    if not has_section or not local_has_graphify_hooks(read_json(local_path)):
        res = run(graphify_cmd("claude", "install"), project, 120)
        if res.returncode != 0:
            raise SystemExit(f"graphify claude install failed:\n{(res.stderr or res.stdout)[-1500:]}")
        report.append("graphify: Claude Code integration installed (CLAUDE.md section + hooks)")
    shared, local, moved = relocate_graphify_hooks(read_json(settings_path), read_json(local_path))
    if moved:
        write_json(settings_path, shared)
        write_json(local_path, local)
        report.append(f"graphify: moved {moved} machine-specific hook(s) to .claude/settings.local.json")
    for bak in (Path(project) / ".claude").glob("*.graphify-bak"):
        bak.unlink()


def step_ponytail(project, cfg, report):
    """Returns True if the session must be restarted before coding."""
    settings_path = Path(project) / ".claude" / "settings.json"
    settings = read_json(settings_path)
    changed = ensure_ponytail(settings, cfg.get("ponytail_ref", "main"))
    changed = ensure_allow(settings, GRAPHIFY_ALLOW) or changed
    if changed:
        write_json(settings_path, settings)
        report.append(f"ponytail: enabled in .claude/settings.json (pinned {cfg.get('ponytail_ref', 'main')})")
    else:
        report.append("ponytail: enabled in .claude/settings.json")
    active = guard.ponytail_flag().is_file()
    report.append("ponytail: active in this session" if active else "ponytail: NOT active in this session")
    return not active


def step_gitignore(project, report):
    path = Path(project) / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    text, changed = ensure_gitignore(text, GITIGNORE_LINES)
    if changed:
        write_lf(path, text)
        report.append(".gitignore: added graphify-out/ and local settings")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print a JSON summary")
    ap.add_argument("--root", default=".", help="product repo root (default: current dir)")
    args = ap.parse_args()
    project = Path(args.root).resolve()

    cfg = guard.load_build_config(project)
    if cfg is None:
        print("No .sdlc/build.yaml here: this repo has not opted in to the Build stage.", file=sys.stderr)
        return 1
    report = []
    try:
        step_graphify(project, cfg, report)
        needs_restart = step_ponytail(project, cfg, report)
        step_gitignore(project, report)
    except SystemExit as e:
        print(f"Preflight failed: {e}", file=sys.stderr)
        return 1
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"Preflight failed: {e}", file=sys.stderr)
        return 1

    action = None
    if needs_restart:
        action = ("Ponytail is enabled for this repo but not loaded in this session. Run "
                  "`/plugin install ponytail@ponytail` (accept the marketplace if asked), then `/clear`, "
                  "then start again with /sdlc:build-story.")
    if args.json:
        print(json.dumps({"ready": not needs_restart, "steps": report, "action": action}, indent=2))
    else:
        for line in report:
            print(f"- {line}")
        print(f"\nACTION NEEDED: {action}" if action else "\nReady: Graphify and Ponytail are set up.")
    return 3 if needs_restart else 0


if __name__ == "__main__":
    sys.exit(main())
