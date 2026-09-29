"""Tests for the Design stage: validate_spec.py, spec_stories.py, render_review.py."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "sdlc" / "skills"
INTENT = SKILLS / "write-intent" / "examples" / "claims-status-self-service.md"
SPEC = SKILLS / "write-spec" / "examples" / "claims-status-self-service.md"
OWNERS = SKILLS / "write-intent" / "examples" / "owners.yaml"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vs = load("validate_spec", SKILLS / "write-spec" / "scripts" / "validate_spec.py")
ss = load("spec_stories", SKILLS / "write-spec" / "scripts" / "spec_stories.py")
rr = load("render_review", SKILLS / "review-spec" / "scripts" / "render_review.py")


class RepoCase(unittest.TestCase):
    """A throwaway repo root with intent/ and specs/ holding the examples."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "intent").mkdir()
        (self.root / "specs").mkdir()
        shutil.copy(INTENT, self.root / "intent" / INTENT.name)
        self.spec_text = SPEC.read_text(encoding="utf-8")
        self.owners = vs.vi.load_owners(OWNERS)

    def check(self, text=None, name="claims-status-self-service"):
        path = self.root / "specs" / f"{name}.md"
        path.write_text(self.spec_text if text is None else text, encoding="utf-8")
        return vs.validate(path, self.owners, self.root)

    def assertError(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r} in {errors}")


class ValidateSpecTest(RepoCase):
    def test_example_is_valid(self):
        fm, errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(fm["record_id"], "CLM-482")

    def test_template_is_rejected(self):
        _, errors, _ = vs.validate(SKILLS / "write-spec" / "templates" / "spec.md", None, self.root)
        self.assertError(errors, "unfilled template placeholder")

    def test_intent_path_must_match_slug(self):
        _, errors, _ = self.check(self.spec_text.replace("intent: intent/claims-status-self-service.md", "intent: intent/other.md"))
        self.assertError(errors, "intent must be 'intent/claims-status-self-service.md'")

    def test_record_id_must_match_intent(self):
        _, errors, _ = self.check(self.spec_text.replace("record_id: CLM-482", "record_id: CLM-999"))
        self.assertError(errors, "differs from the intent's 'CLM-482'")

    def test_tech_lead_required_when_high_risk(self):
        text = self.spec_text.replace("risk: medium", "risk: high").replace('tech_lead: "@claims-tech-lead"\n', "")
        _, errors, _ = self.check(text)
        self.assertError(errors, "tech_lead is required when risk is high")

    def test_unknown_owner_rejected(self):
        _, errors, _ = self.check(self.spec_text.replace('owner: "@claims-po"', 'owner: "@nobody"'))
        self.assertError(errors, "owner '@nobody' is not listed")

    def test_every_intent_question_must_be_carried(self):
        text = self.spec_text.replace(
            "| OQ-2 | intent | Should customers be notified", "| OQ-2 | spec | Should customers be notified")
        _, errors, _ = self.check(text)
        self.assertError(errors, "the intent has 2 open questions but only 1 rows")

    def test_open_question_status(self):
        _, errors, _ = self.check(self.spec_text.replace("| open | Claims Operations", "| maybe | Claims Operations"))
        self.assertError(errors, "status must be one of")

    def test_missing_section(self):
        _, errors, _ = self.check(self.spec_text.replace("## Technology and architecture", "## Stack"))
        self.assertError(errors, "missing ['Technology and architecture']")

    def test_requirements_need_req_rows(self):
        _, errors, _ = self.check(self.spec_text.replace("| REQ-", "| R-"))
        self.assertError(errors, "needs at least one '| REQ-<n> | ... |' row")

    def test_security_needs_sec_rows(self):
        _, errors, _ = self.check(self.spec_text.replace("| SEC-", "| RULE-"))
        self.assertError(errors, "'| SEC-<n> | ... |' row")

    def test_stories_need_acceptance_criteria(self):
        text = self.spec_text.replace(
            "Acceptance criteria:\n- Every internal state maps to exactly one customer status.\n"
            "- Wording matches the Legal-approved table (REQ-2).\n", "")
        _, errors, _ = self.check(text)
        self.assertError(errors, "story S2 needs 'Acceptance criteria:'")

    def test_duplicate_story_ids(self):
        _, errors, _ = self.check(self.spec_text.replace("### S3:", "### S2:"))
        self.assertError(errors, "story id S2 is used twice")

    def test_missing_intent_only_warns(self):
        (self.root / "intent" / INTENT.name).unlink()
        _, errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertTrue(any("not found" in w for w in warnings))

    def test_parse_stories(self):
        _, body = vs.vi.parse_frontmatter(self.spec_text)
        stories = vs.parse_stories(body)
        self.assertEqual([s["id"] for s in stories], ["S1", "S2", "S3"])
        self.assertTrue(stories[0]["body"].startswith("Read-only endpoint"))
        self.assertIn("Acceptance criteria:", stories[2]["body"])


