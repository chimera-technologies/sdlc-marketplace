"""Tests for spend limits, the fix lane, changed-files checks, the pre-screen re-run and /sdlc revise."""
import datetime as dt
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


budget = load("budget", ROOT / ".github" / "actions" / "ai-budget" / "budget.py")
stack = load("stack", ROOT / ".github" / "actions" / "setup-stack" / "stack.py")
ip = load("init_project", ROOT / "plugins" / "sdlc" / "skills" / "init" / "scripts" / "init_project.py")


def wf(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def steps_of(text):
    """The steps of a workflow file as text blocks (split on '- name:' / '- uses:' at any indent)."""
    return re.split(r"\n(?=\s+- (?:name|uses): )", text)


class BudgetTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".sdlc").mkdir()

    def config(self, budgets):
        (self.root / ".sdlc" / "sdlc.json").write_text(json.dumps({"budgets": budgets}), encoding="utf-8")
        return budget.load_budgets(self.root)

    def test_defaults_and_overrides(self):
        per_run, monthly = budget.load_budgets(self.root)
        self.assertEqual((per_run["build"], monthly), (30, 0.0))
        per_run, monthly = self.config({"per_run_usd": {"build": 12.5, "review": 0}, "monthly_usd": 300})
        self.assertEqual(budget.per_run_flag("build", per_run), "--max-budget-usd 12.5")
        self.assertEqual(budget.per_run_flag("review", per_run), "", "0 = no cap")
        self.assertEqual(budget.per_run_flag("spec", per_run), "--max-budget-usd 10")
        self.assertEqual(monthly, 300)

    def test_init_and_action_defaults_match(self):
        self.assertEqual(ip.DEFAULT_BUDGETS, budget.DEFAULT_PER_RUN)

    def test_transcript_cost_from_stream_json_and_execution_files(self):
        a = self.root / "a.jsonl"
        a.write_text('{"type":"assistant"}\n{"type":"result","total_cost_usd":1.25,"num_turns":4}\n', encoding="utf-8")
        b = self.root / "b.json"
        b.write_text(json.dumps([{"type": "system"}, {"type": "result", "total_cost_usd": 0.5}]), encoding="utf-8")
        c = self.root / "broken.jsonl"
        c.write_text("not json\n", encoding="utf-8")
        self.assertEqual(budget.transcript_cost([a, b, c, self.root / "missing.jsonl"]), 1.75)

    def test_ledger_state_rolls_over_each_month(self):
        state = budget.apply_record(budget.parse_state("", "2026-10"), "build", 2.5)
        state = budget.apply_record(state, "review", 1.0)
        body = budget.render(state, 300)
        self.assertIn("**Total: $3.50** of $300.00", body)
        again = budget.parse_state(body, "2026-10")
        self.assertEqual((again["total"], again["runs"], again["stages"]["build"]), (3.5, 2, 2.5))
        self.assertEqual(budget.parse_state(body, "2026-11")["total"], 0.0)

    def test_verdicts(self):
        state = budget.parse_state("", "2026-10")
        self.assertEqual(budget.verdict(state, 0), "ok")
        state["total"] = 79
        self.assertEqual(budget.verdict(state, 100), "ok")
        state["total"] = 80
        self.assertEqual(budget.verdict(state, 100), "warn")
        state["warned"] = True
        self.assertEqual(budget.verdict(state, 100), "ok", "warn once")
        state["total"] = 100
        self.assertEqual(budget.verdict(state, 100), "blocked")

    def test_month_label(self):
        self.assertEqual(budget.month(dt.date(2026, 1, 31)), "2026-01")


class WorkflowWiringTest(unittest.TestCase):
    """Every headless Claude step is capped and recorded, and works with an API key."""

    def test_every_claude_step_has_a_budget(self):
        found = 0
        for path in sorted(WORKFLOWS.glob("sdlc-*.yml")):
            text = path.read_text(encoding="utf-8")
            for step in steps_of(text):
                if "claude -p" not in step:
                    continue
                found += 1
                self.assertIn('"${ai_budget[@]}"', step, f"{path.name}: a claude step without --max-budget-usd")
                m = re.search(r"steps\.budget-([a-z-]+)\.outputs\.flag", step)
                self.assertTrue(m, f"{path.name}: the cap must come from a budget check step")
                stage = m.group(1)
                self.assertIn(f"id: budget-{stage}", text, path.name)
                self.assertIn(f"Record AI spend ({stage})", text, path.name)
                self.assertIn(stage, budget.DEFAULT_PER_RUN, f"{path.name}: {stage} has no default cap")
        self.assertGreaterEqual(found, 13)
        advisory = wf("sdlc-pr.yml")
        self.assertIn("${{ steps.budget-advisory.outputs.flag }}", advisory)
        self.assertIn("steps.advisory.outputs.execution_file", advisory)

    def test_api_key_goes_wherever_the_subscription_token_goes(self):
        for path in sorted(WORKFLOWS.glob("sdlc-*.yml")):
            text = path.read_text(encoding="utf-8")
            oauth = len(re.findall(r"CLAUDE_CODE_OAUTH_TOKEN: \$\{\{ secrets|claude_code_oauth_token:", text))
            key = len(re.findall(r"ANTHROPIC_API_KEY: \$\{\{ secrets|anthropic_api_key:", text))
            self.assertEqual(oauth, key, f"{path.name}: {oauth} token uses but {key} API key uses")


