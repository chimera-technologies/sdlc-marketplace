"""Tests for the repository layout: one repo, or one repo per service (a system repo and its service repos)."""
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
SKILLS = ROOT / "plugins" / "sdlc" / "skills"
INIT = SKILLS / "init" / "scripts" / "init_project.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ip = load("init_project", INIT)
vs = load("validate_spec", SKILLS / "write-spec" / "scripts" / "validate_spec.py")

OWNERS = {"product_owner": "@po", "service_owner": "@acme/sre", "tech_lead": "@lead"}
ANSWERS = {"sdlc_ref": "v0.30.0", "owners": OWNERS,
           "jira": {"enabled": True, "site": "acme.atlassian.net", "space_key": "SHOP"}}
ORDERS_STACK = {"toolchains": ["java@21"], "install_command": "mvn -B -q -DskipTests install",
                "test_command": "mvn -B test", "test_file_command": "mvn -B test -Dtest={file}"}
LAYOUT = {"decided": True, "layout": "per-service", "services": [
    {"component": "orders", "repo": "acme/shop-orders", "ui": False, "stack": ORDERS_STACK,
     "owners": {"product_owner": "@ord-po", "service_owner": "@acme/ord-sre", "tech_lead": "@be-lead"}},
    {"component": "storefront", "repo": "acme/shop-storefront", "ui": True, "stack": {},
     "owners": {"product_owner": "@web-po"}},
]}


class Result:
    def __init__(self, stdout, returncode=0):
        self.stdout, self.returncode = stdout, returncode


def fake_gh(responses):
    """A subprocess.run stand-in: the first response whose key is in the joined gh arguments."""
    def run(args, **_):
        joined = " ".join(args)
        for key, value in responses.items():
            if key in joined:
                return Result(json.dumps(value)) if value is not None else Result("", 1)
        return Result("", 1)
    return run


class RepoCase(unittest.TestCase):
    """A throwaway git repo with a GitHub origin."""

    origin = "acme/shop-system"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{self.origin}.git"], cwd=self.root, check=True)

    def init(self, *args, answers=None):
        if answers is not None:
            path = self.root / "answers.json"
            path.write_text(json.dumps(answers), encoding="utf-8")
            args = ("--answers", str(path), *args)
        return subprocess.run([sys.executable, str(INIT), "--root", str(self.root), *args], capture_output=True, text=True)

    def record(self, proposal):
        path = self.root / "stack.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        return self.init("--stack", str(path))

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def sdlc(self):
        return json.loads(self.read(".sdlc/sdlc.json"))


class NormalizeTest(unittest.TestCase):
    def test_roles_are_validated(self):
        self.assertIn("role must be one of", " ".join(ip.normalize({**ANSWERS, "role": "mono"})[1]))
        self.assertIn("repo must be this system repo", " ".join(ip.normalize({**ANSWERS, "role": "system"})[1]))
        errors = " ".join(ip.normalize({**ANSWERS, "role": "service", "component": "Orders"})[1])
        self.assertIn("system_repo must be", errors)
        self.assertIn("component must be", errors)
        self.assertIn("repo must be owner/name",
                      " ".join(ip.normalize({**ANSWERS, "components": [{"name": "orders", "repo": "shop-orders"}]})[1]))

    def test_system_repo_has_no_code_stages(self):
        a, errors = ip.normalize({**ANSWERS, "role": "system", "repo": "acme/shop-system"})
        self.assertEqual(errors, [])
        for stage in ip.SYSTEM_STAGES_OFF:
            self.assertFalse(a["stages"][stage], stage)
        self.assertTrue(a["stages"]["plan"] and a["stages"]["design"])

    def test_single_repo_sdlc_json_is_unchanged(self):
        a, _ = ip.normalize(ANSWERS)
        self.assertEqual(a["role"], "single")
        self.assertNotIn("role", json.loads(ip.render_sdlc_json(a)))


