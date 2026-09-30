"""Tests for the UI design sub-stage (validate_design, export_screens), the
plan's design rule, and the PR review gate (render_review --fail-on)."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "sdlc" / "skills"
SPEC = SKILLS / "write-spec" / "examples" / "claims-status-self-service.md"
DESIGN = SKILLS / "design-ui" / "examples" / "claims-status-self-service"
MOCKUP = SKILLS / "design-ui" / "examples" / "mockup" / "claims-status-self-service"
PLAN = SKILLS / "build-story" / "examples" / "claims-status-self-service-s1.md"
OWNERS = SKILLS / "write-intent" / "examples" / "owners.yaml"
RENDER = SKILLS / "review-spec" / "scripts" / "render_review.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vd = load("validate_design", SKILLS / "design-ui" / "scripts" / "validate_design.py")
ex = load("export_screens", SKILLS / "design-ui" / "scripts" / "export_screens.py")
rm = load("render_mockups", SKILLS / "design-ui" / "scripts" / "render_mockups.py")
vp = load("validate_plan", SKILLS / "build-story" / "scripts" / "validate_plan.py")
PNG = (DESIGN / "screens" / "claim-status-list.png").read_bytes()


class DesignRepo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "specs").mkdir()
        (self.root / "plans").mkdir()
        shutil.copy(SPEC, self.root / "specs" / SPEC.name)
        shutil.copytree(DESIGN, self.root / "designs" / DESIGN.name)
        self.manifest = self.root / "designs" / DESIGN.name / "design.md"
        self.text = self.manifest.read_text(encoding="utf-8")
        self.owners = vd.vi.load_owners(OWNERS)

    def check(self, text=None, images=True):
        if text is not None:
            self.manifest.write_text(text, encoding="utf-8")
        return vd.validate(self.manifest, self.owners, self.root, images)

    def assertError(self, errors, fragment):
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r} in {errors}")


class ValidateDesignTest(DesignRepo):
    def test_example_is_valid(self):
        fm, errors, warnings = self.check()
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(fm["figma_file_key"], "AbC123exampleKey")

    def test_parse_screens(self):
        _, body = vd.vi.parse_frontmatter(self.text)
        rows = vd.parse_screens(body)
        self.assertEqual([r["screen"] for r in rows], ["claim-status-list", "claim-status-empty"])
        self.assertEqual(rows[0]["requirements"], ["REQ-1", "REQ-2"])

    def test_missing_screenshot(self):
        (self.manifest.parent / "screens" / "claim-status-empty.png").unlink()
        _, errors, _ = self.check()
        self.assertError(errors, "claim-status-empty.png not found (run export_screens.py)")
        _, errors, _ = self.check(images=False)
        self.assertEqual(errors, [])

    def test_screenshot_must_be_png(self):
        (self.manifest.parent / "screens" / "claim-status-list.png").write_bytes(b"not a png")
        _, errors, _ = self.check()
        self.assertError(errors, "is not a PNG")

    def test_every_story_on_a_screen_or_no_ui(self):
        _, errors, _ = self.check(self.text.replace("- S2: mapping table in claims-core, no screen.\n", ""))
        self.assertError(errors, "spec story S2 is on no screen")

    def test_unknown_story_and_requirement(self):
        text = self.text.replace("| S3 | REQ-1, REQ-2 |", "| S3, S9 | REQ-1, REQ-42 |")
        _, errors, _ = self.check(text)
        self.assertError(errors, "story S9 is not in the spec")
        self.assertError(errors, "REQ-42 is not in the spec's Requirements")

    def test_node_id_format(self):
        _, errors, _ = self.check(self.text.replace("| 12:34 |", "| frame-a |"))
        self.assertError(errors, "Figma node must look like 1:2")

    def test_screenshot_path_matches_screen_id(self):
        _, errors, _ = self.check(self.text.replace("| screens/claim-status-list.png |", "| screens/list.png |"))
        self.assertError(errors, "screenshot must be screens/claim-status-list.png")

    def test_figma_key_must_match_url(self):
        _, errors, _ = self.check(self.text.replace("figma_file_key: AbC123exampleKey", "figma_file_key: Other"))
        self.assertError(errors, "differs from the URL's 'AbC123exampleKey'")

    def test_folder_must_match_id(self):
        other = self.root / "designs" / "other"
        shutil.move(str(self.manifest.parent), str(other))
        _, errors, _ = vd.validate(other / "design.md", self.owners, self.root)
        self.assertError(errors, "must match its folder designs/other/")

    def test_stray_image_warns(self):
        (self.manifest.parent / "screens" / "old.png").write_bytes(PNG)
        _, errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertTrue(any("old.png is not referenced" in w for w in warnings))

    def test_template_is_rejected(self):
        _, errors, _ = vd.validate(SKILLS / "design-ui" / "templates" / "design.md", None, self.root)
        self.assertError(errors, "unfilled template placeholder")


class ExportScreensTest(DesignRepo):
    def fake(self, images):
        calls = []

        def fetch(url, token=None, timeout=60):
            calls.append((url, token))
            if url.startswith(ex.API):
                return json.dumps({"err": None, "images": images}).encode()
            return PNG

        return fetch, calls

    def test_exports_every_screen_and_sends_token_only_to_the_api(self):
        for p in (self.manifest.parent / "screens").glob("*.png"):
            p.unlink()
        fetch, calls = self.fake({"12:34": "https://s3.example/a.png", "12:58": "https://s3.example/b.png"})
        written = ex.export(self.manifest, "secret-token", 2, fetch)
        self.assertEqual([w[0] for w in written], ["claim-status-list", "claim-status-empty"])
        self.assertTrue((self.manifest.parent / "screens" / "claim-status-empty.png").is_file())
        self.assertIn("ids=12:34,12:58", calls[0][0])
        self.assertEqual(calls[0][1], "secret-token")
        self.assertTrue(all(tok is None for _, tok in calls[1:]), "token leaked to image downloads")
        self.assertEqual(vd.validate(self.manifest, self.owners, self.root)[1], [])

    def test_missing_image_is_an_error(self):
        fetch, _ = self.fake({"12:34": "https://s3.example/a.png"})
        with self.assertRaises(SystemExit) as cm:
            ex.export(self.manifest, "t", 2, fetch)
        self.assertIn("claim-status-empty", str(cm.exception))

    def test_url_style_node_ids_are_normalized(self):
        self.manifest.write_text(self.text.replace("| 12:34 |", "| 12-34 |"), encoding="utf-8")
        _, items = ex.plan_exports(self.manifest)
        self.assertEqual(items[0][1], "12:34")

    def test_no_token_exits_1(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "FIGMA_TOKEN"}
        r = subprocess.run([sys.executable, str(SKILLS / "design-ui" / "scripts" / "export_screens.py"), str(self.manifest)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FIGMA_TOKEN is not set", r.stderr)


class MockupRepo(DesignRepo):
    """The same spec designed as HTML mockups (source: mockup)."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.manifest.parent)
        shutil.copytree(MOCKUP, self.manifest.parent)
        self.text = self.manifest.read_text(encoding="utf-8")
        self.list_html = self.manifest.parent / "mockups" / "claim-status-list.html"