class FakeJira:
    """Records calls; answers like Jira for the endpoints spec_stories uses."""

    def __init__(self, record_type="Epic", existing=()):
        self.record_type, self.existing, self.calls, self.n = record_type, set(existing), [], 100

    def issue(self, key):
        return {"fields": {"project": {"key": key.split("-")[0]}, "issuetype": {"name": self.record_type}}}

    def find_by_label(self, label):
        return "CLM-1" if label in self.existing else None

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith("/issue"):
            self.n += 1
            return {"key": f"CLM-{self.n}"}
        return {}


class SpecStoriesTest(unittest.TestCase):
    def test_payloads(self):
        fm, stories = ss.story_payloads(SPEC)
        self.assertEqual(fm["record_id"], "CLM-482")
        self.assertEqual(stories[0]["summary"], "S1: Customer claim status endpoint in claims-core")
        self.assertEqual(stories[0]["labels"], ["from-spec", "spec-claims-status-self-service-s1"])
        self.assertIn("From spec: specs/claims-status-self-service.md (S1)", stories[0]["description"])

    def test_creates_under_epic(self):
        jira = FakeJira("Epic")
        result = ss.create_stories(SPEC, jira)
        self.assertEqual([c["id"] for c in result["created"]], ["S1", "S2", "S3"])
        creates = [b for m, p, b in jira.calls if p == "/rest/api/2/issue"]
        self.assertTrue(all(b["fields"]["parent"] == {"key": "CLM-482"} for b in creates))
        self.assertFalse(any(p.endswith("issueLink") for _, p, _ in jira.calls))

    def test_links_when_record_is_not_epic(self):
        jira = FakeJira("Task")
        ss.create_stories(SPEC, jira)
        creates = [b for m, p, b in jira.calls if p == "/rest/api/2/issue"]
        self.assertTrue(all("parent" not in b["fields"] for b in creates))
        self.assertEqual(sum(p.endswith("issueLink") for _, p, _ in jira.calls), 3)

    def test_idempotent(self):
        jira = FakeJira("Epic", existing={"spec-claims-status-self-service-s1", "spec-claims-status-self-service-s2"})
        result = ss.create_stories(SPEC, jira)
        self.assertEqual([c["id"] for c in result["created"]], ["S3"])
        self.assertEqual([e["id"] for e in result["existing"]], ["S1", "S2"])

    def test_no_record_skips(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "claims-status-self-service.md"
            p.write_text(SPEC.read_text(encoding="utf-8").replace("record_id: CLM-482", "record_id: none"), encoding="utf-8")
            jira = FakeJira()
            result = ss.create_stories(p, jira)
        self.assertEqual(result["created"], [])
        self.assertEqual(jira.calls, [])


class RenderReviewTest(unittest.TestCase):
    def render(self, content):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "review.json"
            if content is not None:
                p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            review, problem = rr.load(p)
            return rr.render(review, problem)

    def test_clean(self):
        md, verdict = self.render({"verdict": "clean", "summary": "Looks fine.", "findings": []})
        self.assertEqual(verdict, "clean")
        self.assertIn("0 high", md)

    def test_verdict_derived_from_findings_not_trusted(self):
        md, verdict = self.render({"verdict": "clean", "findings": [
            {"severity": "low", "section": "Summary", "issue": "Wordy."},
            {"severity": "high", "section": "Context", "issue": "Invented endpoint.", "evidence": "no such file"}]})
        self.assertEqual(verdict, "concerns")
        self.assertLess(md.index("Invented endpoint"), md.index("Wordy"))  # high first

    def test_missing_or_bad_file_is_failed(self):
        self.assertEqual(self.render(None)[1], "failed")
        self.assertEqual(self.render("{not json")[1], "failed")
        self.assertEqual(self.render('["a list"]')[1], "failed")


if __name__ == "__main__":
    unittest.main()
