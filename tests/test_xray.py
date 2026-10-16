"""Tests for xray_sync.py: a story's planned tests and each run's results in Xray."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
SCRIPT = PLUGIN / "skills" / "build-story" / "scripts" / "xray_sync.py"
PLAN = PLUGIN / "skills" / "build-story" / "examples" / "claims-status-self-service-s1.md"
WORKFLOWS = ROOT / ".github" / "workflows"

spec = importlib.util.spec_from_file_location("xray_sync", SCRIPT)
xs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xs)

FINDINGS = ("\n## Review findings\n| ID | Finding | Handling | Test |\n|---|---|---|---|\n"
            '| EC-1 | Customer with two accounts | merge by customer ID | tests/api/t.py › "S1 EC-1: two accounts" |\n'
            "| BUG-1 | Leaks ids | Decision needed: should admins see them? | none |\n\n")

# A Vitest-style file (describe path in the name) and a Playwright-style file (one suite per browser).
VITEST = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="tests/api/t.test.ts" tests="4">
  <testcase classname="tests/api/t.test.ts" name="S1 claims &gt; S1 AC-1: only the customer's own claims" time="0.01"/>
  <testcase classname="tests/api/t.test.ts" name="S1 claims &gt; S1 AC-2: status codes, never internal states" time="0.02">
    <failure message="expected 'OPEN' to be 'Open'" type="AssertionError">at t.test.ts:12</failure>
  </testcase>
  <testcase classname="tests/api/t.test.ts" name="S1 claims &gt; S1 EC: an empty list is fine" time="0.01"/>
  <testcase classname="tests/api/t.test.ts" name="S10 AC-1: another story" time="0.01"/>
</testsuite></testsuites>"""
PLAYWRIGHT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
 <testsuite name="claims.spec.ts" hostname="chromium" tests="1">
  <testcase name="S1 AC-3: access logged without claim content" classname="claims.spec.ts">
   <system-out>[[ATTACHMENT|{root}/test-results/claims-S1-AC-3-chromium/test-finished-1.png]]</system-out>
  </testcase>
 </testsuite>
 <testsuite name="claims.spec.ts" hostname="firefox" tests="1">
  <testcase name="S1 AC-3: access logged without claim content" classname="claims.spec.ts">
   <failure message="timed out">waiting for the log line</failure>
   <system-out>[[ATTACHMENT|/elsewhere/runner/repo/test-results/claims-S1-AC-3-firefox/test-failed-1.png]]</system-out>
  </testcase>
 </testsuite>
 <testsuite name="claims.spec.ts" hostname="webkit" tests="1">
  <testcase name="S1 EC-1: two accounts" classname="claims.spec.ts"><skipped/></testcase>
 </testsuite>
