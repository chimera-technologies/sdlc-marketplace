"""Tests for the Build stage: validate_plan.py, build_guard.py, build_preflight.py."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
SPEC = PLUGIN / "skills" / "write-spec" / "examples" / "claims-status-self-service.md"
PLAN = PLUGIN / "skills" / "build-story" / "examples" / "claims-status-self-service-s1.md"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vp = load("validate_plan", PLUGIN / "skills" / "build-story" / "scripts" / "validate_plan.py")
bg = load("build_guard", PLUGIN / "hooks" / "build_guard.py")
bp = load("build_preflight", PLUGIN / "skills" / "build-story" / "scripts" / "build_preflight.py")
ns = load("next_story", PLUGIN / "skills" / "build-story" / "scripts" / "next_story.py")
js = load("jira_story", PLUGIN / "skills" / "build-story" / "scripts" / "jira_story.py")
RPR = PLUGIN / "skills" / "review-plan" / "scripts" / "render_plan_review.py"
rpr = load("render_plan_review", RPR)

TEST_FILE = '''
test("S1 AC-1: only the customer's own claims", () => {});
test("S1 AC-2: status codes, never internal states", () => {});
test("S1 AC-3: access logged without claim content", () => {});
'''


class Repo(unittest.TestCase):
    """A throwaway product repo with the example spec and plan."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        for d in ("specs", "plans", "tests/api", ".sdlc", ".claude"):
            (self.root / d).mkdir(parents=True)
        shutil.copy(SPEC, self.root / "specs" / SPEC.name)
        self.plan_text = PLAN.read_text(encoding="utf-8")

    def plan(self, text=None, name="claims-status-self-service-s1"):
        p = self.root / "plans" / f"{name}.md"
        p.write_text(self.plan_text if text is None else text, encoding="utf-8")
        return p

    def assertError(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r} in {errors}")