class ValidateMockupTest(MockupRepo):
    def test_example_is_valid(self):
        fm, errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(fm["source"], "mockup")

    def test_figma_keys_not_needed(self):
        text = self.text.replace("figma_file: none\n", "").replace("figma_file_key: none\n", "")
        self.assertEqual(self.check(text)[1], [])

    def test_figma_source_still_needs_them(self):
        _, errors, _ = self.check(self.text.replace("source: mockup", "source: figma"))
        self.assertError(errors, "Figma node must look like 1:2")
        self.assertError(errors, "figma_file must be a https://www.figma.com")

    def test_unknown_source(self):
        self.assertError(self.check(self.text.replace("source: mockup", "source: sketch"))[1], "source must be one of")

    def test_source_path_must_match_screen(self):
        _, errors, _ = self.check(self.text.replace("| mockups/claim-status-empty.html |", "| mockups/empty.html |"))
        self.assertError(errors, "source must be mockups/claim-status-empty.html")

    def test_missing_mockup(self):
        self.list_html.unlink()
        self.assertError(self.check()[1], "claim-status-list.html not found")

    def test_missing_png_points_to_the_renderer(self):
        (self.manifest.parent / "screens" / "claim-status-list.png").unlink()
        self.assertError(self.check()[1], "run render_mockups.py")

    def test_unsafe_mockups_are_rejected(self):
        html = self.list_html.read_text(encoding="utf-8")
        for bad, fragment in [
            ("<script>alert(1)</script>", "<script"),
            ('<img src="https://cdn.example/logo.png">', "remote resources"),
            ('<link rel="stylesheet" href="//fonts.example/a.css">', "remote resources"),
            ("<style>@import 'https://x.example/a.css';</style>", "remote resources"),
            ("<style>body{background:url(http://x.example/a.png)}</style>", "remote resources"),
            ('<button onclick="go()">Go</button>', "event handlers"),
            ('<a href="javascript:go()">Go</a>', "javascript:"),
            ('<iframe src="a.html"></iframe>', "<iframe"),
        ]:
            with self.subTest(bad=bad):
                self.list_html.write_text(html.replace("</main>", bad + "</main>"), encoding="utf-8")
                self.assertError(self.check()[1], fragment)
        self.list_html.write_text(html.replace("</main>", '<img src="data:image/png;base64,iVBOR" alt="">'
                                               '<a href="#top">Top</a></main>'), encoding="utf-8")
        self.assertEqual(self.check()[1], [])

    def test_size_meta(self):
        self.assertEqual(vd.mockup_size('<meta name="sdlc-size" content="390x844">'), (390, 844))
        self.assertEqual(vd.mockup_size("<html></html>"), (1280, 800))


