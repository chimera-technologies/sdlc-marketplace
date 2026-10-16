"""Tests for review findings as PR comments the reviewer answers (findings.py and its wiring)."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fs = load("findings", PLUGIN / "skills" / "review-story" / "scripts" / "findings.py")
ip = load("init_project", PLUGIN / "skills" / "init" / "scripts" / "init_project.py")

FINDINGS = [
    {"severity": "low", "section": "Naming", "issue": "A test is misnamed.", "evidence": "t.ts:67", "suggestion": "Rename it."},
    {"severity": "medium", "section": "AC-1", "issue": "A branch is untested.", "evidence": "Overview.tsx:95", "suggestion": "Add a test."},
    {"severity": "high", "section": "Design: overview", "issue": "Links not in the design.", "evidence": "Overview.tsx:60",
     "suggestion": "Update the design."},
]


def comment(body, created, assoc="NONE", login="bot", cid=1):
    return {"id": cid, "body": body, "created_at": created, "author_association": assoc, "user": {"login": login}}


class FindingCommentsTest(unittest.TestCase):
    def test_high_and_medium_only_numbered_high_first(self):
        out = fs.comments(FINDINGS, "abcdef1234")
        self.assertEqual([(c["n"], c["severity"]) for c in out], [(1, "high"), (2, "medium")])
        body = out[0]["body"]
        self.assertTrue(body.startswith("<!-- sdlc-finding n=1 sha=abcdef1234 severity=high -->"))
        self.assertIn("Review finding 1 (high): Design: overview", body)
        self.assertIn("**Evidence:** Overview.tsx:60", body)
        for how in ("`/sdlc fix 1`", "`/sdlc fix 1 <how>`", "`/sdlc dismiss 1 <reason>`"):
            self.assertIn(how, body)
        self.assertFalse(any("misnamed" in c["body"] for c in out), "low findings stay in the summary")

    def test_commands(self):
        self.assertEqual(fs.parse_command("/sdlc fix 1"), {"action": "fix", "numbers": [1], "all": False, "text": ""})
        self.assertEqual(fs.parse_command("/sdlc fix 2, 1 keep the links, update the design"),
                         {"action": "fix", "numbers": [1, 2], "all": False, "text": "keep the links, update the design"})
        self.assertEqual(fs.parse_command("/SDLC Dismiss 3: fine for now")["text"], "fine for now")
        self.assertTrue(fs.parse_command("/sdlc fix all add tests")["all"])
        for not_one in ("/sdlc revise x", "please /sdlc fix 1", "", "/sdlcfix 1"):
            self.assertEqual(fs.parse_command(not_one), {}, not_one)

    def test_pick_takes_the_latest_review_only(self):
        old = fs.comments(FINDINGS, "1111111")
        new = fs.comments(FINDINGS[:2], "2222222")   # the next review found only the medium one
        pr = [comment(c["body"], "2026-10-16T10:00:00Z", cid=i) for i, c in enumerate(old)] + \
             [comment(c["body"], "2026-10-16T11:00:00Z", cid=10 + i) for i, c in enumerate(new)]
        text, found, missing, sha, severities = fs.pick(pr, [1, 2])
        self.assertEqual((found, missing, sha, severities), ([1], [2], "2222222", ["medium"]))
        self.assertIn("A branch is untested.", text)
        self.assertNotIn("Reviewer, what should happen?", text)
        self.assertNotIn("sdlc-finding", text)
        _, found, _, _, _ = fs.pick(pr, [], everything=True)
        self.assertEqual(found, [1])

    def test_dismissed_needs_a_trusted_reviewer_and_keeps_the_reason(self):
        posted = fs.comments(FINDINGS, "abc1234")
        pr = [comment(c["body"], "2026-10-16T10:00:00Z", cid=i) for i, c in enumerate(posted)]
        pr += [comment("/sdlc dismiss 2 fine for the prototype", "2026-10-16T10:05:00Z", "OWNER", "bala"),
               comment("/sdlc dismiss 1 not a problem", "2026-10-16T10:06:00Z", "NONE", "stranger")]
        text = fs.dismissed(pr)
        self.assertIn('Dismissed by @bala: "fine for the prototype"', text)
        self.assertIn("A branch is untested.", text)
        self.assertNotIn("stranger", text)
        self.assertNotIn("Links not in the design", text)

    def test_load_review_tolerates_a_missing_or_broken_file(self):
        self.assertEqual(fs.load_review(ROOT / "nope.json"), [])


class FindingsWiringTest(unittest.TestCase):
    def wf(self, name):
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_gate_always_updates_its_comment_and_posts_findings(self):
        gate = self.wf("sdlc-pr.yml").split("\n  review-gate:\n", 1)[1].split("\n  advisory:\n", 1)[0]
        self.assertIn('--fail-on "$FAIL_ON" > "$RUNNER_TEMP/verdict.txt" || code=$?', gate,
                      "the step shell has -e: a failing render must not skip the comment")
        self.assertIn("findings.py\" comments .sdlc-output/pr-review.json", gate)
        self.assertIn("minimizeComment", gate)
        self.assertIn("dismissed=.sdlc-input/dismissed.md", gate)
        self.assertLess(gate.index("Findings the reviewer dismissed"), gate.index("Conformance review (sdlc:review-story"))

    def test_fix_findings_is_trusted_scoped_and_keeps_sdlc_files(self):
        wf = self.wf("sdlc-fix-findings.yml")
        self.assertIn('fromJSON(\'["OWNER","MEMBER","COLLABORATOR"]\')', wf)
        self.assertIn("BODY: ${{ github.event.comment.body }}", wf)
        self.assertIn('[[ "$head" != story/* ]] && [[ "$head" != fix/* ]]', wf)
        deny = wf.split('SDLC_WRITE_DENY: "', 1)[1].split('"', 1)[0]
        self.assertNotIn("designs/", deny, "the reviewer may ask for the design to change")
        self.assertIn("plans/", deny)
        self.assertIn("protected=(.github .sdlc .claude intent specs plans releases runbooks CLAUDE.md REVIEW.md)", wf)
        self.assertIn("/sdlc:build-story mode=fix-findings", wf)
        self.assertIn("--allow-empty", wf, "a dismissed high finding re-runs the gate")

    def test_init_routes_the_commands(self):
        a, _ = ip.normalize({"sdlc_ref": "v1.0.0", "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}})
        caller = ip.render_callers(a)[".github/workflows/sdlc-comment.yml"]
        self.assertIn("  findings:\n", caller)
        self.assertIn("sdlc-fix-findings.yml@v1.0.0", caller)
        self.assertIn("startsWith(github.event.comment.body, '/sdlc dismiss')", caller)

    def test_skills_document_the_modes(self):
        review = (PLUGIN / "skills" / "review-story" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("**Dismissed findings** (`dismissed=<path>`)", review)
        build = (PLUGIN / "skills" / "build-story" / "SKILL.md").read_text(encoding="utf-8")
        section = build.split("## Headless fix-findings", 1)[1]
        self.assertIn("Never delete, skip or weaken a test", section)
        self.assertIn("RESULT: FIXED", section)


if __name__ == "__main__":
    unittest.main()
