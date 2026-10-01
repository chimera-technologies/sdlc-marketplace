#!/usr/bin/env python3
"""Plan and apply the project's infrastructure for one environment (Deploy stage).

Deterministic, standard library only. Used by the release workflow when
.sdlc/deploy.yaml has `iac: terraform`; the cloud login happened before.

  iac.py plan  --env staging --out plan.tfplan --summary summary.md [--allow-destroy]
  iac.py apply --env production --plan plan.tfplan

plan: `terraform init` (with iac_backend_config for the environment, if set),
`terraform plan -out` (with iac_var_file, if set), then reads the plan with
`terraform show -json` and writes a markdown summary: counts to create,
update, replace and destroy, and every resource that would be destroyed or
replaced. Exit 3 when anything would be destroyed or replaced and
--allow-destroy is not given: a person re-runs the release with
allow_destroy after reading the summary. Exit 0 = planned, 1 = error.

apply: `terraform init` the same way, then `terraform apply` of exactly the
saved plan (the one the production approvers saw).

{env} in iac_var_file and iac_backend_config is replaced by the environment.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_DC = Path(__file__).resolve().parent / "deploy_config.py"
_spec = importlib.util.spec_from_file_location("deploy_config", _DC)
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

EXIT_DESTROY = 3


def env_path(value, env):
    return value.replace("{env}", env) if value else ""


def init_cmd(cfg, env):
    cmd = ["terraform", f"-chdir={cfg['iac_dir']}", "init", "-input=false", "-no-color"]
    backend = env_path(cfg["iac_backend_config"], env)
    if backend:
        cmd.append(f"-backend-config={backend}")
    return cmd


def plan_cmd(cfg, env, out):
    cmd = ["terraform", f"-chdir={cfg['iac_dir']}", "plan", "-input=false", "-no-color", "-lock-timeout=5m",
           f"-out={Path(out).resolve()}"]
    var_file = env_path(cfg["iac_var_file"], env)
    if var_file:
        cmd.append(f"-var-file={var_file}")
    return cmd


def changes(plan_json):
    """Counts and the destroyed/replaced addresses from `terraform show -json <plan>`."""
    counts = {"create": 0, "update": 0, "replace": 0, "destroy": 0}
    risky = []
    for rc in plan_json.get("resource_changes") or []:
        actions = rc.get("change", {}).get("actions") or []
        if actions in (["delete", "create"], ["create", "delete"]):
            counts["replace"] += 1
            risky.append(("replace", rc.get("address", "?")))
        elif actions == ["delete"]:
            counts["destroy"] += 1
            risky.append(("destroy", rc.get("address", "?")))
        elif actions == ["create"]:
            counts["create"] += 1
        elif actions == ["update"]:
            counts["update"] += 1
    return counts, risky


def summary(env, counts, risky, allowed):
    head = (f"### Infrastructure plan: {env}\n\n"
            f"{counts['create']} to create, {counts['update']} to update, "
            f"**{counts['replace']} to replace, {counts['destroy']} to destroy**.\n")
    if not risky:
        return head + "\nNothing is destroyed or replaced.\n"
    rows = "\n".join(f"| {a} | `{addr}` |" for a, addr in risky)
    note = ("Destroy allowed for this run (allow_destroy)." if allowed else
            "**Stopped: nothing was applied.** Read the list; if it is intended, re-run the release with "
            "`allow_destroy: true` (Actions > SDLC push > Run workflow).")
    return head + f"\n> [!CAUTION]\n> {note}\n\n| Action | Resource |\n|---|---|\n{rows}\n"


def run(cmd, capture=False):
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, capture_output=capture)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["plan", "apply"])
    ap.add_argument("--env", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", help="plan: where to save the plan")
    ap.add_argument("--summary", help="plan: where to write the markdown summary")
    ap.add_argument("--plan", help="apply: the saved plan to apply")
    ap.add_argument("--allow-destroy", action="store_true")
    args = ap.parse_args()
    os.chdir(args.root)
    cfg = dc.load(".")
    problems = dc.errors(cfg)
    if cfg["iac"] != "terraform":
        problems.append(f"iac is {cfg['iac']!r}; this script handles terraform")
    if args.action == "plan" and not (args.out and args.summary):
        problems.append("plan needs --out and --summary")
    if not shutil.which("terraform"):
        problems.append("terraform is not installed: add terraform@<version> to toolchains in .sdlc/build.yaml")
    if problems:
        for p in problems:
            print(f"::error::{p}", file=sys.stderr)
        return 1
    try:
        run(init_cmd(cfg, args.env))
        if args.action == "apply":
            if not args.plan or not Path(args.plan).is_file():
                print("::error::apply needs --plan with the saved plan", file=sys.stderr)
                return 1
            run(["terraform", f"-chdir={cfg['iac_dir']}", "apply", "-input=false", "-no-color", "-lock-timeout=5m",
                 str(Path(args.plan).resolve())])
            return 0
        run(plan_cmd(cfg, args.env, args.out))
        shown = run(["terraform", f"-chdir={cfg['iac_dir']}", "show", "-json", str(Path(args.out).resolve())], capture=True)
    except subprocess.CalledProcessError as e:
        print(f"::error::{' '.join(e.cmd[:3])} failed (exit {e.returncode})", file=sys.stderr)
        return 1
    counts, risky = changes(json.loads(shown.stdout))
    text = summary(args.env, counts, risky, args.allow_destroy)
    Path(args.summary).write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return EXIT_DESTROY if risky and not args.allow_destroy else 0


if __name__ == "__main__":
    sys.exit(main())
