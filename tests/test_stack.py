"""Tests for .github/actions/setup-stack/stack.py (the stack the Test stage installs)."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / ".github" / "actions" / "setup-stack" / "stack.py"

_spec = importlib.util.spec_from_file_location("stack", STACK)
stack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stack)


class StackTest(unittest.TestCase):
    def repo(self, build_yaml):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / ".sdlc").mkdir()
        (root / ".sdlc" / "build.yaml").write_text(build_yaml, encoding="utf-8")
        return root

    def test_node_python_java(self):
        root = self.repo("toolchains: [node@22, python@3.12, java@21]\n"
                         "install_command: npm ci\ntest_command: npx playwright test\n"
                         "report_path: playwright-report/   # comment\n")
        out, errors = stack.read_stack(root)
        self.assertEqual(errors, [])
        self.assertEqual((out["node"], out["python"], out["java"], out["dotnet"]), ("22", "3.12", "21", ""))
        self.assertEqual(out["java_distribution"], "temurin")
        self.assertEqual(out["test_command"], "npx playwright test")
        self.assertEqual(out["report_path"], "playwright-report/")

    def test_dotnet_and_go(self):
        out, errors = stack.read_stack(self.repo("toolchains: [dotnet@8.0, go@1.23]\ntest_command: dotnet test\n"))
        self.assertEqual(errors, [])
        self.assertEqual((out["dotnet"], out["go"]), ("8.0", "1.23"))

    def test_unknown_toolchain_points_to_setup_command(self):
        _, errors = stack.read_stack(self.repo("toolchains: [rust@1.80]\n"))
        self.assertTrue(any("setup_command" in e for e in errors))

    def test_toolchain_needs_version(self):
        _, errors = stack.read_stack(self.repo("toolchains: [go]\n"))
        self.assertTrue(any("needs a version" in e for e in errors))

    def test_no_build_yaml_is_empty_stack(self):
        with tempfile.TemporaryDirectory() as d:
            out, errors = stack.read_stack(d)
        self.assertEqual(errors, [])
        self.assertEqual(out["test_command"], "")

    def test_cli_writes_github_output_and_requires_tests(self):
        root = self.repo("toolchains: [python@3.12]\n")
        env = {**os.environ}
        with tempfile.NamedTemporaryFile("r", delete=False, suffix=".txt") as fh:
            env["GITHUB_OUTPUT"] = fh.name
        self.addCleanup(os.unlink, env["GITHUB_OUTPUT"])
        r = subprocess.run([sys.executable, str(STACK), "--root", str(root)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("python=3.12", Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8"))
        r = subprocess.run([sys.executable, str(STACK), "--root", str(root), "--require-tests"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no test_command", r.stderr)


if __name__ == "__main__":
    unittest.main()
