#!/usr/bin/env python3
"""Read the project's stack from .sdlc/build.yaml for the setup-stack action.

Writes GitHub Actions step outputs (to $GITHUB_OUTPUT, or prints them):
  node, python, java, java_distribution, dotnet, go   toolchain versions ("" = not used)
  setup_command, install_command, test_command, test_file_command

build.yaml keys (all optional except test_command for the Test stage):
  toolchains: [node@22, python@3.12, java@21, dotnet@8.0, go@1.23]
  java_distribution: temurin          # setup-java distribution (default temurin)
  setup_command: <anything else to install, e.g. a Rust or Ruby toolchain>
  install_command: npm ci && npx playwright install --with-deps chromium
  test_command: npx playwright test
  test_file_command: npx playwright test {file} --reporter=line
  report_path: playwright-report/      # uploaded as an artifact after tests

Standard library only. Exit 1 on an unknown toolchain.
"""
import argparse
import importlib.util
import os
import sys
from pathlib import Path

SUPPORTED = ["node", "python", "java", "dotnet", "go"]
KEYS = ["setup_command", "install_command", "test_command", "test_file_command", "report_path"]


def load_guard():
    # The plugin is checked out next to this action: .sdlc-plugin/{.github,plugins}.
    path = Path(__file__).resolve().parents[3] / "plugins" / "sdlc" / "hooks" / "build_guard.py"
    spec = importlib.util.spec_from_file_location("build_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_stack(root):
    """Return (outputs dict, errors list) for the project at root."""
    cfg = load_guard().load_build_config(root) or {}
    out = {k: "" for k in SUPPORTED}
    out["java_distribution"] = cfg.get("java_distribution") or "temurin"
    errors = []
    chains = cfg.get("toolchains") or []
    if isinstance(chains, str):
        chains = [chains]
    for item in chains:
        name, _, version = item.partition("@")
        name = name.strip().lower()
        if name not in SUPPORTED:
            errors.append(f"toolchain {item!r} has no preset (supported: {', '.join(SUPPORTED)}); "
                          "install it with setup_command in .sdlc/build.yaml")
            continue
        if not version.strip():
            errors.append(f"toolchain {item!r} needs a version, e.g. {name}@<version>")
            continue
        out[name] = version.strip()
    for k in KEYS:
        out[k] = cfg.get(k, "") or ""
    return out, errors


def has_code(root):
    """True if any of build.yaml's code_paths exists (before the first story, none do)."""
    cfg = load_guard().load_build_config(root) or {}
    return any((Path(root) / p.strip("/")).exists() for p in cfg.get("code_paths") or [])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--require-tests", action="store_true", help="fail if test_command is missing")
    ap.add_argument("--skip-without-code", action="store_true",
                    help="output an empty stack (nothing installed or run) if no code_paths exist yet")
    ap.add_argument("--install-if-code", action="store_true",
                    help="toolchains always, but no install_command until code_paths exist (the build of a first story)")
    args = ap.parse_args()
    out, errors = read_stack(args.root)
    if args.skip_without_code and not args.require_tests and not has_code(args.root):
        out = {k: "" for k in out}
        print("No code under code_paths yet; nothing to install or test.", file=sys.stderr)
    elif args.install_if_code and not has_code(args.root):
        out["install_command"] = ""
        print("No code under code_paths yet; toolchains only, no install_command.", file=sys.stderr)
    if args.require_tests and not out["test_command"]:
        errors.append("no test_command in .sdlc/build.yaml: record the stack with /sdlc:init stack=specs/<slug>.md")
    for e in errors:
        print(f"::error file=.sdlc/build.yaml::{e}", file=sys.stderr)
    if errors:
        return 1
    target = os.environ.get("GITHUB_OUTPUT")
    lines = []
    for k, v in out.items():
        if "\n" in v:
            lines += [f"{k}<<SDLC_EOF", v, "SDLC_EOF"]
        else:
            lines.append(f"{k}={v}")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    used = ", ".join(f"{k} {out[k]}" for k in SUPPORTED if out[k]) or "runner defaults"
    print(f"Stack: {used}; test: {out['test_command'] or '(none)'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
