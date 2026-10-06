"""Tests for plugins/sdlc/hooks/*.py, run as subprocesses the way Claude Code calls them."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "plugins" / "sdlc" / "hooks"
SKILL = ROOT / "plugins" / "sdlc" / "skills" / "write-intent"
EXAMPLE = SKILL / "examples" / "claims-status-self-service.md"


def run_hook(script, event, project, **env):
    full_env = {k: v for k, v in os.environ.items() if k not in ("SDLC_HEADLESS", "SDLC_WRITE_ALLOW")}
    full_env.update(CLAUDE_PROJECT_DIR=str(project), **env)
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(event), capture_output=True, text=True, env=full_env,
    )


def write_event(path, tool="Write"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"file_path": str(path)}}


class HookTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name).resolve()
        (self.project / "intent").mkdir()
        (self.project / ".sdlc").mkdir()
        shutil.copy(SKILL / "examples" / "owners.yaml", self.project / ".sdlc" / "owners.yaml")


class HeadlessWriteGuardTest(HookTestBase):
    def guard(self, path, **env):
        return run_hook("headless_write_guard.py", write_event(path), self.project, **env)

    def test_interactive_is_never_blocked(self):
        self.assertEqual(self.guard(self.project / "src" / "app.py").returncode, 0)

    def test_headless_allows_intent_and_output(self):
        self.assertEqual(self.guard(self.project / "intent" / "x.md", SDLC_HEADLESS="1").returncode, 0)
        self.assertEqual(self.guard(".sdlc-output/duplicate.txt", SDLC_HEADLESS="1").returncode, 0)

    def test_headless_blocks_other_paths(self):
        for p in [self.project / ".sdlc-output" / "validate_intent.py",self.project / ".github" / "workflows" / "x.yml", self.project / ".sdlc" / "owners.yaml",
                  self.project / "intentional.md", self.project / "intent" / ".." / "CLAUDE.md"]:
            r = self.guard(p, SDLC_HEADLESS="1")
            self.assertEqual(r.returncode, 2, p)
            self.assertIn("Blocked", r.stderr)

    def test_headless_blocks_outside_project(self):
        self.assertEqual(self.guard(Path(tempfile.gettempdir()) / "evil.sh", SDLC_HEADLESS="1").returncode, 2)

    def test_custom_allow_list(self):
        env = dict(SDLC_HEADLESS="1", SDLC_WRITE_ALLOW="specs/,.sdlc-output/")
        self.assertEqual(self.guard(self.project / "specs" / "a.md", **env).returncode, 0)
        self.assertEqual(self.guard(self.project / "intent" / "a.md", **env).returncode, 2)

    def test_allow_anywhere_with_a_deny_list(self):
        # The headless Build: code anywhere, never the SDLC's own files.
        env = dict(SDLC_HEADLESS="1", SDLC_WRITE_ALLOW="*", SDLC_WRITE_DENY=".github/,.sdlc/,plans/,CLAUDE.md")
        for ok in [self.project / "src" / "app.ts", self.project / "package.json", self.project / "tests" / "a.spec.ts"]:
            self.assertEqual(self.guard(ok, **env).returncode, 0, ok)
        for bad in [self.project / ".github" / "workflows" / "x.yml", self.project / ".sdlc" / "build.yaml",
                    self.project / "plans" / "a.md", self.project / "CLAUDE.md", self.project / "src" / ".." / "CLAUDE.md"]:
            r = self.guard(bad, **env)
            self.assertEqual(r.returncode, 2, bad)
            self.assertIn("may not write", r.stderr)
        self.assertEqual(self.guard(Path(tempfile.gettempdir()) / "evil.sh", **env).returncode, 2)

    def test_notebook_path(self):
        event = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(self.project / "x.ipynb")}}
        r = run_hook("headless_write_guard.py", event, self.project, SDLC_HEADLESS="1")
        self.assertEqual(r.returncode, 2)

    def test_bad_input_blocks_in_headless(self):
        r = subprocess.run([sys.executable, str(HOOKS / "headless_write_guard.py")], input="not json",
                           capture_output=True, text=True, env={**os.environ, "SDLC_HEADLESS": "1"})
        self.assertEqual(r.returncode, 2)


class ValidateOnWriteTest(HookTestBase):
    def validate(self, path):
        event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(path)}}
        return run_hook("validate_on_write.py", event, self.project)

    def test_valid_intent_passes(self):
        target = self.project / "intent" / EXAMPLE.name
        shutil.copy(EXAMPLE, target)
        self.assertEqual(self.validate(target).returncode, 0)

    def test_invalid_intent_is_sent_back(self):
        target = self.project / "intent" / EXAMPLE.name
        target.write_text(EXAMPLE.read_text(encoding="utf-8").replace('"@claims-po"', '"@nobody"'), encoding="utf-8")
        r = self.validate(target)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not listed in owners file", r.stderr)

    def test_relative_path(self):
        (self.project / "intent" / "bad.md").write_text("no frontmatter", encoding="utf-8")
        self.assertEqual(self.validate("intent/bad.md").returncode, 2)

    def test_valid_spec_passes_and_invalid_is_sent_back(self):
        skills = ROOT / "plugins" / "sdlc" / "skills"
        shutil.copy(EXAMPLE, self.project / "intent" / EXAMPLE.name)
        (self.project / "specs").mkdir()
        spec = self.project / "specs" / EXAMPLE.name
        shutil.copy(skills / "write-spec" / "examples" / EXAMPLE.name, spec)
        self.assertEqual(self.validate(spec).returncode, 0)
        spec.write_text(spec.read_text(encoding="utf-8").replace("## Design", "## How"), encoding="utf-8")
        r = self.validate(spec)
        self.assertEqual(r.returncode, 2)
        self.assertIn("validate_spec.py", r.stderr)

    def test_other_files_ignored(self):
        for rel in ["README.md", "intent/sub/x.md", "intent/notes.txt", "specs/notes.txt", "docs/x.md"]:
            p = self.project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("anything", encoding="utf-8")
            self.assertEqual(self.validate(p).returncode, 0, rel)


class PlanValidateOnWriteTest(HookTestBase):
    def test_invalid_plan_is_sent_back(self):
        (self.project / "plans").mkdir()
        plan = self.project / "plans" / "x-s1.md"
        plan.write_text("no frontmatter", encoding="utf-8")
        event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(plan)}}
        r = run_hook("validate_on_write.py", event, self.project)
        self.assertEqual(r.returncode, 2)
        self.assertIn("validate_plan.py", r.stderr)


# A real-looking key built at run time, so this file never holds one.
FAKE_AWS = "AKIA" + "Q7LMZ2RT5V3WN8KD"


class CodeHooksTest(HookTestBase):
    """code_hooks.py: secrets, lock files, dangerous commands, format and lint, graph freshness."""

    def setUp(self):
        super().setUp()
        (self.project / ".sdlc" / "build.yaml").write_text("code_paths: [src/, tests/]\ntest_command: x\n",
                                                          encoding="utf-8")
        (self.project / "src").mkdir()

    def hook(self, mode, tool_input, tool="Write", **env):
        event = {"hook_event_name": "x", "tool_name": tool, "tool_input": tool_input}
        full_env = {k: v for k, v in os.environ.items() if k != "SDLC_HEADLESS"}
        full_env.update(CLAUDE_PROJECT_DIR=str(self.project), **env)
        return subprocess.run([sys.executable, str(HOOKS / "code_hooks.py"), mode], input=json.dumps(event),
                              capture_output=True, text=True, env=full_env)

    def bash(self, command):
        return self.hook("pre-bash", {"command": command}, tool="Bash")

    # pre-write
    def test_secrets_are_blocked_in_every_write_tool(self):
        cases = [({"file_path": "src/a.ts", "content": f'const key = "{FAKE_AWS}";'}, "Write"),
                 ({"file_path": "src/a.ts", "old_string": "x", "new_string": "-----BEGIN RSA PRIVATE KEY-----"}, "Edit"),
                 ({"file_path": "src/a.ts", "edits": [{"old_string": "a", "new_string": "ghp_" + "a1" * 18}]}, "MultiEdit")]
        for tool_input, tool in cases:
            r = self.hook("pre-write", tool_input, tool=tool)
            self.assertEqual(r.returncode, 2, tool)
            self.assertIn("looks like", r.stderr)

    def test_placeholders_and_plain_code_pass(self):
        for content in ['const key = "AKIAIOSFODNN7EXAMPLE";', "export const add = (a, b) => a + b;",
                        "const t = process.env.API_TOKEN;"]:
            self.assertEqual(self.hook("pre-write", {"file_path": "src/a.ts", "content": content}).returncode, 0, content)

    def test_lock_files_and_dependency_folders_are_blocked(self):
        for rel in ["package-lock.json", "sub/poetry.lock", "node_modules/x/index.js", "app/.venv/lib/a.py"]:
            r = self.hook("pre-write", {"file_path": rel, "content": "{}"})
            self.assertEqual(r.returncode, 2, rel)
        self.assertEqual(self.hook("pre-write", {"file_path": "package.json", "content": "{}"}).returncode, 0)

    def test_repos_without_sdlc_are_untouched(self):
        shutil.rmtree(self.project / ".sdlc")
        self.assertEqual(self.hook("pre-write", {"file_path": "package-lock.json", "content": "{}"}).returncode, 0)
        self.assertEqual(self.bash("terraform apply").returncode, 0)

    # pre-bash
    def test_dangerous_commands_are_blocked(self):
        for command in ["terraform apply -auto-approve", "terraform -chdir=infra destroy", "kubectl -n app apply -f k8s/",
                        "kubectl delete pod x", "helm upgrade --install app charts/app", "git push --force origin story/x",
                        "git push -f", "git push origin main", "git push origin HEAD:main", "git commit -m x --no-verify",
                        "git commit -nm x", "rm -rf /", "rm -rf ~", "cd x && terraform apply"]:
            r = self.bash(command)
            self.assertEqual(r.returncode, 2, command)
            self.assertIn("Blocked by the SDLC code hooks", r.stderr)

    def test_safe_commands_pass(self):
        for command in ["terraform plan", "terraform validate", "kubectl get pods", "kubectl describe deploy edit-svc",
                        "helm template charts/app", "git push -u origin story/scrum-1-x",
                        "git push --force-with-lease origin story/x", "git commit -m 'main fix'", "rm -rf dist",
                        "npm test", "git push origin maintenance"]:
            self.assertEqual(self.bash(command).returncode, 0, command)

    def test_base_branch_comes_from_sdlc_json(self):
        (self.project / ".sdlc" / "sdlc.json").write_text('{"base_branch": "trunk"}', encoding="utf-8")
        self.assertEqual(self.bash("git push origin trunk").returncode, 2)
        self.assertEqual(self.bash("git push origin main").returncode, 0)

    def test_graph_query_tries_to_refresh_a_stale_graph(self):
        (self.project / "graphify-out").mkdir()
        (self.project / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
        (self.project / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
        (self.project / "graphify-out" / "STALE").write_text("src/a.ts\n", encoding="utf-8")
        r = self.bash('graphify query "where is the loader"')
        self.assertEqual(r.returncode, 0)
        self.assertIn("graphify:", r.stderr)   # updated, or left stale with the reason; never blocked

    # post-write
    def write_code(self, rel="src/a.ts", text="export {}\n"):
        (self.project / rel).write_text(text, encoding="utf-8")
        return self.hook("post-write", {"file_path": rel})

    def tool(self, name, body):
        script = self.project / f"{name}.py"
        script.write_text(body, encoding="utf-8")
        # Unquoted, with forward slashes: build.yaml values are not shell-quoted.
        return f"{Path(sys.executable).as_posix()} {name}.py {{file}}"

    def test_lint_errors_go_back_to_claude(self):
        lint = self.tool("lint", "import sys\nprint(f'{sys.argv[1]}:1 no-unused-vars')\nsys.exit(1)\n")
        with open(self.project / ".sdlc" / "build.yaml", "a", encoding="utf-8") as fh:
            fh.write(f"lint_command: {lint}\n")
        r = self.write_code()
        self.assertEqual(r.returncode, 2)
        self.assertIn("lint_command found problems in src/a.ts", r.stderr)
        self.assertIn("src/a.ts:1 no-unused-vars", r.stderr)

    def test_a_linter_that_is_not_installed_does_not_block(self):
        missing_script = self.tool("lint", "import sys\nprint('npm error Missing script: lint')\nsys.exit(1)\n")
        for lint in ("no-such-linter-xyz {file}", missing_script):
            (self.project / ".sdlc" / "build.yaml").write_text(
                f"code_paths: [src/]\ntest_command: x\nlint_command: {lint}\n", encoding="utf-8")
            r = self.write_code()
            self.assertEqual(r.returncode, 0, lint)
            self.assertIn("could not run", r.stderr)

    def test_format_runs_first_and_clean_lint_passes(self):
        fmt = self.tool("fmt", "import sys, pathlib\np = pathlib.Path(sys.argv[1])\np.write_text(p.read_text().strip() + '\\n')\n")
        lint = self.tool("lint", "import sys\nsys.exit(0)\n")
        with open(self.project / ".sdlc" / "build.yaml", "a", encoding="utf-8") as fh:
            fh.write(f"format_command: {fmt}\nlint_command: {lint}\n")
        r = self.write_code(text="  export {}  \n\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.project / "src" / "a.ts").read_text(encoding="utf-8"), "export {}\n")

    def test_code_writes_mark_the_graph_stale_once(self):
        self.write_code()
        self.assertFalse((self.project / "graphify-out" / "STALE").exists(), "no preflight yet: nothing to mark")
        (self.project / "graphify-out").mkdir()
        (self.project / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
        self.write_code()
        self.write_code()
        self.write_code("src/b.ts")
        self.assertEqual((self.project / "graphify-out" / "STALE").read_text(encoding="utf-8"), "src/a.ts\nsrc/b.ts\n")

    def test_files_outside_code_paths_are_ignored(self):
        (self.project / "graphify-out").mkdir()
        (self.project / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
        (self.project / "README.md").write_text("x", encoding="utf-8")
        self.assertEqual(self.hook("post-write", {"file_path": "README.md"}).returncode, 0)
        self.assertFalse((self.project / "graphify-out" / "STALE").exists())

    # stop
    def test_stop_skips_headless_runs(self):
        (self.project / "graphify-out").mkdir()
        (self.project / "graphify-out" / "STALE").write_text("src/a.ts\n", encoding="utf-8")
        r = self.hook("stop", {}, SDLC_HEADLESS="1")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue((self.project / "graphify-out" / "STALE").exists())

    def test_hooks_json_wires_every_mode(self):
        hooks = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        commands = json.dumps(hooks)
        for mode in ("pre-write", "pre-bash", "post-write", "stop"):
            self.assertIn(f"code_hooks.py\\\" {mode}", commands)
        self.assertIn("Stop", hooks)
        self.assertTrue(any(e.get("matcher") == "Bash" for e in hooks["PreToolUse"]))


if __name__ == "__main__":
    unittest.main()