class RenderMockupsTest(MockupRepo):
    def fake_browser(self, calls, write=True):
        def run(cmd, **kwargs):
            calls.append(cmd)
            out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--screenshot="))
            if write:
                Path(out).write_bytes(PNG)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return run

    def test_renders_every_screen_locked_down(self):
        for p in (self.manifest.parent / "screens").glob("*.png"):
            p.unlink()
        calls = []
        written = rm.render(self.manifest, "chrome", self.fake_browser(calls))
        self.assertEqual([w[0] for w in written], ["claim-status-list", "claim-status-empty"])
        self.assertEqual(self.check()[1], [])
        cmd = calls[0]
        self.assertIn("--headless=new", cmd)
        self.assertIn("--window-size=1280,800", cmd)
        self.assertIn("--proxy-server=127.0.0.1:9", cmd)
        # The browser gets a locked copy, never the mockup itself.
        self.assertNotIn(self.list_html.resolve().as_uri(), cmd)

    def test_locked_copy_blocks_scripts_and_loads(self):
        locked = rm.locked_copy("<html><head><title>x</title></head><body></body></html>")
        self.assertTrue(locked.startswith("<html><head><meta http-equiv=\"Content-Security-Policy\""))
        self.assertIn("default-src 'none'", locked)
        self.assertIn("Content-Security-Policy", rm.locked_copy("<html><body></body></html>"))

    def test_no_png_is_an_error(self):
        with self.assertRaises(SystemExit) as cm:
            rm.render(self.manifest, "chrome", self.fake_browser([], write=False))
        self.assertIn("browser wrote no PNG", str(cm.exception))

    def test_unsafe_mockup_is_not_rendered(self):
        self.list_html.write_text("<html><body><script>x()</script></body></html>", encoding="utf-8")
        calls = []
        with self.assertRaises(SystemExit):
            rm.render(self.manifest, "chrome", self.fake_browser(calls))
        self.assertEqual(calls, [])

    def test_figma_manifest_is_refused_and_vice_versa(self):
        figma = self.root / "designs" / "figma" / "design.md"
        figma.parent.mkdir(parents=True)
        shutil.copy(DESIGN / "design.md", figma)
        with self.assertRaises(SystemExit):
            rm.plan_renders(figma)
        with self.assertRaises(SystemExit) as cm:
            ex.plan_exports(self.manifest)
        self.assertIn("render_mockups.py", str(cm.exception))

    @unittest.skipUnless(rm.find_browser(), "no Chrome, Chromium or Edge on this machine")
    def test_real_browser_renders_pngs(self):
        for p in (self.manifest.parent / "screens").glob("*.png"):
            p.unlink()
        rm.render(self.manifest, rm.find_browser())
        self.assertEqual(self.check()[1], [])