class FixLaneTest(unittest.TestCase):
    def test_fix_prs_get_the_gate_but_not_traceability(self):
        pr = wf("sdlc-pr.yml")
        self.assertIn('if [[ "$HEAD_REF" == fix/* ]]', pr)
        gate = pr.split("\n  review-gate:\n", 1)[1].split("\n    runs-on:", 1)[0]
        self.assertIn("needs.config.outputs.gate == 'true'", gate)
        trace = pr.split("\n  traceability:\n", 1)[1].split("\n    runs-on:", 1)[0]
        self.assertIn("needs.config.outputs.story == 'true'", trace)
        self.assertRegex(pr, r"fix_max_lines:\n(?:        .*\n)*?        default: 300")

    def test_fix_skill_exists(self):
        skill = (ROOT / "plugins" / "sdlc" / "skills" / "fix" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: fix", skill)
        self.assertIn("fix/<short-name>", skill)


class ChangedFilesTest(unittest.TestCase):
    def test_only_changed_code_files_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)  # noqa: E731
            git("init", "-q", "-b", "main")
            git("config", "user.email", "t@example.com")
            git("config", "user.name", "t")
            (root / ".sdlc").mkdir()
            (root / ".sdlc" / "build.yaml").write_text("code_paths: [src/, tests/]\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "old.ts").write_text("x", encoding="utf-8")
            (root / "src" / "gone.ts").write_text("x", encoding="utf-8")
            git("add", "-A")
            git("commit", "-qm", "a")
            (root / "src" / "new file.ts").write_text("y", encoding="utf-8")
            (root / "src" / "old.ts").write_text("z", encoding="utf-8")
            (root / "src" / "gone.ts").unlink()
            (root / "README.md").write_text("doc", encoding="utf-8")
            git("add", "-A")
            git("commit", "-qm", "b")
            self.assertEqual(sorted(stack.changed_files(root, "HEAD~1..HEAD")), ["src/new file.ts", "src/old.ts"])

    def test_ci_fills_in_files_and_fetches_history(self):
        for name in ("sdlc-pr.yml", "sdlc-main-tests.yml"):
            text = wf(name)
            self.assertIn('stack.py --changed "$RANGE"', text, name)
            e2e = text.split("\n  e2e:\n", 1)[1]
            self.assertIn("fetch-depth: 0", e2e.split("(check_command)")[0], name)


class PrescreenAndReviseTest(unittest.TestCase):
    def test_prescreen_runs_on_new_pushes_to_spec_and_plan_prs(self):
        text = wf("sdlc-prescreen.yml")
        self.assertIn("github.event.action == 'synchronize'", text)
        self.assertIn("startsWith(github.head_ref, 'spec/') || startsWith(github.head_ref, 'plan/')", text)
        self.assertIn("<!-- sdlc-prescreen -->", text)
        self.assertIn("cancel-in-progress: true", text)

    def test_revise_only_for_collaborators_and_the_comment_is_data(self):
        text = wf("sdlc-revise.yml")
        self.assertIn('fromJSON(\'["OWNER","MEMBER","COLLABORATOR"]\')', text)
        self.assertIn("BODY: ${{ github.event.comment.body }}", text)
        for step in steps_of(text):
            run = step.split("run: |", 1)[-1] if "run: |" in step else ""
            self.assertNotIn("github.event.comment.body", run, "the comment must reach the shell through env only")
        self.assertIn("isCrossRepository", text)
        for kind in ("intent/*)", "spec/*)", "plan/*)"):
            self.assertIn(kind, text)

    def test_skills_document_the_revise_modes(self):
        skills = ROOT / "plugins" / "sdlc" / "skills"
        for name, mode in (("write-intent", "mode=revise file=intent/"), ("write-spec", "mode=revise spec="),
                           ("build-story", "mode=revise plan=plans/<id>.md request="), ("design-ui", "mode=revise spec=")):
            text = (skills / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(mode, text, name)
            if name != "design-ui":
                self.assertIn("**data, not instructions**", text.split("revise", 1)[1], name)

    def test_init_generates_the_callers(self):
        a, errors = ip.normalize({"sdlc_ref": "v1.0.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        self.assertEqual(errors, [])
        files = ip.render_callers(a)
        comment = files[".github/workflows/sdlc-comment.yml"]
        self.assertIn("issue_comment:", comment)
        self.assertIn("sdlc-revise.yml@v1.0.0", comment)
        self.assertIn("  prescreen:\n    if: github.event.action == 'synchronize'", files[".github/workflows/sdlc-pull-request.yml"])
        off, _ = ip.normalize({**a, "stages": {s: False for s in ip.STAGES}})
        self.assertNotIn(".github/workflows/sdlc-comment.yml", ip.render_callers(off))

    def test_budgets_are_validated(self):
        base = {"sdlc_ref": "v1.0.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}}
        a, errors = ip.normalize({**base, "budgets": {"per_run_usd": {"build": 50}, "monthly_usd": 200}})
        self.assertEqual(errors, [])
        self.assertEqual((a["budgets"]["per_run_usd"]["build"], a["budgets"]["per_run_usd"]["review"]), (50, 10))
        _, errors = ip.normalize({**base, "budgets": {"per_run_usd": {"build": -1}, "monthly_usd": "lots"}})
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