class ValidatePlanTest(Repo):
    def test_example_is_valid(self):
        _, errors, _ = vp.validate(self.plan(), self.root)
        self.assertEqual(errors, [])

    def test_template_is_rejected(self):
        _, errors, _ = vp.validate(PLUGIN / "skills" / "build-story" / "templates" / "plan.md", self.root)
        self.assertError(errors, "unfilled template placeholder")

    def test_story_criteria_parsed_from_spec(self):
        crit = vp.story_criteria(SPEC.read_text(encoding="utf-8"), "S1")
        self.assertEqual(len(crit), 3)
        self.assertTrue(crit[0].startswith("Returns only claims owned"))
        self.assertIsNone(vp.story_criteria(SPEC.read_text(encoding="utf-8"), "S9"))

    def test_every_criterion_needs_a_row(self):
        text = "\n".join(l for l in self.plan_text.splitlines() if not l.startswith("| AC-3 "))
        _, errors, _ = vp.validate(self.plan(text), self.root)
        self.assertError(errors, "missing ['AC-3']")

    def test_extra_row_not_in_spec(self):
        text = self.plan_text.replace(
            "\n## Edge cases", '| AC-4 | Made up. | tests/api/x.py › "S1 AC-4: x" |\n\n## Edge cases')
        _, errors, _ = vp.validate(self.plan(text), self.root)
        self.assertError(errors, "not in the spec ['AC-4']")

    def test_test_name_must_match(self):
        _, errors, _ = vp.validate(self.plan(self.plan_text.replace('"S1 AC-2:', '"S2 AC-2:')), self.root)
        self.assertError(errors, 'AC-2: the Test column must name a test for "S1 AC-2"')

    def test_test_names_in_any_language_style(self):
        for style in ('"S1 AC-2: x"', 'test_s1_ac_2_rejects', 'S1Ac2Rejects', 'S1-AC-2'):
            text = self.plan_text.replace('"S1 AC-2: status codes, never internal states"', style)
            _, errors, _ = vp.validate(self.plan(text), self.root)
            self.assertEqual(errors, [], style)

    def test_test_paths_from_build_yaml(self):
        (self.root / ".sdlc").mkdir(exist_ok=True)
        (self.root / ".sdlc" / "build.yaml").write_text("test_paths: [src/test/, spec/]\n", encoding="utf-8")
        _, errors, _ = vp.validate(self.plan(), self.root)
        self.assertEqual(sum("must name a file under src/test/ or spec/" in e for e in errors), 3)
        text = self.plan_text.replace("tests/api/test_customer_status.py", "src/test/CustomerStatusTest.java")
        _, errors, _ = vp.validate(self.plan(text), self.root)
        self.assertEqual(errors, [])
        (self.root / "src" / "test").mkdir(parents=True)
        (self.root / "src" / "test" / "CustomerStatusTest.java").write_text(
            '@DisplayName("S1 AC-1 own claims") void a(){}\nvoid s1Ac2StatusCodes(){}\nvoid test_S1_AC_3(){}',
            encoding="utf-8")
        _, errors, _ = vp.validate(self.plan(text), self.root, check_tests=True)
        self.assertEqual(errors, [])

    def test_test_must_be_under_tests(self):
        _, errors, _ = vp.validate(self.plan(self.plan_text.replace(
            "| tests/api/test_customer_status.py › \"S1 AC-1", "| src/check.py › \"S1 AC-1")), self.root)
        self.assertError(errors, "AC-1: the Test column must name a file under tests/")

    def test_branch_must_match_jira(self):
        _, errors, _ = vp.validate(self.plan(self.plan_text.replace("story/clm-483-", "feature/")), self.root)
        self.assertError(errors, "branch must be story/clm-483-<short-name>")

    def test_id_must_be_spec_slug_plus_story(self):
        text = self.plan_text.replace("id: claims-status-self-service-s1", "id: my-plan")
        _, errors, _ = vp.validate(self.plan(text, "my-plan"), self.root)
        self.assertError(errors, "id must be 'claims-status-self-service-s1'")

    def test_story_must_exist(self):
        _, errors, _ = vp.validate(self.plan(self.plan_text.replace("story: S1", "story: S9")), self.root)
        self.assertError(errors, "story S9 not found")

    def test_check_tests(self):
        plan = self.plan()
        _, errors, _ = vp.validate(plan, self.root, check_tests=True)
        self.assertEqual(sum("no test titled" in e for e in errors), 3)
        (self.root / "tests" / "api" / "test_customer_status.py").write_text(TEST_FILE, encoding="utf-8")
        _, errors, _ = vp.validate(plan, self.root, check_tests=True)
        self.assertEqual(errors, [])

    def test_check_tests_does_not_match_longer_ids(self):
        (self.root / "tests" / "api" / "t.py").write_text('test("S1 AC-10: x")\ntest("S1 AC-20: y")\ntest("S1 AC-30: z")', encoding="utf-8")
        self.assertEqual(vp.test_names_found(self.root, ["S1 AC-1", "S1 AC-2", "S1 AC-3"]), set())


class PlanEdgeCasesTest(Repo):
    def test_example_has_edge_cases(self):
        _, errors, warnings = vp.validate(self.plan(), self.root)
        self.assertEqual((errors, warnings), ([], []))

    def test_missing_section_only_warns(self):
        start, end = self.plan_text.index("## Edge cases"), self.plan_text.index("## Steps")
        _, errors, warnings = vp.validate(self.plan(self.plan_text[:start] + self.plan_text[end:]), self.root)
        self.assertEqual(errors, [])
        self.assertTrue(any("Edge cases" in w for w in warnings), warnings)

    def test_section_must_be_real_and_after_tests(self):
        start, end = self.plan_text.index("## Edge cases"), self.plan_text.index("## Steps")
        empty = self.plan_text[:start] + "## Edge cases\nTBD\n\n" + self.plan_text[end:]
        self.assertError(vp.validate(self.plan(empty), self.root)[1], "'Edge cases' needs real content")
        section = self.plan_text[start:end]
        moved = (self.plan_text[:start] + self.plan_text[end:]).replace("## Out of scope", section + "## Out of scope")
        self.assertError(vp.validate(self.plan(moved), self.root)[1], "section headings must be exactly")


