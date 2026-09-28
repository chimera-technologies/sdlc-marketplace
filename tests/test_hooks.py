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
        return run_hook("validate_intent_on_write.py", event, self.project)

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

    def test_other_files_ignored(self):
        for rel in ["README.md", "intent/sub/x.md", "intent/notes.txt", "specs/x.md"]:
            p = self.project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("anything", encoding="utf-8")
            self.assertEqual(self.validate(p).returncode, 0, rel)


if __name__ == "__main__":
    unittest.main()
