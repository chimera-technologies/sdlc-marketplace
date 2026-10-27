"""Learning an existing codebase: PATTERNS.md and the CLAUDE.md Architecture notes (v0.28.0)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
INIT = PLUGIN / "skills" / "init"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cn = load("codebase_notes", INIT / "scripts" / "codebase_notes.py")
ip = load("init_project", INIT / "scripts" / "init_project.py")
OWNERS = {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")}

FILLED_PATTERNS = """# Coding patterns

Intro kept.

## Project structure

- **Features**: one folder per feature under `src/features/`; shared code in `src/lib/`.

## Errors and validation

- **API errors**: throw `AppError` from `src/lib/errors.ts`; `src/api/middleware.ts:12` turns it into JSON.

## Data access and external calls

- **Database**: only `src/lib/db.ts` talks to Postgres.

## UI components

None: a backend service, no UI.

## State and configuration

- **Config**: read once in `src/lib/config.ts` from the environment.

## Testing

- **Builders**: `tests/builders/*.ts` make test data; tests are named for the story.
"""

ARCHITECTURE = """
## Architecture

An orders API in TypeScript.

- **API**: routes in `src/api/`, one file per resource.
- **Domain**: business rules in `src/features/`, pure functions.
- **Run**: `npm run dev`; tests with `npm test` (see `.sdlc/build.yaml`).
"""


class Repo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def write(self, rel, text="x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def code(self):
        for rel in ("src/features/orders.ts", "src/lib/errors.ts", "src/lib/db.ts", "src/lib/config.ts",
                    "src/api/middleware.ts", "src/api/orders.ts", "tests/builders/order.ts", ".sdlc/build.yaml"):
            self.write(rel)

    def init_files(self):
        a, _ = ip.normalize({"sdlc_ref": "v1.0.0", "owners": OWNERS})
        self.write("PATTERNS.md", ip.render_patterns_md(a))
        self.write("CLAUDE.md", "# Project\n\n" + ip.BEGIN + "\n## SDLC\n- rules\n" + ip.END + "\n")


class StatusTest(Repo):
    def test_has_code_ignores_dependencies_and_sdlc_folders(self):
        for rel in ("node_modules/x/index.js", "specs/a.md", "docs/x.py", ".venv/lib/a.py", "plans/p.md"):
            self.write(rel)
        self.assertFalse(cn.has_code(self.root))
        self.write("app/main.py")
        self.assertTrue(cn.has_code(self.root))

    def test_a_fresh_init_is_the_template(self):
        self.code()
        self.init_files()
        self.assertEqual(cn.status(self.root), {"has_code": True, "patterns": "template", "architecture": False})
        errors = cn.check(self.root)
        self.assertEqual(sum("still empty" in e for e in errors), len(cn.PATTERN_SECTIONS))
        self.assertTrue(any("no '## Architecture' section" in e for e in errors))

    def test_written_notes_pass(self):
        self.code()
        self.init_files()
        self.write("PATTERNS.md", FILLED_PATTERNS)
        claude = self.root / "CLAUDE.md"
        claude.write_text(claude.read_text(encoding="utf-8") + ARCHITECTURE, encoding="utf-8")
        self.assertEqual(cn.check(self.root), [])
        self.assertEqual(cn.status(self.root)["patterns"], "filled")
        self.assertTrue(cn.status(self.root)["architecture"])


class CheckTest(Repo):
    def setUp(self):
        super().setUp()
        self.code()
        self.init_files()
        self.write("PATTERNS.md", FILLED_PATTERNS)
        self.claude = self.root / "CLAUDE.md"
        self.claude.write_text(self.claude.read_text(encoding="utf-8") + ARCHITECTURE, encoding="utf-8")

    def test_a_made_up_path_is_an_error(self):
        self.write("PATTERNS.md", FILLED_PATTERNS.replace("`src/lib/db.ts`", "`src/data/repository.ts`"))
        errors = cn.check(self.root)
        self.assertTrue(any("`src/data/repository.ts` does not exist" in e for e in errors), errors)
        self.assertEqual(cn.status(self.root)["patterns"], "partial")

    def test_a_section_without_a_file_or_a_reason_fails(self):
        self.write("PATTERNS.md", FILLED_PATTERNS.replace("None: a backend service, no UI.", "We use components."))
        self.assertTrue(any("'UI components' must name at least one real file" in e for e in cn.check(self.root)))

    def test_architecture_inside_the_sdlc_block_does_not_count(self):
        text = "# Project\n\n" + ip.BEGIN + "\n## SDLC\n" + ARCHITECTURE + ip.END + "\n"
        self.claude.write_text(text, encoding="utf-8")
        self.assertTrue(any("no '## Architecture' section" in e for e in cn.check(self.root)),
                        "init regenerates the block: the notes must live outside it")

    def test_architecture_needs_substance(self):
        self.claude.write_text("# P\n\n## Architecture\n\n- A thing.\n", encoding="utf-8")
        errors = cn.check(self.root)
        self.assertTrue(any("at least 3 points" in e for e in errors))
        self.assertTrue(any("at least 2 real files" in e for e in errors))

    def test_class_names_and_extensions_are_not_missing_files(self):
        self.write("PATTERNS.md", FILLED_PATTERNS.replace(
            "None: a backend service, no UI.", "- **Buttons**: the `.btn` and `.chip` classes in `src/lib/config.ts`; "
                                                "exports as `.csv`; replies with `res.json`."))
        self.assertEqual(cn.check(self.root), [])

    def test_paths_with_lines_globs_and_folders(self):
        self.assertEqual(cn.cited_paths("`src/a.ts:12` `tests/*.ts` `src/` `npm test` `AppError` `x = 1`"),
                         ["src/a.ts:12", "tests/*.ts", "src/"])

    def test_cli(self):
        script = str(INIT / "scripts" / "codebase_notes.py")
        r = subprocess.run([sys.executable, script, "check", "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, script, "status", "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout)["patterns"], "filled")


class WiringTest(unittest.TestCase):
    def test_the_template_and_the_checker_agree(self):
        a, _ = ip.normalize({"sdlc_ref": "v1.0.0", "owners": OWNERS})
        headings = [l[3:] for l in ip.render_patterns_md(a).splitlines() if l.startswith("## ")]
        self.assertEqual(headings, cn.PATTERN_SECTIONS)
        self.assertEqual((ip.BEGIN, ip.END), (cn.BEGIN, cn.END))

    def test_skills_run_it(self):
        init = (INIT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("- `learn`: go to \"Learn the codebase\"", init)
        self.assertIn("## Learn the codebase", init)
        self.assertIn("4b. **An existing codebase?**", init)
        self.assertIn("codebase_notes.py\" check", init)
        build = (PLUGIN / "skills" / "build-story" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("**An existing codebase without notes**", build)
        self.assertIn("/sdlc:init learn", build)


if __name__ == "__main__":
    unittest.main()
