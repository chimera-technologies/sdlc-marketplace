#!/usr/bin/env python3
"""Read .sdlc/deploy.yaml for the release workflow (Deploy stage).

Writes step outputs (to $GITHUB_OUTPUT, or prints them): every key below,
plus `deploys` (true when there is anything to deploy: a deploy_command or
IaC). Exit 1 on an invalid value. Standard library only.

The cloud and the IaC tool are the architect's decision in the spec
(Technology and architecture); `/sdlc:init stack=specs/<slug>.md` records
them here. The cloud identity for each environment is not in this file: it
comes from that GitHub environment's variables (AWS_ROLE_ARN, AWS_REGION;
AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID;
GCP_WORKLOAD_IDENTITY_PROVIDER, GCP_SERVICE_ACCOUNT), used through OIDC
with no long-lived keys.
"""
import argparse
import os
import sys
from pathlib import Path

DEFAULTS = {
    "version_scheme": "semver",
    "deploy_command": "",                       # app deploy, per environment (SDLC_ENV set)
    "smoke_command": "",                        # after each deploy (SMOKE_URL from the environment); failure stops the release
    "staging_environment": "staging",
    "production_environment": "production",
    "production_plan_environment": "production-plan",  # no reviewers; read-only identity for the production plan
    "cloud": "none",                            # none | aws | azure | gcp
    "iac": "none",                              # none | terraform
    "iac_dir": "infra",
    "iac_var_file": "",                         # relative to iac_dir; {env} = staging/production
    "iac_backend_config": "",                   # relative to iac_dir; {env} = staging/production
}
CHOICES = {"cloud": ["none", "aws", "azure", "gcp"], "iac": ["none", "terraform"], "version_scheme": ["semver"]}


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
    for key in ("cloud", "iac"):
        cfg[key] = cfg[key] or "none"
    return cfg


def errors(cfg):
    out = [f"{k} must be one of {', '.join(v)}, got {cfg[k]!r}" for k, v in CHOICES.items() if cfg[k] not in v]
    if cfg["iac"] != "none" and not cfg["iac_dir"]:
        out.append("iac_dir is required when iac is set")
    for key in ("iac_dir", "iac_var_file", "iac_backend_config"):
        if ".." in Path(cfg[key]).parts or cfg[key].startswith("/"):
            out.append(f"{key} must be a relative path inside the repo")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    cfg = load(ap.parse_args().root)
    problems = errors(cfg)
    for p in problems:
        print(f"::error file=.sdlc/deploy.yaml::{p}", file=sys.stderr)
    if problems:
        return 1
    cfg["deploys"] = "true" if (cfg["deploy_command"] or cfg["iac"] != "none") else "false"
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
