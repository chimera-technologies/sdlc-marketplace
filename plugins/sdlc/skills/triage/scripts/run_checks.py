#!/usr/bin/env python3
"""Run the Maintain checks in .sdlc/maintain.json; turn breaches into intents.

Deterministic, standard library only. Run by the maintain workflow on a
schedule (and by hand to test a check).

  run_checks.py                      # run every check, report, change nothing
  run_checks.py --dispatch           # also send each breach to the intake

A check is any command, in any language:
  {"name": "api-p95-latency", "source": "maintain", "fingerprint": "api-p95-latency",
   "command": "python scripts/check_latency.py --band 800", "timeout": 120}
It exits 0 when healthy, or exits 1 and prints one JSON object (the signal,
e.g. {"metric": "p95_latency_ms", "value": 2400, "band": "<=800"}) on a
breach. Any other exit, or bad output, is a broken check: reported, not an
intent. --dispatch POSTs a repository_dispatch "create-intent" to this repo
(GITHUB_REPOSITORY) with GH_TOKEN; the intake drafts the intent and
deduplicates by fingerprint, so a breach that persists does not pile up.

Exit 0 = ran (breaches are not failures), 1 = a check is broken or the
config is invalid.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

FINGERPRINT_RE = re.compile(r"^[a-z0-9-]{1,60}$")
SOURCES = {"maintain", "claude-security", "claude-tag"}


def load_checks(root):
    """Return (checks, errors)."""
    path = Path(root) / ".sdlc" / "maintain.json"
    if not path.is_file():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [], [f".sdlc/maintain.json is not valid JSON: {e}"]
    checks, errors, seen = [], [], set()
    for i, c in enumerate(data.get("checks", [])):
        name = c.get("name", "")
        where = f"checks[{i}] ({name or 'unnamed'})"
        if not name or not c.get("command"):
            errors.append(f"{where}: needs a name and a command")
            continue
        fp = c.get("fingerprint") or name
        if not FINGERPRINT_RE.match(fp):
            errors.append(f"{where}: fingerprint {fp!r} must match ^[a-z0-9-]{{1,60}}$")
            continue
        if fp in seen:
            errors.append(f"{where}: fingerprint {fp!r} is used twice")
            continue
        src = c.get("source", "maintain")
        if src not in SOURCES:
            errors.append(f"{where}: source must be one of {sorted(SOURCES)}")
            continue
        seen.add(fp)
        checks.append({"name": name, "command": c["command"], "fingerprint": fp, "source": src,
                       "timeout": int(c.get("timeout", 120))})
    return checks, errors


def run_check(check, root, runner=subprocess.run):
    """Return ('healthy'|'breach'|'broken', signal_or_message)."""
    try:
        proc = runner(check["command"], shell=True, cwd=root, capture_output=True, text=True, timeout=check["timeout"])
    except subprocess.TimeoutExpired:
        return "broken", f"timed out after {check['timeout']}s"
    if proc.returncode == 0:
        return "healthy", None
    if proc.returncode != 1:
        return "broken", f"exit {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-300:]}"
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    try:
        signal = json.loads(lines[-1]) if lines else None
    except ValueError:
        signal = None
    if not isinstance(signal, dict):
        return "broken", "exit 1 but the last line of output is not a JSON object (the signal)"
    signal.setdefault("check", check["name"])
    signal.setdefault("detected_at", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return "breach", signal


def dispatch(repo, token, check, signal, post=None):
    payload = {"event_type": "create-intent", "client_payload": {
        "source": check["source"], "record_id": "none", "fingerprint": check["fingerprint"], "signal": signal}}
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/dispatches", data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    if post:
        return post(req)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        raise SystemExit(f"dispatch for {check['name']} failed: HTTP {e.code} {e.read().decode(errors='replace')[:200]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--dispatch", action="store_true", help="send each breach to the intake")
    args = ap.parse_args()
    checks, errors = load_checks(args.root)
    for e in errors:
        print(f"::error file=.sdlc/maintain.json::{e}", file=sys.stderr)
    if errors:
        return 1
    if not checks:
        print("No checks in .sdlc/maintain.json; nothing to do.")
        return 0
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
    if args.dispatch and not (repo and token):
        print("--dispatch needs GITHUB_REPOSITORY and GH_TOKEN", file=sys.stderr)
        return 1
    rows, broken = [], 0
    for c in checks:
        status, detail = run_check(c, args.root)
        note = ""
        if status == "breach":
            note = json.dumps(detail)[:200]
            if args.dispatch:
                dispatch(repo, token, c, detail)
                note = "intent requested (" + note + ")"
        elif status == "broken":
            broken += 1
            note = detail
            print(f"::warning::check {c['name']} is broken: {detail}", file=sys.stderr)
        rows.append((c["name"], status, note))
        print(f"{status:8} {c['name']} {note}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### Maintain checks\n\n| Check | Result | Detail |\n|---|---|---|\n")
            for name, status, note in rows:
                fh.write(f"| {name} | {status} | {note.replace('|', '/')} |\n")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
