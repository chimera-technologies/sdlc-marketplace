#!/usr/bin/env python3
"""Check that the app still starts the way a developer starts it locally.

Runs build.yaml's dev_command from a fresh clone's settings (.env copied
from .env.example when there is no .env), waits until dev_check_url
answers, then stops everything the command started. Fails, with the end of
the command's output, if the URL does not answer in time or the command
exits first. Used by the PR and main-tests workflows after the tests.

Usage: dev_check.py COMMAND URL [--timeout SECONDS] [--root DIR]

Standard library only.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def answers(url):
    """True once the URL responds with a status below 500 (a 404 still means the app is up)."""
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            return res.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def stop(proc):
    """Stop the command and everything it started (its own process group)."""
    if proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        if hasattr(os, "killpg"):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        else:
            proc.kill()


def check(command, url, root=".", timeout=180, poll=2.0):
    """(ok, message, log tail)."""
    root = Path(root)
    env_file, example = root / ".env", root / ".env.example"
    if not env_file.exists() and example.is_file():
        shutil.copyfile(example, env_file)
    log = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(["bash", "-c", command], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    start = time.monotonic()
    try:
        while time.monotonic() - start < timeout:
            if answers(url):
                return True, f"{url} answered after {int(time.monotonic() - start)}s", ""
            if proc.poll() is not None and proc.returncode != 0:
                break
            time.sleep(poll)
        if proc.poll() is not None and proc.returncode != 0:
            message = f"dev_command exited with {proc.returncode} before {url} answered"
        else:
            message = f"{url} did not answer within {timeout}s"
    finally:
        stop(proc)
    log.seek(0)
    tail = "\n".join(log.read().splitlines()[-60:])
    return False, message, tail


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command")
    ap.add_argument("url")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    ok, message, tail = check(args.command, args.url, args.root, args.timeout)
    if ok:
        print(f"The app starts locally: {message}.")
        return 0
    print(f"::error file=.sdlc/build.yaml::The app does not start locally: {message}. A new developer "
          "following the README would hit the same problem (missing .env.example values, a migration, a script).",
          file=sys.stderr)
    if tail:
        print(f"Last lines of dev_command:\n{tail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
