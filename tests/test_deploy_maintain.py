"""Tests for the Deploy stage (validate_release, deploy_config) and the
Maintain stage (run_checks)."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "sdlc" / "skills"
EXAMPLE = SKILLS / "release" / "examples" / "v1.1.0.md"
OWNERS = SKILLS / "write-intent" / "examples" / "owners.yaml"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vr = load("validate_release", SKILLS / "release" / "scripts" / "validate_release.py")
dc = load("deploy_config", SKILLS / "release" / "scripts" / "deploy_config.py")
rc = load("run_checks", SKILLS / "triage" / "scripts" / "run_checks.py")
init = load("init_project", SKILLS / "init" / "scripts" / "init_project.py")


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.text = EXAMPLE.read_text(encoding="utf-8")
        self.owners = vr.vi.load_owners(OWNERS)

    def check(self, text=None, name="v1.1.0"):
        p = self.dir / f"{name}.md"
        p.write_text(self.text if text is None else text, encoding="utf-8")
        return vr.validate(p, self.owners)

    def assertError(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r} in {errors}")

    def test_example_is_valid(self):
        fm, errors = self.check()
        self.assertEqual(errors, [])
        self.assertEqual(fm["type"], "release")
        _, body = vr.vi.parse_frontmatter(self.text)
        self.assertEqual([r["jira"] for r in vr.changes(body)], ["CLM-483", "CLM-484", "CLM-485"])

    def test_template_is_rejected(self):
        _, errors = vr.validate(SKILLS / "release" / "templates" / "release.md")
        self.assertError(errors, "unfilled template placeholder")

    def test_version_must_match_file_and_be_newer(self):
        self.assertError(self.check(name="v2.0.0")[1], "must match the file name")
        self.assertError(self.check(self.text.replace("previous: v1.0.0", "previous: v1.2.0"))[1], "must be newer than previous")

    def test_rollback_may_go_back(self):
        text = self.text.replace("type: release", "type: rollback").replace("previous: v1.0.0", "previous: v1.2.0")
        self.assertEqual(self.check(text)[1], [])

    def test_commit_must_be_full_sha(self):
        self.assertError(self.check(self.text.replace("3f9c2d8a1b7e4c6d5f0a9e8b7c6d5e4f3a2b1c0d", "3f9c2d8"))[1], "full 40-character sha")

    def test_release_needs_changes(self):
        start, end = self.text.index("| CLM-483"), self.text.index("\n\n## Risk")
        self.assertError(self.check(self.text[:start] + self.text[end:])[1], "needs at least one")

    def test_jira_key_format(self):
        self.assertError(self.check(self.text.replace("| CLM-483 |", "| clm483 |"))[1], "must be a Jira key")

    def test_owner_must_be_listed(self):
        self.assertError(self.check(self.text.replace('"@example-org/claims-sre"', '"@nobody"'))[1], "not listed")


class DeployConfigTest(unittest.TestCase):
    def test_defaults_and_values(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dc.load(d)["production_environment"], "production")
            (Path(d) / ".sdlc").mkdir()
            (Path(d) / ".sdlc" / "deploy.yaml").write_text(
                "deploy_command: ./deploy.sh   # comment\nstaging_environment:\n", encoding="utf-8")
            cfg = dc.load(d)
        self.assertEqual(cfg["deploy_command"], "./deploy.sh")
        self.assertEqual(cfg["staging_environment"], "")

    def test_init_writes_a_readable_deploy_yaml(self):
        a, _ = init.normalize({"sdlc_ref": "v0.6.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".sdlc").mkdir()
            (Path(d) / ".sdlc" / "deploy.yaml").write_text(init.render_deploy(a), encoding="utf-8")
            cfg = dc.load(d)
        self.assertEqual((cfg["deploy_command"], cfg["staging_environment"], cfg["production_environment"]),
                         ("", "staging", "production"))


class Proc:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class RunChecksTest(unittest.TestCase):
    def repo(self, checks):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / ".sdlc").mkdir()
        (root / ".sdlc" / "maintain.json").write_text(json.dumps({"checks": checks}), encoding="utf-8")
        return root

    def test_load_validates(self):
        root = self.repo([{"name": "a", "command": "x"}, {"name": "b"}, {"name": "c", "command": "x", "fingerprint": "Bad FP"},
                          {"name": "d", "command": "x", "fingerprint": "a"}, {"name": "e", "command": "x", "source": "pager"}])
        checks, errors = rc.load_checks(root)
        self.assertEqual([c["name"] for c in checks], ["a"])
        text = " ".join(errors)
        for frag in ("needs a name and a command", "must match", "used twice", "source must be one of"):
            self.assertIn(frag, text)

    def test_init_example_config_loads(self):
        a, _ = init.normalize({"sdlc_ref": "v0.6.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        root = self.repo([])
        (root / ".sdlc" / "maintain.json").write_text(init.render_maintain(a), encoding="utf-8")
        self.assertEqual(rc.load_checks(root), ([], []))

    def test_outcomes(self):
        check = {"name": "latency", "command": "x", "fingerprint": "api-p95", "source": "maintain", "timeout": 5}
        self.assertEqual(rc.run_check(check, ".", lambda *a, **k: Proc(0))[0], "healthy")
        status, signal = rc.run_check(check, ".", lambda *a, **k: Proc(1, 'noise\n{"metric": "p95_ms", "value": 2400}\n'))
        self.assertEqual(status, "breach")
        self.assertEqual((signal["value"], signal["check"]), (2400, "latency"))
        self.assertIn("detected_at", signal)
        self.assertEqual(rc.run_check(check, ".", lambda *a, **k: Proc(1, "not json"))[0], "broken")
        self.assertEqual(rc.run_check(check, ".", lambda *a, **k: Proc(2, "", "boom"))[0], "broken")

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired("x", 5)
        self.assertEqual(rc.run_check(check, ".", timeout), ("broken", "timed out after 5s"))

    def test_dispatch_payload(self):
        sent = {}

        def post(req):
            sent["url"], sent["body"], sent["auth"] = req.full_url, json.loads(req.data), req.get_header("Authorization")
            return 204

        check = {"name": "latency", "fingerprint": "api-p95", "source": "maintain"}
        self.assertEqual(rc.dispatch("acme/app", "tok", check, {"value": 2400}, post), 204)
        self.assertEqual(sent["url"], "https://api.github.com/repos/acme/app/dispatches")
        self.assertEqual(sent["auth"], "Bearer tok")
        self.assertEqual(sent["body"], {"event_type": "create-intent", "client_payload": {
            "source": "maintain", "record_id": "none", "fingerprint": "api-p95", "signal": {"value": 2400}}})


class InitDeployWiringTest(unittest.TestCase):
    def test_release_caller_passes_deploy_token_and_runbooks_folder(self):
        a, _ = init.normalize({"sdlc_ref": "v0.6.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        push = init.render_callers(a)[".github/workflows/sdlc-push.yml"]
        release_job = push[push.index("  release:"):]
        self.assertIn("DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}", release_job)
        self.assertIn("runbooks", init.FOLDERS)

    def test_release_caller_can_log_in_with_oidc_and_allow_destroy(self):
        a, _ = init.normalize({"sdlc_ref": "v0.6.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        push = init.render_callers(a)[".github/workflows/sdlc-push.yml"]
        release_job = push[push.index("  release:"):]
        self.assertIn("    permissions:\n      contents: read\n      id-token: write\n", release_job)
        self.assertIn("allow_destroy: ${{ inputs.rerun == 'release' && inputs.allow_destroy || false }}", release_job)
        self.assertIn("      allow_destroy:\n        description:", push)


IAC = load("iac", SKILLS / "release" / "scripts" / "iac.py")


def plan_json(*actions):
    return {"resource_changes": [{"address": f"aws_x.r{i}", "change": {"actions": a}} for i, a in enumerate(actions)]}


class InfraDeployConfigTest(unittest.TestCase):
    def write(self, d, text):
        (Path(d) / ".sdlc").mkdir(exist_ok=True)
        (Path(d) / ".sdlc" / "deploy.yaml").write_text(text, encoding="utf-8")
        return dc.load(d)

    def test_cloud_and_iac(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual((dc.load(d)["cloud"], dc.load(d)["iac"]), ("none", "none"))
            cfg = self.write(d, "cloud: gcp\niac: terraform\niac_dir: infra/live   # c\niac_var_file: envs/{env}.tfvars\n")
        self.assertEqual((cfg["cloud"], cfg["iac"], cfg["iac_dir"], cfg["iac_var_file"]), ("gcp", "terraform", "infra/live", "envs/{env}.tfvars"))
        self.assertEqual(dc.errors(cfg), [])

    def test_invalid_values(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self.write(d, "cloud: oracle\niac: pulumi\niac_dir: ../outside\n")
        text = " ".join(dc.errors(cfg))
        for frag in ("cloud must be one of", "iac must be one of", "iac_dir must be a relative path"):
            self.assertIn(frag, text)

    def test_deploys_output(self):
        script = SKILLS / "release" / "scripts" / "deploy_config.py"
        # In CI, GITHUB_OUTPUT is set and the script writes there; make it print instead.
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
        with tempfile.TemporaryDirectory() as d:
            self.write(d, "iac: terraform\n")
            r = subprocess.run([sys.executable, str(script), "--root", d], capture_output=True, text=True, env=env)
            self.assertIn("deploys=true", r.stdout)
            self.write(d, "cloud: oracle\n")
            r = subprocess.run([sys.executable, str(script), "--root", d], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1)

    def test_init_render_and_record(self):
        a, _ = init.normalize({"sdlc_ref": "v0.6.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        with tempfile.TemporaryDirectory() as d:
            cfg = self.write(d, init.render_deploy(a))
            self.assertEqual((cfg["cloud"], cfg["iac"], cfg["production_plan_environment"]), ("none", "none", "production-plan"))
            init.set_deploy(d, {"cloud": "azure", "iac": "terraform", "smoke_command": "npm run smoke -- --reporter=line"})
            cfg = dc.load(d)
            text = (Path(d) / ".sdlc" / "deploy.yaml").read_text(encoding="utf-8")
            self.assertEqual((cfg["cloud"], cfg["iac"], cfg["smoke_command"]), ("azure", "terraform", "npm run smoke -- --reporter=line"))
            self.assertIn("# none, aws, azure or gcp", text, "comments are kept")
            with self.assertRaises(SystemExit):
                init.set_deploy(d, {"cloud": "oracle"})


class IacPlanTest(unittest.TestCase):
    def test_changes_counts_and_risky(self):
        counts, risky = IAC.changes(plan_json(["create"], ["update"], ["delete"], ["delete", "create"], ["create", "delete"], ["no-op"]))
        self.assertEqual(counts, {"create": 1, "update": 1, "replace": 2, "destroy": 1})
        self.assertEqual([a for a, _ in risky], ["destroy", "replace", "replace"])

    def test_summary_stops_on_destroy_unless_allowed(self):
        counts, risky = IAC.changes(plan_json(["create"], ["delete"]))
        stopped = IAC.summary("production", counts, risky, allowed=False)
        self.assertIn("**Stopped: nothing was applied.**", stopped)
        self.assertIn("`aws_x.r1`", stopped)
        self.assertIn("Destroy allowed for this run", IAC.summary("production", counts, risky, allowed=True))
        self.assertIn("Nothing is destroyed or replaced", IAC.summary("staging", *IAC.changes(plan_json(["create"])), allowed=False))

    def test_commands_use_the_environment(self):
        cfg = {"iac_dir": "infra", "iac_backend_config": "envs/{env}.backend.hcl", "iac_var_file": "envs/{env}.tfvars"}
        self.assertIn("-backend-config=envs/production.backend.hcl", IAC.init_cmd(cfg, "production"))
        plan = IAC.plan_cmd(cfg, "staging", "p.tfplan")
        self.assertIn("-var-file=envs/staging.tfvars", plan)
        self.assertIn("-chdir=infra", plan)
        self.assertTrue(any(a.startswith("-out=") for a in plan))
        bare = {"iac_dir": "infra", "iac_backend_config": "", "iac_var_file": ""}
        self.assertFalse(any("-backend-config" in a or "-var-file" in a for a in IAC.init_cmd(bare, "x") + IAC.plan_cmd(bare, "x", "p")))

    def test_cli_refuses_without_terraform_config(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(SKILLS / "release" / "scripts" / "iac.py"), "plan", "--env", "staging",
                                "--root", d, "--out", "p", "--summary", "s"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("iac is 'none'", r.stderr)


class DetectInfraTest(unittest.TestCase):
    def test_detects_terraform_docker_helm_and_manifests(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel, text in {"infra/main.tf": 'resource "x" "y" {}\n', "Dockerfile": "FROM node:22-alpine\n",
                              "charts/app/Chart.yaml": "apiVersion: v2\nname: app\n",
                              "k8s/deploy.yaml": "apiVersion: apps/v1\nkind: Deployment\n",
                              ".github/workflows/ci.yml": "name: ci\non: push\n",
                              "node_modules/x/main.tf": "ignored\n"}.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            infra = init.detect_infra(root)
        self.assertEqual(len(infra["found"]), 4, infra["found"])
        self.assertEqual(set(infra["toolchains"]), {"terraform@1.9.8", "helm@3.16.2", "kubectl@1.31.0"})
        self.assertEqual(infra["deploy"], {"iac": "terraform", "iac_dir": "infra"})
        self.assertIn("infra/", infra["code_paths"])
        self.assertIn("Dockerfile", infra["code_paths"])
        self.assertFalse(any("node_modules" in f or ".github" in f for f in infra["found"]))
        self.assertNotIn("cloud", infra["deploy"], "the cloud is the architect's decision, never detected")

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(init.detect_infra(d)["found"], [])


if __name__ == "__main__":
    unittest.main()
