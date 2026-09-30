"""Tests for plugins/sdlc/skills/init/scripts/init_project.py (project onboarding)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import importlib

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "plugins" / "sdlc" / "skills" / "init" / "scripts" / "init_project.py"
_spec = importlib.util.spec_from_file_location("init_project", INIT)
ip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ip)

ANSWERS = {
    "sdlc_ref": "v0.6.0",
    "owners": {"product_owner": "@alice", "service_owner": "@acme/sre", "tech_lead": "@bob"},
    "jira": {"enabled": True, "site": "acme.atlassian.net", "space_key": "ACM"},
    "stack": {"toolchains": ["python@3.12"], "install_command": "pip install -r requirements.txt",
              "test_command": "pytest -q", "test_file_command": "pytest -q {file}"},
}
CALLERS = ["sdlc-pull-request.yml", "sdlc-push.yml", "sdlc-intake.yml", "sdlc-maintain.yml"]


def yaml_load(text):
    try:
        import yaml  # noqa: WPS433 - only for parsing checks when available
    except ImportError:
        return None
    return yaml.safe_load(text)


class InitTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_init(self, answers=None, *extra):
        path = self.root / "answers.json"
        path.write_text(json.dumps(answers or ANSWERS), encoding="utf-8")
        return subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--answers", str(path), *extra],
                              capture_output=True, text=True)

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_normalize_validates(self):
        _, errors = ip.normalize({"sdlc_ref": "latest", "owners": {"product_owner": "alice"},
                                  "jira": {"enabled": True, "site": "acme.com", "space_key": "acm"},
                                  "stack": {"test_command": "pytest # all"}})
        text = " ".join(errors)
        for frag in ("sdlc_ref", "owners.product_owner", "jira.site", "jira.space_key", "must not contain '#'"):
            self.assertIn(frag, text)
        a, errors = ip.normalize(ANSWERS)
        self.assertEqual(errors, [])
        self.assertEqual(a["owners"]["security_owner"], "@bob")
        self.assertTrue(all(a["stages"].values()))

    def test_setup_writes_everything(self):
        r = self.run_init()
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in [".sdlc/sdlc.json", ".sdlc/owners.yaml", ".sdlc/jira.yaml", ".sdlc/build.yaml", ".sdlc/review.json",
                    ".sdlc/deploy.yaml", ".sdlc/maintain.json", "REVIEW.md", "CLAUDE.md", ".claude/settings.json",
                    ".gitignore", "intent/.gitkeep", "releases/.gitkeep"] + [f".github/workflows/{c}" for c in CALLERS]:
            self.assertTrue((self.root / rel).is_file(), rel)
        self.assertIn("Next steps", r.stdout)
        self.assertIn("JIRA_API_TOKEN", r.stdout)

    def test_callers_pin_one_ref_and_parse(self):
        self.run_init()
        for c in CALLERS:
            text = self.read(f".github/workflows/{c}")
            self.assertIn("@v0.6.0\n", text)
            self.assertNotIn("@v0.5", text)
            self.assertIn("sdlc_ref: v0.6.0", text)
            self.assertIn("SDLC_APP_PRIVATE_KEY: ${{ secrets.SDLC_APP_PRIVATE_KEY }}", text)
            parsed = yaml_load(text)
            if parsed is not None:
                self.assertIn("jobs", parsed, c)

    def test_owner_config_is_a_valid_owners_file(self):
        self.run_init()
        vi_spec = importlib.util.spec_from_file_location(
            "vi", ROOT / "plugins" / "sdlc" / "skills" / "write-intent" / "scripts" / "validate_intent.py")
        vi = importlib.util.module_from_spec(vi_spec)
        vi_spec.loader.exec_module(vi)
        self.assertEqual(vi.load_owners(self.root / ".sdlc" / "owners.yaml"), {"@alice", "@acme/sre", "@bob"})

    def test_build_yaml_is_read_by_the_build_guard(self):
        self.run_init()
        bg_spec = importlib.util.spec_from_file_location("bg", ROOT / "plugins" / "sdlc" / "hooks" / "build_guard.py")
        bg = importlib.util.module_from_spec(bg_spec)
        bg_spec.loader.exec_module(bg)
        cfg = bg.load_build_config(self.root)
        self.assertEqual(cfg["toolchains"], ["python@3.12"])
        self.assertEqual(cfg["test_command"], "pytest -q")
        self.assertEqual(cfg["code_paths"], ["src/", "tests/"])

    def test_existing_files_are_kept(self):
        (self.root / "CLAUDE.md").write_text("# Mine\n\nKeep this.\n", encoding="utf-8")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text(json.dumps({"model": "sonnet", "permissions": {"allow": ["Bash(make *)"]}}), encoding="utf-8")
        (self.root / ".sdlc").mkdir()
        (self.root / ".sdlc" / "owners.yaml").write_text("default:\n  product_owner: \"@carol\"\n", encoding="utf-8")
        self.run_init()
        claude = self.read("CLAUDE.md")
        self.assertTrue(claude.startswith("# Mine\n\nKeep this.\n"))
        self.assertEqual(claude.count(ip.BEGIN), 1)
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertEqual(settings["model"], "sonnet")
        self.assertEqual(settings["permissions"]["allow"][0], "Bash(make *)")
        self.assertIs(settings["enabledPlugins"]["sdlc@chimera-sdlc"], True)
        self.assertIn("@carol", self.read(".sdlc/owners.yaml"), "create-once config must not be overwritten")

    def test_rerun_is_idempotent(self):
        self.run_init()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        r = self.run_init()
        self.assertEqual(r.returncode, 0)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_check_and_drift(self):
        self.run_init()
        self.assertEqual(ip.check(self.root), [])
        wf = self.root / ".github" / "workflows" / "sdlc-push.yml"
        wf.write_text(wf.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
        self.assertTrue(any("sdlc-push.yml differs" in p for p in ip.check(self.root)))

    def test_upgrade_moves_every_pin(self):
        self.run_init()
        r = subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--upgrade", "v0.7.0"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for c in CALLERS:
            self.assertNotIn("v0.6.0", self.read(f".github/workflows/{c}"))
        self.assertEqual(json.loads(self.read(".claude/settings.json"))["extraKnownMarketplaces"]["chimera-sdlc"]["source"]["ref"], "v0.7.0")
        self.assertIn("at `v0.7.0`", self.read("CLAUDE.md"))
        self.assertEqual(ip.check(self.root), [])

    def test_disabled_stages_have_no_callers(self):
        answers = {**ANSWERS, "stages": {"plan": False, "maintain": False, "ui_design": False, "deploy": False}}
        self.run_init(answers)
        self.assertFalse((self.root / ".github" / "workflows" / "sdlc-intake.yml").exists())
        self.assertFalse((self.root / ".github" / "workflows" / "sdlc-maintain.yml").exists())
        pr = self.read(".github/workflows/sdlc-pull-request.yml")
        self.assertNotIn("intent-check", pr)
        self.assertNotIn("design-check", pr)
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertNotIn("figma@claude-plugins-official", settings["enabledPlugins"])
        self.assertNotIn("ui_design", self.read(".github/workflows/sdlc-push.yml"))

    def test_ui_design_mockups_come_with_the_spec(self):
        self.run_init()
        push = self.read(".github/workflows/sdlc-push.yml")
        job = push.split("  intent-to-spec:\n", 1)[1].split("\n  spec-to-stories:", 1)[0]
        self.assertIn("      ui_design: true\n", job)
        self.assertIn("automatic with the spec", self.read("CLAUDE.md"))

    def test_jira_off(self):
        self.run_init({**ANSWERS, "jira": {"enabled": False}})
        self.assertIn("enabled: false", self.read(".sdlc/jira.yaml"))

    def test_detect(self):
        cases = [
            ("package.json", json.dumps({"devDependencies": {"@playwright/test": "1.0"}}), "npx playwright test"),
            ("package.json", json.dumps({"scripts": {"test": "jest"}}), "npm test"),
            ("requirements.txt", "pytest\n", "pytest -q"),
            ("pom.xml", "<project/>", "mvn -B test"),
            ("go.mod", "module x\n", "go test ./..."),
        ]
        for name, content, test_cmd in cases:
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / name).write_text(content, encoding="utf-8")
                self.assertEqual(ip.detect(d)["test_command"], test_cmd, name)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ip.detect(d), {})

    def test_set_stack_rewrites_only_stack_keys(self):
        self.run_init()
        build = self.root / ".sdlc" / "build.yaml"
        build.write_text(build.read_text(encoding="utf-8").replace("graphify_version: 0.9.71", "graphify_version: 0.9.99"), encoding="utf-8")
        ip.set_stack(self.root, {"toolchains": ["java@21"], "install_command": "mvn -B -q install",
                                 "test_command": "mvn -B test", "test_paths": ["src/test/"]})
        text = build.read_text(encoding="utf-8")
        self.assertIn("toolchains: [java@21]", text)
        self.assertIn("test_command: mvn -B test", text)
        self.assertIn("test_paths: [src/test/]", text)
        self.assertIn("graphify_version: 0.9.99", text)
        with self.assertRaises(SystemExit):
            ip.set_stack(self.root, {"test_command": "mvn test # x"})


if __name__ == "__main__":
    unittest.main()
