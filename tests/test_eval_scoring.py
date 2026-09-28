"""Offline tests for evals/run_evals.py scoring: fake the skill's output, no API calls."""
import importlib.util
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals" / "run_evals.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

CASES = ROOT / "evals" / "write-intent" / "cases"
OWNERS = ROOT / "plugins" / "sdlc" / "skills" / "write-intent" / "examples" / "owners.yaml"
EXAMPLE = ROOT / "plugins" / "sdlc" / "skills" / "write-intent" / "examples" / "claims-status-self-service.md"


class ScoreTest(unittest.TestCase):
    def workspace(self, case):
        case_dir = CASES / case
        ws = ev.setup_workspace(case_dir, OWNERS)
        self.addCleanup(shutil.rmtree, ws, True)
        return ws, ev.snapshot(ws), ev.load_case(case_dir)["expect"]

    def test_good_output_passes(self):
        ws, before, expect = self.workspace("jira-claims-status")
        shutil.copy(EXAMPLE, ws / "intent" / EXAMPLE.name)
        self.assertEqual(ev.score(ws, before, OWNERS, expect), [])

    def test_wrong_owner_fails(self):
        ws, before, expect = self.workspace("jira-claims-status")
        text = EXAMPLE.read_text(encoding="utf-8").replace('"@claims-po"', '"@portal-po"')
        (ws / "intent" / EXAMPLE.name).write_text(text, encoding="utf-8")
        fails = ev.score(ws, before, OWNERS, expect)
        self.assertTrue(any("frontmatter owner" in f for f in fails), fails)

    def test_write_outside_allowed_paths_fails(self):
        ws, before, expect = self.workspace("jira-claims-status")
        shutil.copy(EXAMPLE, ws / "intent" / EXAMPLE.name)
        (ws / ".sdlc" / "owners.yaml").write_text("tampered", encoding="utf-8")
        fails = ev.score(ws, before, OWNERS, expect)
        self.assertTrue(any("outside allowed paths" in f for f in fails), fails)

    def test_no_output_fails(self):
        ws, before, expect = self.workspace("jira-claims-status")
        self.assertTrue(ev.score(ws, before, OWNERS, expect))

    def test_duplicate_case(self):
        ws, before, expect = self.workspace("duplicate-fingerprint")
        (ws / ".sdlc-output" / "duplicate.txt").write_text("intent/p95-latency-claims-api.md\n", encoding="utf-8")
        self.assertEqual(ev.score(ws, before, OWNERS, expect), [])

    def test_duplicate_case_with_new_intent_fails(self):
        ws, before, expect = self.workspace("duplicate-fingerprint")
        shutil.copy(EXAMPLE, ws / "intent" / EXAMPLE.name)
        self.assertTrue(ev.score(ws, before, OWNERS, expect))

    def test_any_of_and_not(self):
        self.assertTrue(ev.matches("high", ["medium", "high"]))
        self.assertFalse(ev.matches("low", ["medium", "high"]))
        self.assertTrue(ev.matches("x", "x"))

    def test_fixtures_are_consistent(self):
        self.assertEqual(ev.check_fixtures(sorted(p for p in CASES.iterdir() if p.is_dir()), OWNERS), [])


if __name__ == "__main__":
    unittest.main()
