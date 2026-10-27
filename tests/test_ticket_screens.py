"""Design screens for a Jira ticket built without a spec (build-story ticket mode, v0.27.0)."""
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
SCRIPTS = PLUGIN / "skills" / "build-story" / "scripts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tb = load("ticket_brief", SCRIPTS / "ticket_brief.py")
vp = load("validate_plan", SCRIPTS / "validate_plan.py")
vd = load("validate_design", PLUGIN / "skills" / "design-ui" / "scripts" / "validate_design.py")
PLAN = (PLUGIN / "skills" / "build-story" / "examples" / "claims-status-self-service-s1.md").read_text(encoding="utf-8")
CRITERIA = ("Returns only claims owned by the given customer (REQ-1).", "Returns status codes, not internal states.",
            "Access is logged with customer ID and time, without claim content.")


def png():
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


class FakeJira:
    base, auth = "https://acme.atlassian.net", "Basic x"

    def __init__(self, attachments):
        self.attachments = attachments

    def call(self, method, path, body=None):
        assert method == "GET" and "fields=attachment" in path, path
        return {"fields": {"attachment": self.attachments}}


class Project(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / ".sdlc").mkdir()
        (self.root / ".sdlc" / "owners.yaml").write_text('owners:\n  product_owner: "@alice"\n', encoding="utf-8")
        (self.root / "tickets").mkdir()
        (self.root / "plans").mkdir()
        (self.root / "tests" / "api").mkdir(parents=True)
        brief = tb.render("CLM-483", "Customer claim status: endpoint",
                          "Acceptance criteria:\n" + "\n".join(f"- {c}" for c in CRITERIA), created="2026-10-27")
        (self.root / "tickets" / "clm-483.md").write_text(brief, encoding="utf-8")
        self.shots = self.root / "designs" / "clm-483" / "screens"

    def put(self, name, data):
        self.shots.mkdir(parents=True, exist_ok=True)
        (self.shots / name).write_bytes(data)


class LocalScreensTest(Project):
    def test_images_in_the_folder_become_the_design(self):
        self.put("Claim Status (Empty).png", png())
        self.put("detail.JPG", JPEG)
        self.put("notes.txt", b"not an image")
        result = tb.screens("CLM-483", self.root)
        self.assertEqual(result["screens"], ["claim-status-empty", "detail"])
        self.assertEqual(result["errors"], [])
        names = sorted(p.name for p in self.shots.iterdir())
        self.assertEqual(names, ["claim-status-empty.png", "detail.jpg", "notes.txt"], "renamed to their screen ids")
        manifest = (self.root / "designs" / "clm-483" / "design.md").read_text(encoding="utf-8")
        self.assertIn("spec: tickets/clm-483.md", manifest)
        self.assertIn("source: images", manifest)
        self.assertIn('owner: "@alice"', manifest)
        self.assertIn("| claim-status-empty | Claim Status (Empty).png | screens/claim-status-empty.png | S1 | - |", manifest)
        _, errors, _ = vd.validate(self.root / "designs" / "clm-483" / "design.md", root=self.root)
        self.assertEqual(errors, [])

    def test_the_plan_must_name_the_screens(self):
        self.put("status.png", png())
        tb.screens("CLM-483", self.root)
        base = (PLAN.replace("id: claims-status-self-service-s1", "id: clm-483-s1")
                .replace("spec: specs/claims-status-self-service.md", "spec: tickets/clm-483.md")
                .replace("created: 2026-09-29", "created: 2026-10-27"))
        plan = self.root / "plans" / "clm-483-s1.md"
        plan.write_text(base, encoding="utf-8")
        _, errors, _ = vp.validate(plan, self.root)
        self.assertTrue(any("'## Design' section" in e for e in errors), errors)
        plan.write_text(base.replace("## Files", "## Design\n- status: designs/clm-483/screens/status.png\n\n## Files"),
                        encoding="utf-8")
        _, errors, _ = vp.validate(plan, self.root)
        self.assertEqual(errors, [])

    def test_no_screens_writes_nothing(self):
        result = tb.screens("CLM-483", self.root)
        self.assertEqual(result["screens"], [])
        self.assertIsNone(result["manifest"])
        self.assertFalse((self.root / "designs").exists(), "no empty folders left behind")

    def test_a_design_made_another_way_is_left_alone(self):
        d = self.root / "designs" / "clm-483"
        d.mkdir(parents=True)
        (d / "design.md").write_text("---\nid: clm-483\nsource: mockup\n---\n", encoding="utf-8")
        self.put("x.png", png())
        result = tb.screens("CLM-483", self.root)
        self.assertIn("left as it is", result["notes"][0])
        self.assertIn("source: mockup", (d / "design.md").read_text(encoding="utf-8"))

    def test_an_owner_is_needed(self):
        (self.root / ".sdlc" / "owners.yaml").unlink()
        self.put("x.png", png())
        with self.assertRaises(SystemExit):
            tb.screens("CLM-483", self.root)
        self.assertEqual(tb.screens("CLM-483", self.root, owner="@bob")["errors"], [])


