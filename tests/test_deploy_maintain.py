"""Tests for the Deploy stage (validate_release, deploy_config) and the
Maintain stage (run_checks)."""
import importlib.util
import json
import shutil
import subprocess
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


if __name__ == "__main__":
    unittest.main()
