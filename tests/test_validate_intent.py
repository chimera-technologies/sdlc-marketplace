"""Unit tests for skills/write-intent/scripts/validate_intent.py (stdlib only).

Run from the marketplace repo root:
  python -m unittest discover -s tests -v
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "sdlc" / "skills" / "write-intent"
EXAMPLE = SKILL / "examples" / "claims-status-self-service.md"
OWNERS = SKILL / "examples" / "owners.yaml"

spec = importlib.util.spec_from_file_location("validate_intent", SKILL / "scripts" / "validate_intent.py")
vi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vi)


class ValidateIntentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.example = EXAMPLE.read_text(encoding="utf-8")
        self.owners = vi.load_owners(OWNERS)

    def check(self, text, name="claims-status-self-service", owners="default"):
        path = Path(self.tmp.name) / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        return vi.validate(path, self.owners if owners == "default" else owners)

    def assertError(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r} in {errors}")

    # --- happy path -------------------------------------------------------

    def test_example_is_valid(self):
        fm, errors, warnings = self.check(self.example)
        self.assertEqual(errors, [])
        self.assertEqual(fm["owner"], "@claims-po")
        self.assertEqual(fm["systems"], ["claims-core", "customer-portal"])

    def test_crlf_line_endings(self):
        _, errors, _ = self.check(self.example.replace("\n", "\r\n"))
        self.assertEqual(errors, [])

    def test_unquoted_owner_still_parses(self):
        fm, errors, _ = self.check(self.example.replace('owner: "@claims-po"', "owner: @claims-po"))
        self.assertEqual(errors, [])
        self.assertEqual(fm["owner"], "@claims-po")

    def test_fingerprint_is_optional(self):
        _, errors, _ = self.check(self.example.replace("fingerprint: none\n", ""))
        self.assertEqual(errors, [])

    def test_no_owners_file_skips_membership(self):
        _, errors, _ = self.check(self.example.replace("@claims-po", "@someone-else"), owners=None)
        self.assertEqual(errors, [])

    # --- frontmatter ------------------------------------------------------

    def test_missing_frontmatter(self):
        _, errors, _ = self.check(self.example.split("---\n", 2)[2])
        self.assertError(errors, "missing YAML frontmatter")

    def test_required_key_missing(self):
        _, errors, _ = self.check(self.example.replace("risk: medium\n", ""))
        self.assertError(errors, "'risk' is required")

    def test_enum_values(self):
        _, errors, _ = self.check(self.example.replace("risk: medium", "risk: urgent"))
        self.assertError(errors, "'risk' must be one of")

    def test_id_must_match_file_name(self):
        _, errors, _ = self.check(self.example, name="other-name")
        self.assertError(errors, "must match file name")

    def test_id_must_be_slug(self):
        text = self.example.replace("id: claims-status-self-service", "id: Claims_Status")
        _, errors, _ = self.check(text, name="Claims_Status")
        self.assertError(errors, "kebab-case slug")

    def test_record_id_format(self):
        _, errors, _ = self.check(self.example.replace("record_id: CLM-482", "record_id: clm482"))
        self.assertError(errors, "must be a Jira key")

    def test_jira_source_needs_record_id(self):
        _, errors, _ = self.check(self.example.replace("record_id: CLM-482", "record_id: none"))
        self.assertError(errors, "source 'jira' requires a record_id")

    def test_bad_fingerprint(self):
        _, errors, _ = self.check(self.example.replace("fingerprint: none", "fingerprint: Bad_FP"))
        self.assertError(errors, "fingerprint 'Bad_FP'")

    def test_owner_format(self):
        _, errors, _ = self.check(self.example.replace('"@claims-po"', '"claims-po"'))
        self.assertError(errors, "must be @user or @org/team")

    def test_owner_substring_is_not_enough(self):
        _, errors, _ = self.check(self.example.replace('"@claims-po"', '"@claims"'))
        self.assertError(errors, "not listed in owners file")

    def test_created_date(self):
        _, errors, _ = self.check(self.example.replace("created: 2026-09-28", "created: 28/09/2026"))
        self.assertError(errors, "created must be YYYY-MM-DD")

    def test_systems_must_be_list(self):
        _, errors, _ = self.check(self.example.replace("systems: [claims-core, customer-portal]", "systems: claims-core"))
        self.assertError(errors, "systems must be a list")

    # --- body -------------------------------------------------------------

    def test_missing_h1(self):
        _, errors, _ = self.check(self.example.replace("# Intent: ", "# "))
        self.assertError(errors, "missing H1")

    def test_missing_section(self):
        _, errors, _ = self.check(self.example.replace("## Out of scope", "## Not doing"))
        self.assertError(errors, "missing ['Out of scope']")

    def test_sections_out_of_order(self):
        text = self.example.replace("## Problem", "## TMP").replace("## Proposed outcome", "## Problem").replace("## TMP", "## Proposed outcome")
        _, errors, _ = self.check(text)
        self.assertError(errors, "wrong order")

    def test_placeholder_left_in(self):
        _, errors, _ = self.check(self.example.replace("claims-core API, customer portal", "<e.g. claims-core API>"))
        self.assertError(errors, "unfilled template placeholder")

    def test_filler_in_required_section(self):
        _, errors, _ = self.check(self.example.replace("A customer can see", "TBD. A customer can see"))
        self.assertError(errors, "contains filler")

    def test_evidence_required_for_machine_source(self):
        text = self.example.replace("- Jira CLM-482 (reporter: Priya Nair)\n- Call-reason report, Q3: \"claim status\" is the top call reason", "None.")
        _, errors, _ = self.check(text)
        self.assertError(errors, "'Evidence' is required")

    def test_long_intent_warns_not_errors(self):
        text = self.example.replace("## Proposed outcome", "word " * 800 + "\n\n## Proposed outcome")
        _, errors, warnings = self.check(text)
        self.assertEqual(errors, [])
        self.assertTrue(any("consider splitting" in w for w in warnings))

    # --- template and owners ---------------------------------------------

    def test_template_is_rejected(self):
        _, errors, _ = vi.validate(SKILL / "templates" / "intent.md")
        self.assertError(errors, "unfilled template placeholder")

    def test_load_components(self):
        self.assertEqual(vi.load_components(OWNERS), {"claims-core", "customer-portal"})
        path = Path(self.tmp.name) / "owners.yaml"
        path.write_text('default:\n  product_owner: "@a"\n\ncomponents: {}\n', encoding="utf-8")
        self.assertEqual(vi.load_components(path), set())

    def test_unlisted_system_warns_not_errors(self):
        path = Path(self.tmp.name) / "claims-status-self-service.md"
        path.write_text(self.example.replace("[claims-core, customer-portal]", "[claims-core, to-do-list]"), encoding="utf-8")
        _, errors, warnings = vi.validate(path, self.owners, vi.load_components(OWNERS))
        self.assertEqual(errors, [])
        self.assertTrue(any("'to-do-list' is not a component" in w for w in warnings), warnings)

    def test_unknown_system_is_allowed(self):
        path = Path(self.tmp.name) / "claims-status-self-service.md"
        path.write_text(self.example.replace("[claims-core, customer-portal]", "[unknown]"), encoding="utf-8")
        _, errors, warnings = vi.validate(path, self.owners, set())
        self.assertEqual((errors, warnings), ([], []))

    def test_load_owners(self):
        path = Path(self.tmp.name) / "owners.yaml"
        path.write_text(
            'default:\n  product_owner: "@org/pos"\n  service_owner: @org/sre  # comment\n'
            "components:\n  x:\n    product_owner: '@alice'\n    service_owner: \"@<placeholder>\"\n"
            '    jira_components: ["X"]\n',
            encoding="utf-8",
        )
        self.assertEqual(vi.load_owners(path), {"@org/pos", "@org/sre", "@alice"})


if __name__ == "__main__":
    unittest.main()