class ReviewFindingsTest(Repo):
    """The plan review's must-fix findings, carried into the plan and its tests."""

    ROWS = ('| EC-1 | Customer with two accounts | merge by customer ID (Step 2) | '
            'tests/api/test_customer_status.py › "S1 EC-1: two accounts, one list" |\n'
            '| BUG-1 | 404 vs 403 leaks claim ids | always 404 (Step 3) | '
            'tests/api/test_customer_status.py › "S1 BUG-1: never 403" |\n')

    def with_findings(self, rows=None):
        section = "## Review findings\n| ID | Finding | Handling | Test |\n|---|---|---|---|\n" + (self.ROWS if rows is None else rows) + "\n"
        return self.plan(self.plan_text.replace("## Steps", section + "## Steps"))

    def test_valid_rows(self):
        _, errors, _ = vp.validate(self.with_findings(), self.root, must_fix=["EC-1", "BUG-1"])
        self.assertEqual(errors, [])

    def test_every_must_fix_id_needs_a_row(self):
        _, errors, _ = vp.validate(self.with_findings(), self.root, must_fix=["EC-1", "EC-2", "BUG-1"])
        self.assertError(errors, "Review findings has no row for EC-2")
        _, errors, _ = vp.validate(self.plan(), self.root, must_fix=["EC-1"])
        self.assertError(errors, "no row for EC-1")

    def test_row_needs_a_named_test(self):
        rows = '| EC-1 | Two accounts | merge them | a manual check |\n'
        _, errors, _ = vp.validate(self.with_findings(rows), self.root, must_fix=["EC-1"])
        self.assertError(errors, 'a test for "S1 EC-1"')

    def test_decision_needed_warns(self):
        rows = '| BUG-1 | Leaks ids | Decision needed: should admins see other customers? | none |\n'
        _, errors, warnings = vp.validate(self.with_findings(rows), self.root, must_fix=["BUG-1"])
        self.assertEqual(errors, [])
        self.assertTrue(any("needs the owner's decision" in w for w in warnings), warnings)

    def test_check_tests_requires_the_finding_tests(self):
        (self.root / "tests" / "api" / "test_customer_status.py").write_text(TEST_FILE, encoding="utf-8")
        _, errors, _ = vp.validate(self.with_findings(), self.root, check_tests=True)
        self.assertError(errors, 'no test titled "S1 EC-1: ..."')
        self.assertError(errors, 'no test titled "S1 BUG-1: ..."')
        (self.root / "tests" / "api" / "test_customer_status.py").write_text(
            TEST_FILE + 'test("S1 EC-1: two accounts", () => {});\ndef test_s1_bug_1_never_403(): pass\n', encoding="utf-8")
        self.assertEqual(vp.validate(self.with_findings(), self.root, check_tests=True)[1], [])

    def test_cli_review_flag(self):
        must = self.root / "must-fix.json"
        must.write_text(json.dumps([{"id": "EC-1"}, {"id": "EC-2"}]), encoding="utf-8")
        r = subprocess.run([sys.executable, str(PLUGIN / "skills" / "build-story" / "scripts" / "validate_plan.py"),
                            "--root", str(self.root), "--review", str(must), str(self.with_findings())],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no row for EC-2", r.stderr)


class RenderPlanReviewTest(unittest.TestCase):
    BUG = {"severity": "high", "title": "Undo restores at the end", "where": "Steps 3",
           "scenario": "delete the 2nd of 3 tasks, undo: it comes back last", "suggestion": "keep the index"}
    EDGE = {"case": "Exactly 500 characters", "why": "only 501 is tested", "suggestion": "add a 500 case"}

    def run_render(self, content):
        with tempfile.TemporaryDirectory() as d:
            src, md = Path(d) / "plan-review.json", Path(d) / "out.md"
            if content is not None:
                src.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            r = subprocess.run([sys.executable, str(RPR), str(src), "--markdown", str(md)], capture_output=True, text=True)
            return r.returncode, r.stdout.strip(), md.read_text(encoding="utf-8")

    def test_verdicts(self):
        self.assertEqual(rpr.verdict({"edge_cases": [], "bugs": []}), "clean")
        self.assertEqual(rpr.verdict({"edge_cases": [], "bugs": [{**self.BUG, "severity": "low"}]}), "clean")
        self.assertEqual(rpr.verdict({"edge_cases": [self.EDGE], "bugs": []}), "concerns")
        self.assertEqual(rpr.verdict({"edge_cases": [], "bugs": [self.BUG]}), "concerns")
        self.assertEqual(rpr.verdict({"bugs": [self.BUG, {**self.BUG, "severity": "critical"}]}), "blocking")

    def test_markdown_lists_both_by_severity(self):
        data = {"summary": "Two gaps.", "edge_cases": [self.EDGE],
                "bugs": [{**self.BUG, "severity": "low", "title": "Minor"}, {**self.BUG, "severity": "critical", "title": "Loses | data"}]}
        code, verdict, md = self.run_render(data)
        self.assertEqual((code, verdict), (0, "blocking"))
        self.assertIn("Potential bugs: 1 critical · 0 high · 1 low. Missed edge cases: 1.", md)
        self.assertIn("this plan PR is a draft", md)
        self.assertLess(md.index("Loses \\| data"), md.index("Minor"), "critical first, pipes escaped")
        self.assertIn("| Exactly 500 characters | only 501 is tested | add a 500 case |", md)

    def test_must_fix_and_low(self):
        data = {"edge_cases": [self.EDGE, {**self.EDGE, "case": "Empty list"}],
                "bugs": [{**self.BUG, "severity": "low", "title": "Cosmetic"}, {**self.BUG, "severity": "critical", "title": "Data loss"},
                         self.BUG]}
        fix = rpr.must_fix(data)
        self.assertEqual([(f["id"], f["kind"], f["severity"]) for f in fix],
                         [("EC-1", "edge case", ""), ("EC-2", "edge case", ""), ("BUG-1", "bug", "critical"), ("BUG-2", "bug", "high")])
        low = rpr.low_text(data)
        self.assertIn("not required to fix", low)
        self.assertIn("BUG-3 Cosmetic", low)
        self.assertNotIn("Data loss", low)
        self.assertEqual(rpr.low_text({"bugs": [self.BUG]}), "")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "r.json"
            src.write_text(json.dumps(data), encoding="utf-8")
            subprocess.run([sys.executable, str(RPR), str(src), "--markdown", str(Path(d) / "m.md"),
                            "--must-fix", str(Path(d) / "f.json"), "--low", str(Path(d) / "l.txt")], check=True, capture_output=True)
            self.assertEqual(len(json.loads((Path(d) / "f.json").read_text(encoding="utf-8"))), 4)
            md = (Path(d) / "m.md").read_text(encoding="utf-8")
            self.assertIn("Must be fixed in this story (4):** EC-1, EC-2, BUG-1, BUG-2", md)
            self.assertIn("| BUG-3 | ⚪ low | Cosmetic", md)

    def test_review_that_did_not_run(self):
        for content in (None, "not json", {"bugs": [{"severity": "medium"}]}, {"edge_cases": "x"}):
            code, verdict, md = self.run_render(content)
            self.assertEqual((code, verdict), (0, "failed"), content)
            self.assertIn("did not run", md)


class PlanWithoutJiraTest(Repo):
    def no_jira(self, branch="story/claims-status-self-service-s1"):
        return (self.plan_text.replace("jira: CLM-483", "jira: none")
                .replace("branch: story/clm-483-status-endpoint", f"branch: {branch}"))

    def test_jira_none_with_plan_branch_is_valid(self):
        self.assertEqual(vp.validate(self.plan(self.no_jira()), self.root)[1], [])
        self.assertEqual(vp.validate(self.plan(self.no_jira("story/claims-status-self-service-s1-endpoint")), self.root)[1], [])

    def test_jira_none_needs_the_plan_branch(self):
        _, errors, _ = vp.validate(self.plan(self.no_jira("story/endpoint")), self.root)
        self.assertError(errors, "branch must be story/claims-status-self-service-s1 (jira: none)")

    def test_jira_must_be_a_key_or_none(self):
        _, errors, _ = vp.validate(self.plan(self.plan_text.replace("jira: CLM-483", "jira: nope")), self.root)
        self.assertError(errors, "Jira key (ABC-123) or none")


class NextStoryTest(Repo):
    """next_story.py: the automatic Build's state machine (git + PR list only)."""

    def setUp(self):
        super().setUp()
        (self.root / ".sdlc" / "build.yaml").write_text("test_command: pytest -q\n", encoding="utf-8")

    def decide(self, prs=()):
        return ns.decide(self.root, [{"headRefName": h, "state": s} for h, s in prs])

    def only(self, result):
        self.assertEqual(len(result["actions"]) + len(result["waiting"]), 1, result)
        return (result["actions"] or result["waiting"])[0]

    def test_first_story_is_planned(self):
        a = self.only(self.decide())
        self.assertEqual((a["action"], a["story"], a["id"]), ("plan", "S1", "claims-status-self-service-s1"))

    def test_waits_for_the_plan_pr(self):
        w = self.only(self.decide([("plan/claims-status-self-service-s1", "OPEN")]))
        self.assertIn("plan PR open", w["reason"])

    def test_merged_plan_is_built_on_its_branch(self):
        self.plan()
        a = self.only(self.decide([("plan/claims-status-self-service-s1", "MERGED")]))
        self.assertEqual((a["action"], a["branch"], a["plan"]),
                         ("build", "story/clm-483-status-endpoint", "plans/claims-status-self-service-s1.md"))

    def test_waits_for_the_story_pr(self):
        self.plan()
        self.assertIn("story PR open", self.only(self.decide([("story/clm-483-status-endpoint", "OPEN")]))["reason"])

    def test_merged_story_moves_to_the_next(self):
        self.plan()
        a = self.only(self.decide([("story/clm-483-status-endpoint", "MERGED")]))
        self.assertEqual((a["action"], a["story"]), ("plan", "S2"))

    def test_rejections_stop_the_loop(self):
        self.assertIn("closed without merge", self.only(self.decide([("plan/claims-status-self-service-s1", "CLOSED")]))["reason"])
        self.plan()
        self.assertIn("closed without merge", self.only(self.decide([("story/clm-483-status-endpoint", "CLOSED")]))["reason"])
        # A later attempt that merged wins over an earlier closed one.
        a = self.only(self.decide([("story/clm-483-status-endpoint", "CLOSED"), ("story/clm-483-status-endpoint", "MERGED")]))
        self.assertEqual(a["story"], "S2")

    def test_all_done(self):
        prs = []
        for n, branch in ((1, "story/clm-483-a"), (2, "story/clm-484-b"), (3, "story/clm-485-c")):
            text = (self.plan_text.replace("claims-status-self-service-s1", f"claims-status-self-service-s{n}")
                    .replace("story: S1", f"story: S{n}").replace("story/clm-483-status-endpoint", branch))
            self.plan(text, f"claims-status-self-service-s{n}")
            prs.append((branch, "MERGED"))
        self.assertEqual(self.decide(prs), {"actions": [], "waiting": []})

    def test_nothing_moves_without_a_stack(self):
        (self.root / ".sdlc" / "build.yaml").write_text("code_paths: [src/]\n", encoding="utf-8")
        self.assertIn("record the stack", self.only(self.decide())["reason"])

    def test_manual_build_in_progress_pauses(self):
        self.assertIn("manual build", self.only(self.decide([("story/clm-9-local", "OPEN")]))["reason"])

    def test_cli(self):
        prs = self.root / "prs.json"
        prs.write_text("[]", encoding="utf-8")
        r = subprocess.run([sys.executable, str(PLUGIN / "skills" / "build-story" / "scripts" / "next_story.py"),
                            "--root", str(self.root), "--prs", str(prs)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["actions"][0]["action"], "plan")
        r = subprocess.run([sys.executable, str(PLUGIN / "skills" / "build-story" / "scripts" / "next_story.py"),
                            "--root", str(self.root), "--prs", str(prs), "--spec", "../etc/x.md"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


class FakeJiraWorkflow:
    """A story in a Jira workflow: status plus the transitions out of it."""

    WORKFLOW = {  # status: (category, [(transition name, to status, to category)])
        "To Do": ("new", [("Start", "In Progress", "indeterminate"), ("Close", "Done", "done")]),
        "In Progress": ("indeterminate", [("Ready", "In Review", "indeterminate"), ("Close", "Done", "done")]),
        "In Review": ("indeterminate", [("Close", "Done", "done")]),
        "Done": ("done", [("Reopen", "To Do", "new")]),
    }

    def __init__(self, status="To Do", workflow=None):
        self.status, self.posts = status, []
        self.workflow = workflow or self.WORKFLOW

    def call(self, method, path, body=None):
        if method == "GET" and path.endswith("?fields=status"):
            cat = self.workflow[self.status][0]
            return {"fields": {"status": {"name": self.status, "statusCategory": {"key": cat}}}}
        if method == "GET" and path.endswith("/transitions"):
            return {"transitions": [{"id": str(i), "name": n, "to": {"name": to, "statusCategory": {"key": c}}}
                                    for i, (n, to, c) in enumerate(self.workflow[self.status][1])]}
        self.posts.append((path, body))
        if path.endswith("/transitions"):
            self.status = self.workflow[self.status][1][int(body["transition"]["id"])][1]
        return {}


class JiraStoryTest(unittest.TestCase):
    def test_build_start_then_review(self):
        jira = FakeJiraWorkflow()
        self.assertEqual(js.move(jira, "SCR-1", "in-progress"), "SCR-1: To Do -> In Progress")
        self.assertEqual(js.move(jira, "SCR-1", "in-review"), "SCR-1: In Progress -> In Review")

    def test_never_moves_backwards_or_twice(self):
        for status, target in (("Done", "in-progress"), ("Done", "in-review"), ("In Review", "in-progress"),
                               ("In Progress", "in-progress"), ("In Review", "in-review")):
            jira = FakeJiraWorkflow(status)
            js.move(jira, "SCR-1", target)
            self.assertEqual(jira.posts, [], (status, target))
            self.assertEqual(jira.status, status)

    def test_workflow_without_review_is_left_alone(self):
        simple = {"To Do": ("new", [("Start", "Doing", "indeterminate")]),
                  "Doing": ("indeterminate", [("Finish", "Done", "done")]), "Done": ("done", [])}
        jira = FakeJiraWorkflow(workflow=simple)
        self.assertIn("-> Doing", js.move(jira, "SCR-1", "in-progress"), "any in-progress category status works")
        self.assertIn("no in-review transition", js.move(jira, "SCR-1", "in-review"))
        self.assertEqual(jira.status, "Doing")

    def test_cli_without_jira_is_a_no_op(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("JIRA_")}
        script = str(PLUGIN / "skills" / "build-story" / "scripts" / "jira_story.py")
        r = subprocess.run([sys.executable, script, "SCR-1", "move", "in-progress"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Jira not configured", r.stdout)
        r = subprocess.run([sys.executable, script, "not-a-key", "comment", "x"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)


class BuildGuardTest(Repo):
    def setUp(self):
        super().setUp()
        (self.root / ".sdlc" / "build.yaml").write_text(
            "code_paths: [src/, tests/]   # comment\ngraphify_version: 0.9.71\nponytail_ref: v4.10.0\n", encoding="utf-8")
        cfg = tempfile.TemporaryDirectory()
        self.addCleanup(cfg.cleanup)
        self.claude_dir = Path(cfg.name)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude_dir)})
        patcher.start()
        self.addCleanup(patcher.stop)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)

    def ready(self):
        (self.root / "graphify-out").mkdir(exist_ok=True)
        (self.root / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
        (self.root / ".claude" / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"ponytail@ponytail": True}}), encoding="utf-8")
        (self.claude_dir / ".ponytail-active").write_text("full", encoding="utf-8")
        subprocess.run(["git", "checkout", "-q", "-b", "story/clm-483-status-endpoint"], cwd=self.root, check=True)
        self.plan()

    def test_config_parsing(self):
        cfg = bg.load_build_config(self.root)
        self.assertEqual(cfg["code_paths"], ["src/", "tests/"])
        self.assertEqual(cfg["ponytail_ref"], "v4.10.0")

    def test_repo_without_build_yaml_is_never_blocked(self):
        (self.root / ".sdlc" / "build.yaml").unlink()
        self.assertEqual(bg.check(self.root, "src/app.js"), [])

    def test_non_code_paths_are_not_blocked(self):
        for rel in ["plans/x.md", "README.md", "specs/a.md", "srcx/a.js"]:
            self.assertEqual(bg.check(self.root, rel), [], rel)

    def test_blocks_code_until_everything_is_ready(self):
        problems = bg.check(self.root, "src/app.js")
        text = " ".join(problems)
        self.assertIn("No Graphify graph", text)
        self.assertIn("Ponytail is not enabled", text)
        self.assertIn("not a story branch", text)

    def test_ponytail_enabled_but_not_active(self):
        self.ready()
        (self.claude_dir / ".ponytail-active").unlink()
        self.assertTrue(any("not active in this session" in p for p in bg.check(self.root, "src/app.js")))

    def test_story_branch_needs_its_plan(self):
        self.ready()
        (self.root / "plans" / "claims-status-self-service-s1.md").unlink()
        self.assertTrue(any("No plan in plans/ for branch 'story/clm-483-status-endpoint'" in p
                            for p in bg.check(self.root, "tests/api/t.py")))

    def test_plan_found_by_its_branch_without_jira(self):
        self.ready()
        subprocess.run(["git", "checkout", "-q", "-b", "story/claims-status-self-service-s1"], cwd=self.root, check=True)
        self.assertTrue(any("No plan in plans/" in p for p in bg.check(self.root, "src/app.js")))
        self.plan(self.plan_text.replace("jira: CLM-483", "jira: none")
                  .replace("branch: story/clm-483-status-endpoint", "branch: story/claims-status-self-service-s1"))
        self.assertEqual(bg.check(self.root, "src/app.js"), [])

    def test_older_plan_found_by_jira_key(self):
        self.ready()
        subprocess.run(["git", "checkout", "-q", "-b", "story/clm-483-renamed"], cwd=self.root, check=True)
        self.assertEqual(bg.check(self.root, "src/app.js"), [])

    def test_no_code_marker_stands_in_for_the_graph(self):
        self.ready()
        (self.root / "graphify-out" / "graph.json").unlink()
        self.assertTrue(any("No Graphify graph" in p for p in bg.check(self.root, "src/app.js")))
        bg.no_code_marker(self.root).write_text("x", encoding="utf-8")
        self.assertEqual(bg.check(self.root, "src/app.js"), [])

    def test_allowed_when_ready(self):
        self.ready()
        self.assertEqual(bg.check(self.root, "src/app.js"), [])
        self.assertEqual(bg.check(self.root, "tests/api/test_customer_status.py"), [])

    def test_hook_exit_codes(self):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "CLAUDE_CONFIG_DIR": str(self.claude_dir)}
        event = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(self.root / "src" / "app.js")}})
        r = subprocess.run([sys.executable, str(PLUGIN / "hooks" / "build_guard.py")], input=event,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("build_preflight.py", r.stderr)
        self.ready()
        r = subprocess.run([sys.executable, str(PLUGIN / "hooks" / "build_guard.py")], input=event,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)


class PreflightNoCodeTest(unittest.TestCase):
    """A first story: nothing to index yet must not stop the build."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.cfg = {"code_paths": ["src/", "tests/", "index.html"], "graphify_version": "0.9.71"}
        self.calls = []

    def fake_run(self, cmd, cwd, timeout=600):
        self.calls.append(cmd[3:] if cmd[1:3] == ["-m", "graphify"] else cmd)
        if cmd[-1] == "--version":
            return subprocess.CompletedProcess(cmd, 0, "graphify 0.9.71\n", "")
        if "extract" in cmd:
            (self.root / "graphify-out").mkdir(exist_ok=True)
            (self.root / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "12 nodes, 30 edges\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def graphify(self):
        report = []
        with mock.patch.object(bp, "run", self.fake_run):
            bp.step_graphify(self.root, self.cfg, report)
        return report

    def test_has_code(self):
        self.assertFalse(bp.has_code(self.root, self.cfg))
        (self.root / "src").mkdir()
        self.assertFalse(bp.has_code(self.root, self.cfg), "an empty folder is not code")
        (self.root / "index.html").write_text("<html></html>", encoding="utf-8")
        self.assertTrue(bp.has_code(self.root, self.cfg))

    def test_no_code_warns_and_continues(self):
        report = self.graphify()
        self.assertTrue(any("WARNING no code" in line for line in report), report)
        self.assertTrue(bg.no_code_marker(self.root).is_file())
        self.assertFalse(any("extract" in c for c in self.calls), "must not try to index nothing")

    def test_headless_does_not_touch_claude_md(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "main.ts").write_text("export {}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"SDLC_HEADLESS": "1"}):
            report = self.graphify()
        self.assertFalse(any("claude" in c and "install" in c for c in self.calls), self.calls)
        self.assertIn("graphify: Claude Code integration skipped (headless)", report)
        self.assertTrue((self.root / "graphify-out" / "graph.json").is_file(), "the graph is still built")
        with mock.patch.dict(os.environ, {"SDLC_HEADLESS": "0"}):
            self.graphify()
        self.assertTrue(any("claude" in c and "install" in c for c in self.calls), "interactive still installs it")

    def test_graph_replaces_the_marker_once_code_exists(self):
        self.graphify()
        (self.root / "src").mkdir()
        (self.root / "src" / "main.ts").write_text("export {}\n", encoding="utf-8")
        report = self.graphify()
        self.assertTrue((self.root / "graphify-out" / "graph.json").is_file())
        self.assertFalse(bg.no_code_marker(self.root).is_file())
        self.assertTrue(any("12 nodes" in line for line in report), report)


class PreflightLogicTest(unittest.TestCase):
    GRAPHIFY_ENTRY = {"matcher": "Read|Glob", "hooks": [{"type": "command", "command": "C:/x/graphify.exe hook-guard read"}]}
    OTHER_ENTRY = {"matcher": "Bash", "hooks": [{"type": "command", "command": "node other.js"}]}

    def test_relocate_moves_only_graphify_hooks(self):
        shared = {"hooks": {"PreToolUse": [self.GRAPHIFY_ENTRY, self.OTHER_ENTRY]}, "enabledPlugins": {"a": True}}
        shared, local, moved = bp.relocate_graphify_hooks(shared, {})
        self.assertEqual(moved, 1)
        self.assertEqual(shared["hooks"]["PreToolUse"], [self.OTHER_ENTRY])
        self.assertEqual(local["hooks"]["PreToolUse"], [self.GRAPHIFY_ENTRY])
        self.assertTrue(bp.local_has_graphify_hooks(local))

    def test_relocate_drops_empty_hooks_and_is_idempotent(self):
        shared, local, _ = bp.relocate_graphify_hooks({"hooks": {"PreToolUse": [self.GRAPHIFY_ENTRY]}}, {})
        self.assertNotIn("hooks", shared)
        shared2, local2, moved = bp.relocate_graphify_hooks({"hooks": {"PreToolUse": [self.GRAPHIFY_ENTRY]}}, local)
        self.assertEqual(len(local2["hooks"]["PreToolUse"]), 1)

    def test_ensure_ponytail(self):
        s = {"extraKnownMarketplaces": {"chimera-sdlc": {}}, "enabledPlugins": {"sdlc@chimera-sdlc": True}}
        self.assertTrue(bp.ensure_ponytail(s, "v4.10.0"))
        self.assertEqual(s["extraKnownMarketplaces"]["ponytail"]["source"],
                         {"source": "github", "repo": "DietrichGebert/ponytail", "ref": "v4.10.0"})
        self.assertIs(s["enabledPlugins"]["ponytail@ponytail"], True)
        self.assertIn("chimera-sdlc", s["extraKnownMarketplaces"])
        self.assertFalse(bp.ensure_ponytail(s, "v4.10.0"))

    def test_ensure_gitignore(self):
        text, changed = bp.ensure_gitignore("node_modules/\n", bp.GITIGNORE_LINES)
        self.assertTrue(changed)
        self.assertTrue(text.startswith("node_modules/\n"))
        for line in bp.GITIGNORE_LINES:
            self.assertIn(line, text.splitlines())
        self.assertFalse(bp.ensure_gitignore(text, bp.GITIGNORE_LINES)[1])

    def test_ensure_allow(self):
        s = {"permissions": {"allow": ["Bash(npm test*)"]}}
        self.assertTrue(bp.ensure_allow(s, bp.GRAPHIFY_ALLOW))
        self.assertFalse(bp.ensure_allow(s, bp.GRAPHIFY_ALLOW))
        self.assertEqual(s["permissions"]["allow"][0], "Bash(npm test*)")


if __name__ == "__main__":
    unittest.main()