class DownloadTest(Project):
    def test_image_attachments_are_downloaded(self):
        jira = FakeJira([
            {"id": "1", "filename": "Status screen.png", "mimeType": "image/png", "size": 100},
            {"id": "2", "filename": "photo.jpeg", "mimeType": "image/jpeg", "size": 100},
            {"id": "3", "filename": "spec.pdf", "mimeType": "application/pdf", "size": 100},
            {"id": "4", "filename": "huge.png", "mimeType": "image/png", "size": tb.MAX_IMAGE_BYTES + 1},
            {"id": "5", "filename": "fake.png", "mimeType": "image/png", "size": 10},
        ])
        bodies = {"1": png(), "2": JPEG, "5": b"<html>not an image</html>"}
        asked = []

        def download(_, attachment_id):
            asked.append(attachment_id)
            return bodies[attachment_id]

        result = tb.screens("CLM-483", self.root, jira=jira, download=download)
        self.assertEqual(asked, ["1", "2", "5"], "no PDF, nothing over the size limit")
        self.assertEqual(result["downloaded"], 2)
        self.assertEqual(sorted(result["screens"]), ["photo", "status-screen"])
        self.assertTrue(any("huge.png" in n for n in result["notes"]))
        self.assertTrue(any("fake.png" in n and "not a PNG or JPEG" in n for n in result["notes"]))
        manifest = (self.root / "designs" / "clm-483" / "design.md").read_text(encoding="utf-8")
        self.assertIn("| status-screen | Status screen.png | screens/status-screen.png | S1 | - |", manifest)
        self.assertEqual(result["errors"], [])

    def test_a_rerun_replaces_rather_than_duplicates(self):
        jira = FakeJira([{"id": "1", "filename": "s.png", "mimeType": "image/png", "size": 10}])
        for _ in range(2):
            result = tb.screens("CLM-483", self.root, jira=jira, download=lambda *_: png())
        self.assertEqual(result["screens"], ["s"])
        self.assertEqual(sorted(p.name for p in self.shots.iterdir()), ["s.png"])

    def test_the_download_asks_jira_for_the_content_itself(self):
        captured = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return png()

        def fake_urlopen(req, timeout):
            captured["url"], captured["auth"] = req.full_url, req.get_header("Authorization")
            return Resp()

        real = tb.urllib.request.urlopen
        tb.urllib.request.urlopen = fake_urlopen
        try:
            tb.jira_download(FakeJira([]), "10001")
        finally:
            tb.urllib.request.urlopen = real
        self.assertEqual(captured["url"], "https://acme.atlassian.net/rest/api/3/attachment/content/10001?redirect=false")
        self.assertEqual(captured["auth"], "Basic x")


class ValidateDesignTest(Project):
    def manifest(self, spec="tickets/clm-483.md", shot="screens/s.jpg", data=JPEG):
        self.put(Path(shot).name, data)
        d = self.root / "designs" / "clm-483"
        text = tb.design_manifest("clm-483", "T", "@alice", [("s", Path(shot).name, "s.jpg")], created="2026-10-27")
        (d / "design.md").write_text(text.replace("spec: tickets/clm-483.md", f"spec: {spec}"), encoding="utf-8")
        return vd.validate(d / "design.md", root=self.root)[1]

    def test_a_jpeg_screen_from_a_ticket_is_valid(self):
        self.assertEqual(self.manifest(), [])

    def test_a_wrong_spec_or_a_fake_jpeg_is_rejected(self):
        self.assertTrue(any("spec must be" in e for e in self.manifest(spec="notes/clm-483.md")))
        self.assertTrue(any("is not a JPEG" in e for e in self.manifest(data=b"nope")))

    def test_mockup_designs_still_need_a_png(self):
        d = self.root / "designs" / "clm-483"
        self.put("s.jpg", JPEG)
        (d / "design.md").write_text(tb.design_manifest("clm-483", "T", "@alice", [("s", "s.jpg", "s")], created="2026-10-27")
                                     .replace("source: images", "source: mockup"), encoding="utf-8")
        errors = vd.validate(d / "design.md", root=self.root)[1]
        self.assertTrue(any("screenshot must be screens/s.png" in e for e in errors), errors)


class CliTest(Project):
    def test_screens_without_jira_uses_the_folder(self):
        self.put("a.png", png())
        r = subprocess.run([sys.executable, str(SCRIPTS / "ticket_brief.py"), "screens", "clm-483", "--root", str(self.root)],
                           capture_output=True, text=True, env={"PATH": ""})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Jira environment not set", r.stderr)
        self.assertEqual(json.loads(r.stdout)["screens"], ["a"])

    def test_skill_runs_it_in_ticket_mode(self):
        skill = (PLUGIN / "skills" / "build-story" / "SKILL.md").read_text(encoding="utf-8")
        section = skill.split("### Ticket mode", 1)[1].split("\n## ", 1)[0]
        self.assertIn('ticket_brief.py" screens <KEY>', section)
        self.assertIn("designs/<key-lowercase>/", section)


if __name__ == "__main__":
    unittest.main()
