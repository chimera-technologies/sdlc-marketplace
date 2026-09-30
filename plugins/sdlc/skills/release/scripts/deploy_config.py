#!/usr/bin/env python3
"""Read .sdlc/deploy.yaml for the release workflow (Deploy stage).

Writes step outputs (to $GITHUB_OUTPUT, or prints them):
  deploy_command, staging_environment, production_environment, version_scheme
Defaults: no deploy command (tag + release record only), staging, production.
Standard library only.
"""
import argparse
import os
import sys
from pathlib import Path

DEFAULTS = {"deploy_command": "", "staging_environment": "staging",
            "production_environment": "production", "version_scheme": "semver"}


def load(root):
    """Flat `key: value` YAML; '#' starts a comment. Missing file = defaults."""
    cfg = dict(DEFAULTS)
    path = Path(root) / ".sdlc" / "deploy.yaml"
    if not path.is_file():
        return cfg
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line or line.startswith((" ", "\t")):
            continue
        key, _, val = line.partition(":")
        if key.strip() in cfg:
            cfg[key.strip()] = val.strip().strip("'\"")
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    cfg = load(ap.parse_args().root)
    lines = [f"{k}={v}" for k, v in cfg.items()]
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