class SystemRepoTest(RepoCase):
    def test_setup_as_system_repo(self):
        r = self.init(answers={**ANSWERS, "role": "system", "repo": "acme/shop-system"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sdlc()["role"], "system")
        workflows = sorted(p.name for p in (self.root / ".github" / "workflows").iterdir())
        self.assertNotIn("sdlc-maintain.yml", workflows)
        push = self.read(".github/workflows/sdlc-push.yml")
        self.assertIn("sdlc-spec-to-stack.yml", push)  # the Service map is still recorded
        self.assertNotIn("sdlc-build.yml", push)
        self.assertNotIn("sdlc-release.yml", push)
        self.assertNotIn("sdlc-pr.yml", self.read(".github/workflows/sdlc-pull-request.yml"))
        self.assertIn("System repo", self.read("CLAUDE.md"))
        self.assertIn("/sdlc:init system=acme/shop-system", r.stdout)

    def test_recording_the_service_map(self):
        self.init(answers=ANSWERS)
        r = self.record(LAYOUT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sdlc()["role"], "system")
        self.assertEqual(self.sdlc()["repo"], "acme/shop-system")
        comps = {c["name"]: c for c in ip.read_components(self.read(".sdlc/owners.yaml"))}
        self.assertEqual(comps["orders"]["repo"], "acme/shop-orders")
        self.assertEqual(comps["orders"]["tech_lead"], "@be-lead")
        self.assertEqual(comps["storefront"]["service_owner"], "@acme/sre")  # the default fills a gap
        vi = vs.vi
        self.assertEqual(vi.load_components(self.root / ".sdlc" / "owners.yaml"), {"orders", "storefront"})
        self.assertIn("@acme/ord-sre", vi.load_owners(self.root / ".sdlc" / "owners.yaml"))

        orders = json.loads(self.read("services/shop-orders.answers.json"))
        self.assertEqual((orders["role"], orders["system_repo"], orders["component"], orders["repo"]),
                         ("service", "acme/shop-system", "orders", "acme/shop-orders"))
        self.assertEqual(orders["stack"], ORDERS_STACK)
        self.assertEqual(orders["owners"]["product_owner"], "@ord-po")
        self.assertEqual(orders["owners"]["security_owner"], "@lead")
        self.assertEqual(orders["jira"]["space_key"], "SHOP")
        self.assertFalse(orders["stages"]["ui_design"])
        self.assertTrue(json.loads(self.read("services/shop-storefront.answers.json"))["stages"]["ui_design"])
        self.assertEqual(self.init("--check-stack-files").returncode, 0)
        # The callers follow on the next init (a bot cannot change workflow files).
        self.assertEqual(self.init("--check").returncode, 1)

    def test_the_repo_name_comes_from_its_own_remote(self):
        # In CI, GITHUB_REPOSITORY is the repo running the job, not necessarily the one being written.
        self.init(answers=ANSWERS)
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "acme/somewhere-else"}):
            self.assertEqual(self.record(LAYOUT).returncode, 0)
        self.assertEqual(self.sdlc()["repo"], "acme/shop-system")
        self.assertEqual(json.loads(self.read("services/shop-orders.answers.json"))["system_repo"], "acme/shop-system")

    def test_rerunning_init_keeps_the_layout(self):
        self.init(answers=ANSWERS)
        self.assertTrue((self.root / ".github" / "workflows" / "sdlc-maintain.yml").is_file())
        self.record(LAYOUT)
        r = self.init(answers=ANSWERS)  # no role in the answers
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sdlc()["role"], "system")
        self.assertIn("removed   .github/workflows/sdlc-maintain.yml", r.stdout)
        self.assertFalse((self.root / ".github" / "workflows" / "sdlc-maintain.yml").exists())
        self.assertEqual(self.init("--check").returncode, 0, self.init("--check").stderr)

    def test_upgrade_moves_the_services_pin_and_keeps_their_stack(self):
        self.init(answers=ANSWERS)
        self.record(LAYOUT)
        self.init(answers=ANSWERS)
        r = self.init("--upgrade", "v0.31.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        orders = json.loads(self.read("services/shop-orders.answers.json"))
        self.assertEqual(orders["sdlc_ref"], "v0.31.0")
        self.assertEqual(orders["stack"], ORDERS_STACK)

    def test_hand_edited_answers_are_checked(self):
        self.init(answers=ANSWERS)
        self.record(LAYOUT)
        path = self.root / "services" / "shop-orders.answers.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["system_repo"] = "acme/other"
        data["stack"]["test_file_command"] = "mvn test"
        path.write_text(json.dumps(data), encoding="utf-8")
        r = self.init("--check-stack-files")
        self.assertEqual(r.returncode, 1)
        self.assertIn("system_repo 'acme/shop-system'", r.stderr)
        self.assertIn("test_file_command must contain {file}", r.stderr)

    def test_services_status(self):
        self.init(answers=ANSWERS)
        self.record(LAYOUT)
        run = fake_gh({
            "repos/acme/shop-orders/contents/.sdlc/sdlc.json": {"role": "service", "system_repo": "acme/shop-system",
                                                               "component": "orders", "sdlc_ref": "v0.30.0"},
            "repos/acme/shop-orders": {"name": "shop-orders"},
            "repos/acme/shop-storefront": None,
        })
        status = {s["component"]: s for s in ip.services_status(self.root, run)}
        self.assertTrue(status["orders"]["set_up"])
        self.assertEqual(status["orders"]["next"], "ready")
        self.assertFalse(status["storefront"]["exists"])
        self.assertIn("create the repo acme/shop-storefront", status["storefront"]["next"])

    def test_services_status_needs_a_system_repo(self):
        self.init(answers=ANSWERS)
        self.assertIsNone(ip.services_status(self.root, fake_gh({})))


class ProposalTest(unittest.TestCase):
    def test_valid_layout(self):
        self.assertEqual(ip.validate_stack(LAYOUT), [])

    def test_layout_needs_services(self):
        self.assertIn("needs services", " ".join(ip.validate_stack({"layout": "per-service"})))
        self.assertIn("layout must be one of", " ".join(ip.validate_stack({"layout": "mono"})))

    def test_system_repo_has_no_stack(self):
        errors = " ".join(ip.validate_stack({**LAYOUT, "test_command": "pytest -q"}))
        self.assertIn("the system repo has no code", errors)

    def test_services_are_checked(self):
        services = [dict(LAYOUT["services"][0]), dict(LAYOUT["services"][0], component="Orders 2"),
                    {"component": "pay", "repo": "pay", "ui": "no", "owners": {"tech_lead": "lead"},
                     "stack": {"test_command": ""}}]
        errors = " ".join(ip.validate_stack({"layout": "per-service", "services": services}))
        for frag in ("appears once", "component must be kebab-case", "repo must be owner/name", "ui must be true or false",
                     "owners must map roles", "services[pay].stack: test_command is required"):
            self.assertIn(frag, errors)

    def test_one_repo_has_no_services(self):
        self.assertIn("only for layout per-service",
                      " ".join(ip.validate_stack({**ORDERS_STACK, "services": LAYOUT["services"]})))


class ServiceRepoTest(RepoCase):
    origin = "acme/shop-orders"

    def system_answers(self):
        """The answers file a system repo writes for shop-orders."""
        with tempfile.TemporaryDirectory() as tmp:
            system = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=system, check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/shop-system.git"], cwd=system, check=True)
            (system / "a.json").write_text(json.dumps(ANSWERS), encoding="utf-8")
            (system / "s.json").write_text(json.dumps(LAYOUT), encoding="utf-8")
            for args in (["--answers", "a.json"], ["--stack", "s.json"]):
                subprocess.run([sys.executable, str(INIT), "--root", str(system), *args], cwd=system, check=True,
                               capture_output=True)
            return json.loads((system / "services" / "shop-orders.answers.json").read_text(encoding="utf-8"))

    def test_setup_from_the_system_answers(self):
        r = self.init(answers=self.system_answers())
        self.assertEqual(r.returncode, 0, r.stderr)
        sdlc = self.sdlc()
        self.assertEqual((sdlc["role"], sdlc["system_repo"], sdlc["component"]), ("service", "acme/shop-system", "orders"))
        self.assertIn("test_command: mvn -B test", self.read(".sdlc/build.yaml"))
        self.assertIn('product_owner: "@ord-po"', self.read(".sdlc/owners.yaml"))
        self.assertIn("Service `orders`", self.read("CLAUDE.md"))
        self.assertIn("sdlc-build.yml", self.read(".github/workflows/sdlc-push.yml"))
        self.assertEqual(self.init("--check").returncode, 0)

    def test_answers_for_another_repo_are_refused(self):
        answers = self.system_answers()
        subprocess.run(["git", "remote", "set-url", "origin", "git@github.com:acme/shop-catalog.git"], cwd=self.root, check=True)
        r = self.init(answers=answers)
        self.assertEqual(r.returncode, 1)
        self.assertIn("these answers are for acme/shop-orders, but this repo is acme/shop-catalog", r.stderr)
        self.assertFalse((self.root / ".sdlc").exists())

    def test_fetch_service_answers(self):
        answers = self.system_answers()
        run = fake_gh({"repo view": {"nameWithOwner": "acme/shop-orders"},
                       "repos/acme/shop-system/contents/services/shop-orders.answers.json": answers})
        data, errors = ip.fetch_service_answers(self.root, "acme/shop-system", run)
        self.assertEqual(errors, [])
        self.assertEqual(data["component"], "orders")

    def test_fetch_without_a_file_explains(self):
        run = fake_gh({"repo view": {"nameWithOwner": "acme/shop-orders"}})
        data, errors = ip.fetch_service_answers(self.root, "acme/shop-system", run)
        self.assertIsNone(data)
        self.assertIn("has no services/shop-orders.answers.json", errors[0])
        self.assertIn("system must be", ip.fetch_service_answers(self.root, "shop-system", run)[1][0])

    def test_fetch_from_the_wrong_system_repo(self):
        answers = self.system_answers()
        run = fake_gh({"repo view": {"nameWithOwner": "acme/shop-orders"},
                       "contents/services/shop-orders.answers.json": answers})
        _, errors = ip.fetch_service_answers(self.root, "acme/legacy-system", run)
        self.assertIn("names system_repo 'acme/shop-system'", " ".join(errors))


class ReadComponentsTest(unittest.TestCase):
    def test_comments_and_lists(self):
        text = ("default:\n  product_owner: \"@po\"\n\ncomponents:\n  # services\n  orders:\n"
                "    tech_lead: \"@lead\"   # backend\n    jira_components: [\"Orders\", \"Cart\"]\n"
                "    repo: \"acme/shop-orders\"     # where the code lives\n  web:\n    product_owner: \"@w\"\n"
                "other: 1\n")
        comps = ip.read_components(text)
        self.assertEqual(comps, [{"name": "orders", "tech_lead": "@lead", "jira_components": ["Orders", "Cart"],
                                  "repo": "acme/shop-orders"}, {"name": "web", "product_owner": "@w"}])
        self.assertEqual(ip.read_components("components: {}\n"), [])


SERVICE_MAP = """Repository layout: one repo per service (teams own their services)

| Component | Responsibility | Owns data | Repo | Stack | UI | Product owner | Service owner | Tech lead |
|---|---|---|---|---|---|---|---|---|
| orders | Cart and checkout | carts, orders | shop-orders | Java 21 | no | @ord-po | @acme/ord-sre | @be-lead |
| storefront | Web shop | none | acme/shop-storefront | Node 22 | yes | @web-po | @acme/web-sre | @web-lead |
"""


class SpecLayoutTest(unittest.TestCase):
    def test_no_layout_line_is_fine(self):
        self.assertEqual(vs.check_layout("Existing stack, no new technology."), [])

    def test_one_repo_and_decision_needed(self):
        self.assertEqual(vs.parse_layout("- **Repository layout:** one repo")[0], "one-repo")
        self.assertEqual(vs.check_layout("Repository layout: one repo"), [])
        self.assertEqual(vs.check_layout("Repository layout: decision needed\nDecision needed from: tech lead"), [])

    def test_per_service_with_a_map(self):
        self.assertEqual(vs.parse_layout(SERVICE_MAP)[0], "per-service")
        self.assertEqual(vs.check_layout(SERVICE_MAP), [])
        _, rows = vs.parse_service_map(SERVICE_MAP)
        self.assertEqual([r["Repo"] for r in rows], ["shop-orders", "acme/shop-storefront"])

    def test_per_service_needs_a_map(self):
        self.assertIn("add the Service map", " ".join(vs.check_layout("Repository layout: one repo per service")))

    def test_one_repo_has_no_map(self):
        text = SERVICE_MAP.replace("one repo per service", "one repo")
        self.assertIn("only for 'Repository layout: one repo per service'", " ".join(vs.check_layout(text)))

    def test_unknown_layout(self):
        self.assertIn("must start with one of", " ".join(vs.check_layout("Repository layout: monorepo")))

    def test_bad_rows(self):
        bad = SERVICE_MAP.replace("| orders | Cart and checkout | carts, orders | shop-orders | Java 21 | no | @ord-po",
                                  "| Orders | Cart and checkout |  | shop orders | Java 21 | maybe | ord-po")
        bad += "| storefront | Again | none | shop-web | Node | no | @a | @b | @c |\n"
        errors = " ".join(vs.check_layout(bad))
        for frag in ("component 'Orders' must be kebab-case", "repo 'shop orders'", "UI for 'Orders' must be yes or no",
                     "Product owner for 'Orders'", "which data it owns", "'storefront' and its repo must appear once"):
            self.assertIn(frag, errors)

    def test_wrong_columns(self):
        text = "Repository layout: one repo per service\n\n| Component | Repo |\n|---|---|\n| orders | shop-orders |\n"
        self.assertIn("columns must be exactly", " ".join(vs.check_layout(text)))

    def test_spec_validation_reports_layout_errors(self):
        example = (SKILLS / "write-spec" / "examples" / "claims-status-self-service.md").read_text(encoding="utf-8")
        text = example.replace("Existing stack, no new technology:", "Repository layout: one repo per service\n\nExisting stack:")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specs").mkdir()
            (root / "intent").mkdir()
            shutil.copy(SKILLS / "write-intent" / "examples" / "claims-status-self-service.md", root / "intent")
            path = root / "specs" / "claims-status-self-service.md"
            path.write_text(text, encoding="utf-8")
            _, errors, _ = vs.validate(path, None, root)
        self.assertIn("add the Service map", " ".join(errors))


if __name__ == "__main__":
    unittest.main()
