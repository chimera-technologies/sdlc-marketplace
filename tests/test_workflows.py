"""Static checks for the Claude Code workflow scripts in plugins/sdlc/workflows/.

The scripts run in the Workflow tool, not here; these tests hold the rules
that tool enforces (a pure-literal `meta` first, matching phase titles, no
clock or randomness) and keep the skills, the scripts and the reference doc
in step.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
SCRIPTS = sorted((PLUGIN / "workflows").glob("*.js"))
REFERENCE = (PLUGIN / "reference" / "workflows.md").read_text(encoding="utf-8")


def meta_block(text):
    m = re.match(r"export const meta = (\{.*?\n\})\n", text, re.S)
    return m.group(1) if m else None


class WorkflowScriptTest(unittest.TestCase):
    def test_there_are_scripts(self):
        self.assertEqual({p.name for p in SCRIPTS}, {"review-panel.js", "requirements-to-intents.js"})

    def test_meta_is_a_pure_literal_first(self):
        for p in SCRIPTS:
            meta = meta_block(p.read_text(encoding="utf-8"))
            self.assertIsNotNone(meta, f"{p.name}: must start with export const meta = {{...}}")
            self.assertRegex(meta, r"name: '[a-z0-9-]+'", p.name)
            self.assertRegex(meta, r"description: '[^']+'", p.name)
            self.assertNotIn("${", meta, f"{p.name}: no interpolation in meta")
            self.assertNotRegex(meta, r"\.\.\.|\w\(", f"{p.name}: no spreads or calls in meta")

    def test_phase_titles_match_meta(self):
        for p in SCRIPTS:
            text = p.read_text(encoding="utf-8")
            declared = set(re.findall(r"\{ title: '([^']+)'", meta_block(text)))
            used = set(re.findall(r"\bphase\('([^']+)'\)", text)) | set(re.findall(r"phase: '([^']+)'", text))
            self.assertTrue(used, p.name)
            self.assertLessEqual(used, declared, f"{p.name}: phases used but not in meta: {used - declared}")

    def test_no_clock_or_randomness(self):
        for p in SCRIPTS:
            text = p.read_text(encoding="utf-8")
            for bad in ("Date.now(", "Math.random(", "new Date()"):
                self.assertNotIn(bad, text, f"{p.name}: {bad} breaks resume")

    def test_plain_javascript(self):
        for p in SCRIPTS:
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\b(interface|type)\s+[A-Z]\w*\s*[={]", f"{p.name}: TypeScript")
            self.assertNotRegex(text, r"\bfunction \w+\([^)]*\w: \w", f"{p.name}: type annotations")

    def test_skills_reference_scripts_that_exist(self):
        refs = set()
        for skill in (PLUGIN / "skills").glob("*/SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            for name in re.findall(r"workflows/([a-z0-9-]+\.js)", text):
                refs.add(name)
                self.assertTrue((PLUGIN / "workflows" / name).is_file(), f"{skill.parent.name}: {name}")
            if "workflows/" in text:
                self.assertIn("reference/workflows.md", text, f"{skill.parent.name}: point at the thresholds")
        self.assertEqual(refs, {p.name for p in SCRIPTS}, "every script is used by a skill")

    def test_reference_documents_every_script_and_setting(self):
        for p in SCRIPTS:
            self.assertIn(p.name, REFERENCE)
        for setting in ("`auto`", "`always`", "`off`"):
            self.assertIn(setting, REFERENCE)

    def test_ci_review_steps_can_run_workflows(self):
        for wf, skill in (("sdlc-pr.yml", "review-story"), ("sdlc-intent-to-spec.yml", "review-spec"),
                          ("sdlc-build.yml", "review-plan"), ("sdlc-requirements.yml", "write-intent")):
            text = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
            step = text.split(f"/sdlc:{skill} mode=headless", 1)[1].split("--output-format", 1)[0]
            self.assertIn("Workflow", step, f"{wf}: {skill} needs the Workflow tool")


class AppTokenScopeTest(unittest.TestCase):
    """Every sdlc-bot token covers only the project repo and the plugin repo,
    not every repo the App is installed on (an org may install it widely)."""

    def test_every_app_token_is_scoped(self):
        found = 0
        for wf in sorted((ROOT / ".github" / "workflows").glob("sdlc-*.yml")):
            steps = re.split(r"\n(?=[ \t]*- name: )", wf.read_text(encoding="utf-8"))
            for k, step in enumerate(steps):
                if "actions/create-github-app-token@" not in step:
                    continue
                found += 1
                self.assertIn("repositories: ${{ steps.app-repos.outputs.names }}", step, f"{wf.name}: unscoped token")
                prev = steps[k - 1]
                self.assertIn("id: app-repos", prev, f"{wf.name}: the scope step must come just before the token")
                self.assertIn('echo "names=${GITHUB_REPOSITORY#*/},${SDLC_REPO#*/}"', prev, wf.name)
        self.assertGreater(found, 20)


if __name__ == "__main__":
    unittest.main()