class PlanDesignRuleTest(DesignRepo):
    """A plan must name every screen that lists its story."""

    def plan_for(self, story, text):
        p = self.root / "plans" / f"claims-status-self-service-{story.lower()}.md"
        p.write_text(text, encoding="utf-8")
        return vp.validate(p, self.root)[1]

    def s1_plan(self):
        return PLAN.read_text(encoding="utf-8")

    def test_story_without_screens_needs_no_design_section(self):
        self.assertEqual(self.plan_for("S1", self.s1_plan()), [])
        self.assertEqual(vp.story_screens(self.root, "claims-status-self-service", "S1"), [])

    def test_story_with_screens_requires_design_section(self):
        self.manifest.write_text(self.text.replace("| S3 | REQ-1, REQ-2 |", "| S1, S3 | REQ-1, REQ-2 |"), encoding="utf-8")
        self.assertEqual(vp.story_screens(self.root, "claims-status-self-service", "S1"), ["claim-status-list"])
        errors = self.plan_for("S1", self.s1_plan())
        self.assertTrue(any("add a '## Design' section" in e for e in errors), errors)
        with_design = self.s1_plan().replace(
            "## Files", "## Design\n- claim-status-list: designs/claims-status-self-service/screens/claim-status-list.png\n\n## Files")
        self.assertEqual(self.plan_for("S1", with_design), [])

    def test_plan_older_than_design_only_warns(self):
        self.manifest.write_text(self.text.replace("| S3 | REQ-1, REQ-2 |", "| S1, S3 | REQ-1, REQ-2 |"), encoding="utf-8")
        old_plan = self.s1_plan().replace("created: 2026-09-29", "created: 2026-09-01")
        p = self.root / "plans" / "claims-status-self-service-s1.md"
        p.write_text(old_plan, encoding="utf-8")
        _, errors, warnings = vp.validate(p, self.root)
        self.assertEqual(errors, [])
        self.assertTrue(any("predates the design 2026-09-29" in w for w in warnings), warnings)

    def test_design_section_must_name_each_screen(self):
        self.manifest.write_text(self.text.replace("| S3 | REQ-1, REQ-2 |", "| S1, S3 | REQ-1, REQ-2 |"), encoding="utf-8")
        wrong = self.s1_plan().replace("## Files", "## Design\n- claim-status-empty: the empty state\n\n## Files")
        errors = self.plan_for("S1", wrong)
        self.assertTrue(any("must reference screen 'claim-status-list'" in e for e in errors), errors)


class ReviewGateTest(unittest.TestCase):
    def run_render(self, content, fail_on="high"):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "review.json"
            if content is not None:
                src.write_text(json.dumps(content), encoding="utf-8")
            args = [sys.executable, str(RENDER), str(src), "--markdown", str(Path(d) / "o.md"), "--title", "Conformance review"]
            if fail_on:
                args += ["--fail-on", fail_on]
            r = subprocess.run(args, capture_output=True, text=True)
            md = (Path(d) / "o.md").read_text(encoding="utf-8")
        return r.returncode, r.stdout.strip(), md

    def test_clean_passes(self):
        code, verdict, md = self.run_render({"findings": []})
        self.assertEqual((code, verdict), (0, "clean"))
        self.assertTrue(md.startswith("### Conformance review: ✅ clean"))

    def test_medium_passes_high_blocks(self):
        self.assertEqual(self.run_render({"findings": [{"severity": "medium", "issue": "x"}]})[0], 0)
        self.assertEqual(self.run_render({"findings": [{"severity": "high", "issue": "x"}]})[0], 2)
        self.assertEqual(self.run_render({"findings": [{"severity": "medium", "issue": "x"}]}, "medium")[0], 2)

    def test_review_that_did_not_run_blocks(self):
        code, verdict, _ = self.run_render(None)
        self.assertEqual((code, verdict), (2, "failed"))

    def test_without_fail_on_never_blocks(self):
        self.assertEqual(self.run_render({"findings": [{"severity": "high", "issue": "x"}]}, None)[0], 0)


if __name__ == "__main__":
    unittest.main()