</testsuites>"""


class XrayTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "plans").mkdir()
        text = PLAN.read_text(encoding="utf-8").replace("## Steps", FINDINGS + "## Steps")
        self.plan_path = self.root / "plans" / PLAN.name
        self.plan_path.write_text(text, encoding="utf-8")
        self.plan = xs.read_plan(self.plan_path)
        for browser in ("chromium", "firefox"):
            d = self.root / "test-results" / f"claims-S1-AC-3-{browser}"
            d.mkdir(parents=True)
            name = "test-finished-1.png" if browser == "chromium" else "test-failed-1.png"
            (d / name).write_bytes(b"\x89PNG fake " + browser.encode())
        (self.root / ".sdlc-results").mkdir()
        (self.root / ".sdlc-results" / "unit.xml").write_text(VITEST, encoding="utf-8")
        (self.root / ".sdlc-results" / "e2e.xml").write_text(PLAYWRIGHT.replace("{root}", self.root.as_posix()),
                                                             encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)

    def results(self):
        return xs.parse_junit(sorted(str(p) for p in (self.root / ".sdlc-results").glob("*.xml")), "S1")

    def test_plan_lists_every_planned_case_except_open_decisions(self):
        self.assertEqual(self.plan["jira"], "CLM-483")
        self.assertEqual([c["id"] for c in self.plan["cases"]], ["AC-1", "AC-2", "AC-3", "EC-1"])

    def test_planned_execution_creates_linked_generic_tests_at_todo(self):
        payload = xs.execution_payload(self.plan, {}, "planned tests", planned=True, test_plan="CLM-900")
        self.assertEqual(payload["info"]["project"], "CLM")
        self.assertEqual(payload["info"]["testPlanKey"], "CLM-900")
        self.assertIn("planned, not run yet", payload["info"]["summary"])
        first = payload["tests"][0]
        self.assertEqual(first["status"], "TODO")
        self.assertEqual(first["testInfo"]["type"], "Generic")
        self.assertEqual(first["testInfo"]["requirementKeys"], ["CLM-483"])
        self.assertEqual(first["testInfo"]["definition"], "claims-status-self-service-s1 S1 AC-1")
        self.assertTrue(first["testInfo"]["summary"].startswith("S1 AC-1: "))

    def test_junit_results_are_merged_per_test_across_files_and_browsers(self):
        res = self.results()
        self.assertEqual(res["AC-1"]["status"], "PASSED")
        self.assertEqual(res["AC-2"]["status"], "FAILED")
        self.assertIn("expected 'OPEN' to be 'Open'", res["AC-2"]["messages"][0])
        self.assertEqual((res["AC-3"]["status"], res["AC-3"]["runs"]), ("FAILED", 2))
        self.assertIn("[firefox] timed out", res["AC-3"]["messages"][0])
        self.assertEqual(res["EC-1"]["status"], "TODO", "skipped everywhere = not run")
        self.assertIn("S1 EC: an empty list is fine", res)
        self.assertFalse(any(k.startswith("S10") for k in res), "another story's tests are left out")

    def test_results_execution_has_statuses_comments_and_screenshots(self):
        payload = xs.execution_payload(self.plan, self.results(), "PR #30", revision="abc123",
                                       run_url="https://ci/run/1")
        tests = {t["testInfo"]["definition"].rsplit(" ", 1)[-1] if re.search(r"(AC|EC|BUG)-\d+$", t["testInfo"]["definition"])
                 else t["testInfo"]["summary"]: t for t in payload["tests"]}
        self.assertEqual(tests["AC-1"]["status"], "PASSED")
        self.assertEqual(tests["AC-2"]["status"], "FAILED")
        ev = tests["AC-3"]["evidence"]
        self.assertEqual(sorted(e["filename"] for e in ev), ["chromium-test-finished-1.png", "firefox-test-failed-1.png"],
                         "both browsers' screenshots, the firefox one found from another runner's path")
        self.assertEqual(ev[0]["contentType"], "image/png")
        self.assertIn("S1 EC: an empty list is fine", tests, "unplanned story tests are recorded too")
        self.assertEqual(payload["info"]["revision"], "abc123")
        self.assertIn("2 passed, 2 failed of 5", payload["info"]["summary"])
        self.assertIn("https://ci/run/1", payload["info"]["description"])

    def test_a_planned_test_that_did_not_run_is_todo_with_a_reason(self):
        payload = xs.execution_payload(self.plan, {}, "PR #30")
        self.assertTrue(all(t["status"] == "TODO" for t in payload["tests"]))
        self.assertEqual(payload["tests"][0]["comment"], "No test with this name ran.")

    def test_evidence_skips_non_images_large_files_and_missing_ones(self):
        (self.root / "trace.zip").write_bytes(b"zip")
        big = self.root / "big.png"
        big.write_bytes(b"0" * (xs.MAX_EVIDENCE_BYTES + 1))
        items = [("trace.zip", "chromium"), (str(big), "chromium"), ("/nowhere/x.png", "webkit")]
        self.assertEqual(xs.evidence(items), [])

    def test_cli_skips_without_xray_and_dry_run_hides_the_images(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("XRAY_")}
        r = subprocess.run([sys.executable, str(SCRIPT), "plan", "--plan", str(self.plan_path)],
                           capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Xray not configured", r.stdout)
        r = subprocess.run([sys.executable, str(SCRIPT), "results", "--plan", str(self.plan_path), "--junit",
                            ".sdlc-results/*.xml", "--label", "PR #30", "--dry-run"],
                           capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        payload = json.loads(r.stdout)
        self.assertTrue(any("base64 chars" in e["data"] for t in payload["tests"] for e in t.get("evidence", [])))

    def test_api_errors_are_warnings_never_failures(self):
        with mock.patch.dict(os.environ, {"XRAY_CLIENT_ID": "id", "XRAY_CLIENT_SECRET": "secret",
                                          "JIRA_BASE_URL": "", "JIRA_USER_EMAIL": "", "JIRA_API_TOKEN": ""}), \
                mock.patch.object(xs.Xray, "__init__", side_effect=SystemExit("Xray /api/v2/authenticate: HTTP 401")), \
                mock.patch("sys.stdout") as out:
            self.assertEqual(xs.main(["plan", "--plan", str(self.plan_path)]), 0)
        self.assertIn("HTTP 401", "".join(str(c) for c in out.write.call_args_list))


class XrayWiringTest(unittest.TestCase):
    def wf(self, name):
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_secrets_are_declared_and_optional(self):
        for name in ("sdlc-build.yml", "sdlc-pr.yml", "sdlc-main-tests.yml"):
            text = self.wf(name)
            for secret in ("XRAY_CLIENT_ID", "XRAY_CLIENT_SECRET"):
                self.assertRegex(text, rf"      {secret}:\n(?:        .*\n)*?        required: false", name)

    def test_steps_run_only_with_xray_and_never_block(self):
        build = self.wf("sdlc-build.yml")
        self.assertIn('xray_sync.py" plan --plan "$PLAN"', build)
        pr = self.wf("sdlc-pr.yml")
        self.assertIn("needs.config.outputs.story == 'true' && env.XRAY_CLIENT_ID != ''", pr)
        self.assertIn('--label "PR #$PR"', pr)
        main = self.wf("sdlc-main-tests.yml")
        self.assertIn("sdlc-test-results-${{ github.run_id }}", main)
        self.assertIn('--label "main, after PR #$NUMBER"', main)
        for text in (build, pr, main):
            for block in text.split("- name: ")[1:]:
                if "xray_sync.py" in block:
                    self.assertIn("continue-on-error: true", block)
                    self.assertIn("XRAY_CLIENT_ID != ''", block)

    def test_init_passes_the_secrets_only_to_the_workflows_that_declare_them(self):
        ip = importlib.util.module_from_spec(spec_init := importlib.util.spec_from_file_location(
            "init_project", PLUGIN / "skills" / "init" / "scripts" / "init_project.py"))
        spec_init.loader.exec_module(ip)
        a, _ = ip.normalize({"sdlc_ref": "v1.0.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        files = ip.render_callers(a)
        for rel, text in files.items():
            for job in re.split(r"\n(?=  [a-z-]+:\n)", text):
                uses = re.search(r"workflows/(sdlc-[a-z-]+\.yml)@", job)
                if not uses:
                    continue
                passes = "XRAY_CLIENT_ID" in job
                declares = "XRAY_CLIENT_ID" in self.wf(uses.group(1))
                self.assertEqual(passes, declares, f"{rel}: {uses.group(1)}")


if __name__ == "__main__":
    unittest.main()
