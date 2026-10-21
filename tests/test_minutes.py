"""Actions minutes: jobs start only where they have work, and can run on a self-hosted runner (v0.26.0)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
INIT = ROOT / "plugins" / "sdlc" / "skills" / "init" / "scripts" / "init_project.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ip = load("init_project", INIT)
OWNERS = {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}


def callers(**extra):
    a, _ = ip.normalize({"sdlc_ref": "v1.0.0", "owners": OWNERS, **extra})
    return ip.render_callers(a)


def job(text, name):
    return text.split(f"\n  {name}:\n", 1)[1].split("\n\n  ", 1)[0]


class RunnerTest(unittest.TestCase):
    def test_every_reusable_job_runs_where_the_project_says(self):
        for f in sorted(WORKFLOWS.glob("sdlc-*.yml")):
            s = f.read_text(encoding="utf-8")
            self.assertNotIn("runs-on: ubuntu-latest", s, f.name)
            self.assertIn("runs-on: ${{ inputs.runs_on }}", s, f.name)
            self.assertRegex(s, r"      runs_on:\n        description: .*\n        type: string\n        default: ubuntu-latest\n", f.name)

    def test_callers_pass_the_runner_variable(self):
        for name, text in callers(stages={"deploy": True}).items():
            for block in text.split("\n  ")[1:]:
                if "    uses: " in block:
                    self.assertIn("runs_on: ${{ vars.SDLC_RUNS_ON || 'ubuntu-latest' }}", block, name)

    def test_marketplace_ci_runs_once_per_pr(self):
        ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        on = ci.split("\non:\n", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("push:", on, "not again on main after the PR passed")
        self.assertIn('paths-ignore: ["README.md", "docs/**"]', on, "skills are .md: never ignore **.md")
        self.assertIn("cancel-in-progress: true", ci)


class PullRequestTest(unittest.TestCase):
    def setUp(self):
        self.pr = callers()[".github/workflows/sdlc-pull-request.yml"]

    def test_stage_checks_skip_branches_that_never_carry_their_files(self):
        for name in ("intent-check", "spec-check", "design-check"):
            cond = re.search(r"    if: (.*)\n", job(self.pr, name)).group(1)
            for prefix in ("story/", "plan/", "test-report/", "sdlc/upgrade-"):
                self.assertIn(f"!startsWith(github.head_ref, '{prefix}')", cond, name)
            self.assertFalse(cond.startswith("!"), "a YAML value starting with ! is a tag")

    def test_pr_review_and_tests_skip_document_only_branches(self):
        cond = re.search(r"    if: (.*)\n", job(self.pr, "pr")).group(1)
        for prefix in ("intent/", "spec/", "plan/", "test-report/"):
            self.assertIn(f"!startsWith(github.head_ref, '{prefix}')", cond)
        self.assertNotIn("'story/'", cond)
        self.assertIn("startsWith(github.head_ref, 'spec/')", job(self.pr, "prescreen"))

    def test_sdlc_pr_skips_tests_without_code_and_cancels_stale_runs(self):
        pr = (WORKFLOWS / "sdlc-pr.yml").read_text(encoding="utf-8")
        self.assertIn(f"SDLC_DOCS: '{ip.SDLC_DOCS}'", pr, "the PR and push filters agree")
        self.assertIn("code: ${{ steps.cfg.outputs.code }}", pr)
        e2e = pr.split("\n  e2e:\n", 1)[1].split("\n    steps:\n", 1)[0]
        self.assertIn("needs.config.outputs.code == 'true'", e2e)
        self.assertIn("needs.review-gate.result == 'success'", e2e, "story PRs always test")
        for name in ("review-gate", "e2e"):
            head = pr.split(f"\n  {name}:\n", 1)[1].split("\n    steps:\n", 1)[0]
            self.assertIn(f"group: sdlc-{name}-${{{{ github.event.pull_request.number }}}}", head)
            self.assertIn("cancel-in-progress: true", head)

    def test_document_pattern(self):
        docs = re.compile(ip.SDLC_DOCS)
        for f in ("specs/a.md", "plans/a-s1.md", "test-reports/a/README.md", "README.md", "tickets/abc-1.md"):
            self.assertTrue(docs.search(f), f)
        for f in ("src/app.ts", ".sdlc/build.yaml", ".github/workflows/sdlc-pr.yml", "package.json", "src/README.md"):
            self.assertFalse(docs.search(f), f)


class AfterMergeTest(unittest.TestCase):
    def setUp(self):
        self.push = callers(stages={"deploy": True})[".github/workflows/sdlc-push.yml"]

    def test_each_job_waits_for_its_own_files(self):
        want = {"requirements": "requirements", "intent-to-spec": "intent", "spec-to-stories": "specs",
                "stack": "specs", "build": "build", "tests": "tests", "release": "releases"}
        for name, flag in want.items():
            block = job(self.push, name)
            self.assertIn("    needs: changes\n", block, name)
            self.assertIn(f"needs.changes.outputs.{flag} == 'true'", block, name)
            self.assertIn("always() && (", block, "a re-run by hand skips the changes job")

    def run_changes(self, files, before="1" * 40):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        script = job(self.push, "changes").split("        run: |\n", 1)[1]
        script = "\n".join(l[10:] for l in script.splitlines())
        with tempfile.TemporaryDirectory() as d:
            gh = Path(d) / "gh"
            gh.write_text("#!/bin/sh\ncat \"$FAKE_FILES\"\n", encoding="utf-8")
            gh.chmod(0o755)
            listing = Path(d) / "files.txt"
            listing.write_text("".join(f + "\n" for f in files), encoding="utf-8")
            out = Path(d) / "out.txt"
            env = {**os.environ, "PATH": d + os.pathsep + os.environ.get("PATH", ""), "FAKE_FILES": str(listing),
                   "GITHUB_OUTPUT": str(out), "GITHUB_REPOSITORY": "o/r", "BEFORE": before, "AFTER": "2" * 40,
                   "SDLC_DOCS": ip.SDLC_DOCS}
            r = subprocess.run([bash, "-c", script], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return dict(l.split("=", 1) for l in out.read_text(encoding="utf-8").splitlines())

    def test_a_test_report_merge_starts_nothing(self):
        o = self.run_changes(["test-reports/s5/README.md"])
        self.assertEqual(set(o.values()), {"false"}, o)

    def test_a_story_merge_runs_tests_and_the_next_build(self):
        o = self.run_changes(["src/app.ts", "tests/app.test.ts", "PATTERNS.md"])
        self.assertEqual((o["tests"], o["build"], o["specs"]), ("true", "true", "false"))

    def test_a_spec_merge_feeds_design_and_build_not_tests(self):
        o = self.run_changes(["specs/x.md", "designs/x/design.md"])
        self.assertEqual((o["specs"], o["build"], o["tests"], o["intent"]), ("true", "true", "false", "false"))

    def test_a_stack_merge_builds_and_tests(self):
        o = self.run_changes([".sdlc/build.yaml"])
        self.assertEqual((o["build"], o["tests"]), ("true", "true"))

    def test_unknown_changes_run_everything(self):
        o = self.run_changes([], before="0" * 40)
        self.assertEqual(set(o.values()), {"true"})


class AdvisoryTest(unittest.TestCase):
    def test_no_advisory_reviewer_by_default_with_an_example(self):
        a, _ = ip.normalize({"sdlc_ref": "v1.0.0", "owners": OWNERS})
        review = json.loads(ip.render_review(a))
        self.assertEqual(review["advisory"], [])
        self.assertEqual(review["_example_advisory"][0]["name"], "code-review")


if __name__ == "__main__":
    unittest.main()
