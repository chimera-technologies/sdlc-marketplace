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
        self.assertError(errors, "needs at least one '| SEC-<n> | ... |' or '| INF-<n> | ... |' row")

    def test_infra_policy_rows_count(self):
        # An infrastructure-only spec may cite only infra-policy rules.
        _, errors, _ = self.check(self.spec_text.replace("| SEC-", "| INF-"))
        self.assertFalse(any("Security considerations" in e for e in errors), errors)

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

    def __init__(self, record_type="Epic", existing=(), descriptions=None):
        self.record_type, self.existing, self.calls, self.n = record_type, set(existing), [], 100
        self.descriptions = descriptions or {}   # label -> current description of the existing story

    def issue(self, key):
        return {"fields": {"project": {"key": key.split("-")[0]}, "issuetype": {"name": self.record_type}}}

    def find_by_label(self, label):
        if label in self.existing:
            self.last = label
            return "CLM-1"
        return None

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and "fields=description" in path:
            return {"fields": {"description": self.descriptions.get(self.last)}}
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

    def test_description_numbers_the_criteria(self):
        _, stories = ss.story_payloads(SPEC)
        _, body = vs.vi.parse_frontmatter(SPEC.read_text(encoding="utf-8"))
        s3 = next(s for s in vs.parse_stories(body) if s["id"] == "S3")
        criteria = [l[2:].strip() for l in s3["body"].split("Acceptance criteria:", 1)[1].splitlines() if l.startswith("- ")]
        desc = stories[2]["description"]
        self.assertIn("*Acceptance criteria*", desc)
        self.assertNotIn("Acceptance criteria:", desc)
        for k, c in enumerate(criteria, 1):
            self.assertIn(f"* *AC-{k}:* {c}", desc)
        self.assertTrue(desc.endswith("From spec: specs/claims-status-self-service.md (S3)"))
        self.assertEqual(ss.description("Just text.", "x", "S1"), "Just text.\n\nFrom spec: specs/x.md (S1)")

    def test_existing_story_is_brought_up_to_date(self):
        label = "spec-claims-status-self-service-s1"
        old = "Old text.\n- a\n\nFrom spec: specs/claims-status-self-service.md (S1)\n\nh4. Notes\nAdded by hand."
        jira = FakeJira("Epic", existing={label}, descriptions={label: old})
        result = ss.create_stories(SPEC, jira)
        puts = [(p, b) for m, p, b in jira.calls if m == "PUT"]
        self.assertEqual([p for p, _ in puts], ["/rest/api/2/issue/CLM-1"])
        new = puts[0][1]["fields"]["description"]
        _, stories = ss.story_payloads(SPEC)
        self.assertTrue(new.startswith(stories[0]["description"]))
        self.assertTrue(new.endswith("h4. Notes\nAdded by hand."), "what people added below the From spec line stays")
        self.assertEqual(result["updated"], [{"id": "S1", "key": "CLM-1"}])

    def test_up_to_date_or_foreign_descriptions_are_left_alone(self):
        label = "spec-claims-status-self-service-s1"
        _, stories = ss.story_payloads(SPEC)
        for current in (stories[0]["description"], "Written by a person, no From spec line.", None):
            jira = FakeJira("Epic", existing={label}, descriptions={label: current})
            result = ss.create_stories(SPEC, jira)
            self.assertFalse(any(m == "PUT" for m, _, _ in jira.calls), current)
            self.assertEqual(result["updated"], [])

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

    def no_record_spec(self, d):
        p = Path(d) / "claims-status-self-service.md"
        p.write_text(SPEC.read_text(encoding="utf-8").replace("record_id: CLM-482", "record_id: none"), encoding="utf-8")
        return p

    CFG = {"enabled": "true", "space_key": "ACM", "epic_issue_type": "Epic", "created_label": "intent-created"}

    def test_no_record_creates_the_epic_then_stories(self):
        with tempfile.TemporaryDirectory() as d:
            jira = FakeJira()
            result = ss.create_stories(self.no_record_spec(d), jira, "Story", self.CFG)
        epic = jira.calls[0][2]["fields"]
        self.assertEqual(epic["project"], {"key": "ACM"})
        self.assertEqual(epic["issuetype"], {"name": "Epic"})
        self.assertEqual(epic["summary"], "Let customers check claim status themselves")
        self.assertEqual(epic["labels"], ["from-spec", "spec-claims-status-self-service", "intent-created"])
        self.assertTrue(result["epic_created"])
        self.assertEqual(result["record"], "CLM-101")
        stories = [b["fields"] for _, p, b in jira.calls[1:] if p == "/rest/api/2/issue"]
        self.assertEqual(len(stories), 3)
        self.assertTrue(all(s["parent"] == {"key": "CLM-101"} and s["project"] == {"key": "ACM"} for s in stories))

    def test_rerun_reuses_the_epic(self):
        with tempfile.TemporaryDirectory() as d:
            jira = FakeJira(existing={"spec-claims-status-self-service"})
            result = ss.create_stories(self.no_record_spec(d), jira, "Story", self.CFG)
        self.assertFalse(result["epic_created"])
        self.assertEqual(result["record"], "CLM-1")
        self.assertEqual(len([1 for _, p, _ in jira.calls if p == "/rest/api/2/issue"]), 3, "stories only, no second Epic")

    def test_jira_off_creates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            for cfg in ({"enabled": "false", "space_key": "ACM"}, {"enabled": "true"}, {}):
                jira = FakeJira()
                self.assertIsNone(ss.create_stories(self.no_record_spec(d), jira, "Story", cfg)["record"])
                self.assertEqual(jira.calls, [])

    def test_load_jira_config(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "jira.yaml"
            p.write_text("# c\nenabled: true\nspace_key: ACM   # the space\ncreated_label: \"intent-created\"\n", encoding="utf-8")
            self.assertEqual(ss.load_jira_config(p), {"enabled": "true", "space_key": "ACM", "created_label": "intent-created"})
            self.assertEqual(ss.load_jira_config(Path(d) / "missing.yaml"), {})


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
