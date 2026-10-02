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

    def test_auto_build(self):
        self.run_init()
        push = self.read(".github/workflows/sdlc-push.yml")
        self.assertIn("uses: bala-chimera/sdlc-marketplace/.github/workflows/sdlc-build.yml@v0.6.0", push)
        self.assertIn("inputs.rerun == 'build'", push)
        self.assertIn("options: [intent-to-spec, spec-to-stories, stack, build, release]", push)
        self.assertTrue(json.loads(self.read(".sdlc/sdlc.json"))["auto_build"])
        self.assertIn("a plan PR (reviewed for edge cases and bugs), then the build", self.read("CLAUDE.md"))

    def test_stack_pr_comes_with_the_spec(self):
        self.run_init()
        push = self.read(".github/workflows/sdlc-push.yml")
        self.assertIn("sdlc-spec-to-stack.yml@v0.6.0", push)
        self.assertIn("spec_file: ${{ inputs.rerun == 'stack' && inputs.file || '' }}", push)
        self.assertIn("options: [intent-to-spec, spec-to-stories, stack, build, release]", push)
        self.assertIn("opens a stack PR", self.read("CLAUDE.md"))
        self.run_init({**ANSWERS, "stages": {"build": False}})
        self.assertNotIn("sdlc-spec-to-stack.yml", self.read(".github/workflows/sdlc-push.yml"))

    def test_validate_stack(self):
        good = {"toolchains": ["node@22", "terraform@1.9.8", "helm@v3.16.2"], "test_command": "npm test",
                "test_file_command": "npm test -- {file}", "code_paths": ["src/"], "deploy": {"cloud": "aws", "iac": "terraform"},
                "decided": True, "evidence": {"toolchains": "Node LTS"}}
        self.assertEqual(ip.validate_stack(good), [])
        bad = {"toolchains": ["rust@1", "node"], "test_file_command": "npm test", "install_command": "npm ci # all",
               "code_paths": ["../x"], "deploy": {"cloud": "oracle", "iac_dir": "/abs"}}
        text = " ".join(ip.validate_stack(bad))
        for frag in ("has no preset", "must look like <name>@<version>", "test_command is required", "must contain {file}",
                     "one line without '#'", "relative paths inside the repo", "deploy.cloud must be one of",
                     "deploy.iac_dir must be a relative path"):
            self.assertIn(frag, text)

    def test_stack_dry_run_and_rejection(self):
        self.run_init()
        good = self.root / "good.json"
        good.write_text(json.dumps({"toolchains": ["python@3.12"], "test_command": "pytest -q", "decided": True}), encoding="utf-8")
        before = self.read(".sdlc/build.yaml")
        r = subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--stack", str(good), "--dry-run"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(".sdlc/build.yaml"), before, "--dry-run writes nothing")
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"toolchains": ["cobol@1"]}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--stack", str(bad)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read(".sdlc/build.yaml"), before, "an invalid stack is never written")

    def check_files(self):
        return subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--check-stack-files"],
                              capture_output=True, text=True)

    def test_check_stack_files(self):
        self.run_init()
        self.assertEqual(self.check_files().returncode, 0, "an undecided stack (as init writes it) is fine")
        stack = self.root / "s.json"
        stack.write_text(json.dumps({"toolchains": ["node@24"], "test_command": "npm test",
                                     "test_file_command": "npm test -- {file}"}), encoding="utf-8")
        subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--stack", str(stack)], check=True, capture_output=True)
        self.assertEqual(self.check_files().returncode, 0, self.check_files().stderr)
        # A tech lead's hand edits in the stack PR.
        build = self.root / ".sdlc" / "build.yaml"
        build.write_text(build.read_text(encoding="utf-8").replace("toolchains: [node@24]", "toolchains: [nodejs@24]"), encoding="utf-8")
        deploy = self.root / ".sdlc" / "deploy.yaml"
        deploy.write_text(deploy.read_text(encoding="utf-8").replace("cloud: none", "cloud: oracle"), encoding="utf-8")
        r = self.check_files()
        self.assertEqual(r.returncode, 1)
        self.assertIn(".sdlc/build.yaml: toolchain 'nodejs@24' has no preset", r.stderr)
        self.assertIn(".sdlc/deploy.yaml: cloud must be one of", r.stderr)

    def fake_gh(self, variables=None, secrets=(), login="lead"):
        def run(cmd, **kw):
            out, code = "", 0
            if cmd[:3] == ["gh", "repo", "view"]:
                out = json.dumps({"nameWithOwner": "acme/app", "defaultBranchRef": {"name": "trunk"}})
            elif cmd[:3] == ["gh", "api", "user"]:
                out = json.dumps({"login": login})
            elif cmd[:3] == ["gh", "variable", "list"]:
                out = json.dumps([{"name": k, "value": v} for k, v in (variables or {}).items()])
            elif cmd[:3] == ["gh", "secret", "list"]:
                out = json.dumps([{"name": s} for s in secrets])
            elif cmd[:2] == ["git", "ls-remote"]:
                out = "a\trefs/tags/v0.9.0\nb\trefs/tags/v0.14.0\nc\trefs/tags/v0.10.0\n"
            return subprocess.CompletedProcess(cmd, code, out, "")
        return run

    def test_discover_finds_jira_and_subscription(self):
        found = ip.discover(self.root, self.fake_gh(
            {"JIRA_BASE_URL": "https://acme.atlassian.net/", "JIRA_USER_EMAIL": "a@x", "SDLC_APP_ID": "1"},
            ["CLAUDE_CODE_OAUTH_TOKEN", "JIRA_API_TOKEN", "SDLC_APP_PRIVATE_KEY"]))
        self.assertEqual((found["repo"], found["base_branch"], found["sdlc_ref"], found["owner"]),
                         ("acme/app", "trunk", "v0.14.0", "@lead"))
        self.assertEqual(found["jira"], {"enabled": True, "site": "acme.atlassian.net", "space_key": None})
        self.assertEqual((found["claude_auth"], found["models"]), ("subscription", {"build": "claude-sonnet-5"}))
        self.assertEqual(found["missing"], [])

    def test_discover_lists_what_is_missing(self):
        found = ip.discover(self.root, self.fake_gh({"JIRA_BASE_URL": "https://acme.atlassian.net"}, ["ANTHROPIC_API_KEY"]))
        self.assertEqual(found["claude_auth"], "api_key")
        self.assertEqual(found["models"], {}, "an API key keeps the default models")
        self.assertEqual(found["missing"], ["SDLC_APP_ID", "JIRA_USER_EMAIL", "SDLC_APP_PRIVATE_KEY", "JIRA_API_TOKEN"])
        bare = ip.discover(self.root, self.fake_gh())
        self.assertFalse(bare["jira"]["enabled"])
        self.assertIn("ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN", bare["missing"])

    def test_discover_without_gh(self):
        def broken(cmd, **kw):
            raise OSError("gh not found")
        found = ip.discover(self.root, broken)
        self.assertEqual((found["repo"], found["sdlc_ref"], found["base_branch"]), (None, None, "main"))

    def test_rerun_turns_jira_on(self):
        self.run_init({**ANSWERS, "jira": {"enabled": False}})
        self.assertIn("enabled: false", self.read(".sdlc/jira.yaml"))
        owners_before = self.read(".sdlc/owners.yaml")
        self.run_init({**ANSWERS, "jira": {"enabled": True, "site": "acme.atlassian.net", "space_key": "ACM"}})
        jira = self.read(".sdlc/jira.yaml")
        self.assertIn("enabled: true", jira)
        self.assertIn("space_key: ACM", jira)
        self.assertEqual(self.read(".sdlc/owners.yaml"), owners_before, "other create-once files are kept")
        # An upgrade (no Jira answer) never touches jira.yaml.
        (self.root / ".sdlc" / "jira.yaml").write_text("enabled: true\nsite: acme.atlassian.net\nspace_key: ACM\n# my note\n", encoding="utf-8")
        subprocess.run([sys.executable, str(INIT), "--root", str(self.root), "--upgrade", "v0.6.1"], check=True, capture_output=True)
        self.assertIn("# my note", self.read(".sdlc/jira.yaml"))

    def test_toolchains_match_setup_stack(self):
        spec = importlib.util.spec_from_file_location("stack", ROOT / ".github" / "actions" / "setup-stack" / "stack.py")
        st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(st)
        self.assertEqual(ip.TOOLCHAINS, st.SUPPORTED)

    def test_workflows_setting(self):
        self.run_init()
        self.assertEqual(json.loads(self.read(".sdlc/sdlc.json"))["workflows"], "auto")
        self.assertIn("Claude Code workflows", self.read("CLAUDE.md"))
        _, errors = ip.normalize({**ANSWERS, "workflows": "sometimes"})
        self.assertIn("workflows must be auto, always or off", errors)

    def test_auto_build_off(self):
        self.run_init({**ANSWERS, "auto_build": False})
        push = self.read(".github/workflows/sdlc-push.yml")
        self.assertNotIn("sdlc-build.yml", push)
        self.assertNotIn(", build,", push)
        self.assertIn("`/sdlc:build-story <KEY>` | `plans/", self.read("CLAUDE.md"))

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
