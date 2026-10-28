"""Tests for the database support: the spec's Data lines, the build.yaml and
deploy.yaml keys, the release order, the test database in CI, and the hooks
that protect data (destructive commands, merged migrations)."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sdlc"
SKILLS = PLUGIN / "skills"
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vs = load("validate_spec", SKILLS / "write-spec" / "scripts" / "validate_spec.py")
init = load("init_project", SKILLS / "init" / "scripts" / "init_project.py")
dc = load("deploy_config", SKILLS / "release" / "scripts" / "deploy_config.py")
stack = load("stack", ROOT / ".github" / "actions" / "setup-stack" / "stack.py")
hooks = load("code_hooks", PLUGIN / "hooks" / "code_hooks.py")

DATA = """- **Data store:** PostgreSQL 16, managed
- **Migrations:** Flyway, `db/migrations/`
- **Test database:** Testcontainers; locally the `db` service of `compose.yaml`
- **Test data:** factories per test; reference data in `db/seed/`
- **Run locally:** `docker compose up -d --wait db`, then `npm run dev`
"""


def tmpdir(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


class SpecDataTest(unittest.TestCase):
    def test_all_lines_pass(self):
        self.assertEqual(vs.check_data(DATA), [])

    def test_no_data_lines_or_none_pass(self):
        self.assertEqual(vs.check_data("Existing stack, no new technology."), [])
        self.assertEqual(vs.check_data("- **Data store:** none"), [])
        self.assertEqual(vs.check_data("Data store: decision needed (see options)"), [])

    def test_a_data_store_needs_every_line(self):
        errors = vs.check_data("- **Data store:** PostgreSQL 16\n- **Migrations:** Flyway, `db/migrations/`\n")
        self.assertEqual(len(errors), 3)
        for label in ("Test database", "Test data", "Run locally"):
            self.assertTrue(any(label in e for e in errors), label)

    def test_an_empty_data_store_is_an_error(self):
        self.assertTrue(vs.check_data("- **Data store:**\n"))

    def test_the_example_spec_states_its_data(self):
        example = SKILLS / "write-spec" / "examples" / "claims-status-self-service.md"
        _, errors, _ = vs.validate(example, root=str(example.parent))
        self.assertEqual(errors, [])
        self.assertIn("Data store:", example.read_text(encoding="utf-8"))

    def test_template_and_skill_name_the_lines(self):
        for path in (SKILLS / "write-spec" / "templates" / "spec.md", SKILLS / "write-spec" / "SKILL.md"):
            text = path.read_text(encoding="utf-8")
            for label in vs.DATA_LINES:
                self.assertIn(label, text, f"{path.name}: {label}")


class InitDataKeysTest(unittest.TestCase):
    def answers(self, **stack):
        a, errors = init.normalize({"sdlc_ref": "v0.31.0",
                                    "owners": {r: "@x" for r in ("product_owner", "service_owner", "tech_lead")},
                                    "stack": stack})
        self.assertEqual(errors, [])
        return a

    def test_build_yaml_has_the_database_keys(self):
        text = init.render_build(self.answers(services_command="docker compose up -d --wait db",
                                              migrations_path="db/migrations/", dev_command="make dev"))
        self.assertIn("services_command: docker compose up -d --wait db", text)
        self.assertIn("migrations_path: db/migrations/", text)
        self.assertIn("dev_command: make dev", text)

    def test_deploy_yaml_has_migrate_and_seed(self):
        text = init.render_deploy({"deploy": {"migrate_command": "flyway migrate"}})
        self.assertRegex(text, r"(?m)^migrate_command: flyway migrate\s+#")
        self.assertRegex(text, r"(?m)^seed_command:\s+#")
        self.assertRegex(text, r"(?m)^seed_environments: staging\s+#")

    def test_stack_records_the_database_keys(self):
        root = tmpdir(self)
        proposal = {"toolchains": ["node@22"], "test_command": "npm test",
                    "services_command": "docker compose up -d --wait db", "migrations_path": "db/migrations/",
                    "dev_command": "npm run dev:all",
                    "deploy": {"migrate_command": "npm run db:migrate", "seed_command": "npm run db:seed"}}
        self.assertEqual(init.validate_stack(proposal), [])
        init.set_stack(root, proposal)
        build = (root / ".sdlc" / "build.yaml").read_text(encoding="utf-8")
        deploy = (root / ".sdlc" / "deploy.yaml").read_text(encoding="utf-8")
        self.assertRegex(build, r"(?m)^services_command: docker compose up -d --wait db\s+#")
        self.assertRegex(build, r"(?m)^dev_command: npm run dev:all\s+#")
        self.assertRegex(deploy, r"(?m)^migrate_command: npm run db:migrate\s+#")
        cfg = dc.load(root)
        self.assertEqual((cfg["migrate_command"], cfg["seed_command"], cfg["seed_environments"]),
                         ("npm run db:migrate", "npm run db:seed", "staging"))

    def test_bad_values_are_refused(self):
        errors = init.validate_stack({"test_command": "npm test", "migrations_path": "../db",
                                      "deploy": {"seed_environments": "staging qa"}})
        self.assertTrue(any("migrations_path" in e for e in errors))
        self.assertTrue(any("seed_environments" in e for e in errors))


class DeployDataTest(unittest.TestCase):
    def cfg(self, **values):
        cfg = dict(dc.DEFAULTS, **values)
        return cfg, dc.errors(cfg)

    def outputs(self, root):
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": ""}), \
             mock.patch.object(sys, "argv", ["deploy_config.py", "--root", str(root)]), \
             mock.patch("builtins.print") as out:
            self.assertEqual(dc.main(), 0)
        return dict(line.split("=", 1) for line in out.call_args[0][0].splitlines())

    def test_seed_runs_in_staging_only_by_default(self):
        root = tmpdir(self)
        (root / ".sdlc").mkdir()
        (root / ".sdlc" / "deploy.yaml").write_text("migrate_command: m\nseed_command: s\n", encoding="utf-8")
        out = self.outputs(root)
        self.assertEqual((out["seed_staging"], out["seed_production"], out["deploys"]), ("true", "false", "true"))

    def test_seed_in_both_environments(self):
        root = tmpdir(self)
        (root / ".sdlc").mkdir()
        (root / ".sdlc" / "deploy.yaml").write_text(
            "migrate_command: m\nseed_command: s\nseed_environments: staging, production\n", encoding="utf-8")
        out = self.outputs(root)
        self.assertEqual((out["seed_staging"], out["seed_production"]), ("true", "true"))

    def test_seed_needs_migrations_and_known_environments(self):
        _, errors = self.cfg(seed_command="s")
        self.assertTrue(any("migrate_command" in e for e in errors))
        _, errors = self.cfg(migrate_command="m", seed_environments="qa")
        self.assertTrue(any("seed_environments" in e for e in errors))
        self.assertEqual(self.cfg(migrate_command="m", seed_command="s")[1], [])


class ReleaseOrderTest(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "sdlc-release.yml").read_text(encoding="utf-8")

    def job(self, name):
        m = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", self.text)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_migrations_run_before_the_deploy_in_each_environment(self):
        for job, env in (("staging", "staging"), ("production", "production")):
            body = self.job(job)
            migrate = body.index("name: Migrate the")
            seed = body.index("name: Seed")
            deploy = body.index("name: Deploy to")
            self.assertLess(migrate, seed, job)
            self.assertLess(seed, deploy, job)
            self.assertIn(f"needs.detect.outputs.seed_{env} == 'true'", body)
            self.assertGreaterEqual(body.count("DATABASE_URL: ${{ secrets.DATABASE_URL }}"), 3, job)

    def test_production_migrates_after_its_approval(self):
        body = self.job("production")
        self.assertLess(body.index("Apply exactly the approved plan"), body.index("name: Migrate the"))

    def test_database_url_is_an_optional_secret(self):
        self.assertRegex(self.text, r"(?m)^      DATABASE_URL:\n        description: .*\n        required: false")
        for key in ("migrate_command", "seed_command", "seed_staging", "seed_production"):
            self.assertIn(f"{key}: ${{{{ steps.cfg.outputs.{key} }}}}", self.text)


class TestDatabaseInCITest(unittest.TestCase):
    def test_test_workflows_start_the_services(self):
        for name, count in (("sdlc-pr.yml", 2), ("sdlc-main-tests.yml", 1), ("sdlc-build.yml", 1),
                            ("sdlc-fix-findings.yml", 1)):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertEqual(text.count('start-services: "true"'), count, name)
        release = (WORKFLOWS / "sdlc-release.yml").read_text(encoding="utf-8")
        self.assertNotIn("start-services", release)

    def test_setup_stack_runs_services_after_install(self):
        action = (ROOT / ".github" / "actions" / "setup-stack" / "action.yml").read_text(encoding="utf-8")
        self.assertLess(action.index("name: Install command"), action.index("name: Services command"))
        self.assertIn("inputs.start-services == 'true' && steps.stack.outputs.services_command != ''", action)

    def build_yaml(self, root, code=True):
        (root / ".sdlc").mkdir()
        (root / ".sdlc" / "build.yaml").write_text(
            "code_paths: [src/]\ntest_command: npm test\nservices_command: docker compose up -d --wait db\n",
            encoding="utf-8")
        if code:
            (root / "src").mkdir()

    def run_stack(self, root, *args):
        res = subprocess.run([sys.executable, str(ROOT / ".github" / "actions" / "setup-stack" / "stack.py"),
                              "--root", str(root), *args], capture_output=True, text=True,
                             env={k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"})
        self.assertEqual(res.returncode, 0, res.stderr)
        return dict(line.split("=", 1) for line in res.stdout.splitlines())

    def test_stack_outputs_the_services_command(self):
        root = tmpdir(self)
        self.build_yaml(root)
        self.assertEqual(self.run_stack(root)["services_command"], "docker compose up -d --wait db")

    def test_no_services_before_the_first_story_has_code(self):
        root = tmpdir(self)
        self.build_yaml(root, code=False)
        self.assertEqual(self.run_stack(root, "--install-if-code")["services_command"], "")


class DevCheckTest(unittest.TestCase):
    """dev_check.py: the app starts the way a developer starts it."""

    def setUp(self):
        self.root = tmpdir(self)
        self.dev = load("dev_check", ROOT / ".github" / "actions" / "setup-stack" / "dev_check.py")

    def free_url(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return f"http://127.0.0.1:{s.getsockname()[1]}/healthz"

    def test_passes_once_the_url_answers(self):
        import http.server
        import threading
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/healthz"   # a 404 still means the app is up
        ok, message, _ = self.dev.check("sleep 30", url, self.root, timeout=20, poll=0.2)
        self.assertTrue(ok, message)

    def test_fails_when_the_command_exits_first(self):
        ok, message, tail = self.dev.check("echo missing DATABASE_URL; exit 3", self.free_url(), self.root,
                                           timeout=20, poll=0.2)
        self.assertFalse(ok)
        self.assertIn("exited with 3", message)
        self.assertIn("missing DATABASE_URL", tail)

    def test_fails_when_the_url_never_answers(self):
        ok, message, _ = self.dev.check("sleep 30", self.free_url(), self.root, timeout=2, poll=0.2)
        self.assertFalse(ok)
        self.assertIn("did not answer within 2s", message)

    def test_a_fresh_clone_gets_env_from_the_example(self):
        (self.root / ".env.example").write_text("DATABASE_URL=postgres://shop:shop@localhost/shop\n",
                                                encoding="utf-8")
        self.dev.check("exit 1", self.free_url(), self.root, timeout=5, poll=0.2)
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"),
                         (self.root / ".env.example").read_text(encoding="utf-8"))

    def test_workflows_run_it_after_the_tests(self):
        for name in ("sdlc-pr.yml", "sdlc-main-tests.yml"):
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            tests = text.index("name: Run the project's tests (test_command)")
            check = text.index("name: Check the app starts locally (dev_command)")
            self.assertLess(tests, check, name)
            self.assertIn("steps.stack.outputs.dev_check_url != ''", text)

    def test_init_requires_a_local_url_and_a_command(self):
        errors = init.validate_stack({"test_command": "npm test", "dev_check_url": "https://shop.example.com/"})
        self.assertTrue(any("local URL" in e for e in errors))
        self.assertTrue(any("needs a dev_command" in e for e in errors))
        self.assertEqual(init.validate_stack({"test_command": "npm test", "dev_command": "make dev",
                                              "dev_check_url": "http://localhost:3000/healthz"}), [])


class DestructiveDatabaseCommandTest(unittest.TestCase):
    def setUp(self):
        self.project = tmpdir(self)
        clean = {k: v for k, v in os.environ.items() if not hooks.DB_ENV_RE.match(k)}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def blocked(self, command):
        return bool(hooks.destructive_db(command, self.project))

    def test_remote_databases_are_protected(self):
        for c in ['psql -h prod-db.example.com -c "DROP DATABASE shop"',
                  'psql "postgresql://u:p@shop.postgres.database.azure.com/shop" -c "TRUNCATE orders"',
                  'flyway -url=jdbc:postgresql://db.prod.example.com:5432/shop clean',
                  'redis-cli -h cache.prod.example.com FLUSHALL',
                  'sqlcmd -S tcp:shop.database.windows.net -Q "DROP TABLE orders"']:
            self.assertTrue(self.blocked(c), c)

    def test_local_databases_and_containers_pass(self):
        for c in ['psql postgresql://shop:shop@localhost:5432/shop -c "DROP TABLE orders"',
                  'DATABASE_URL=postgres://shop:shop@127.0.0.1/shop npx prisma migrate reset --force',
                  'docker compose exec db psql -U shop -c "DROP TABLE orders"',
                  'flyway -url=jdbc:postgresql://db:5432/shop clean',
                  'psql -c "truncate orders"', 'redis-cli FLUSHALL']:
            self.assertFalse(self.blocked(c), c)

    def test_text_that_only_mentions_sql_passes(self):
        for c in ['grep -rn "drop table" src/', 'git commit -m "Drop table users from the report"', 'npm test']:
            self.assertFalse(self.blocked(c), c)

    def test_a_reset_with_an_unknown_target_is_blocked(self):
        self.assertTrue(self.blocked("npx prisma migrate reset --force"))

    def test_the_target_comes_from_the_environment_and_dotenv(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql://a:b@prod.example.com/shop"}):
            self.assertTrue(self.blocked("npx prisma migrate reset --force"))
            self.assertTrue(self.blocked('psql -c "drop table a"'))
        (self.project / ".env").write_text("DATABASE_URL=postgresql://shop:shop@localhost:5432/shop\n",
                                           encoding="utf-8")
        self.assertFalse(self.blocked("npx prisma migrate reset --force"))
        (self.project / ".env").write_text("export DB_HOST=shop.mysql.database.azure.com\n", encoding="utf-8")
        self.assertTrue(self.blocked("rails db:drop"))

    def test_the_hook_blocks_with_exit_2(self):
        (self.project / ".sdlc").mkdir()
        event = {"tool_name": "Bash", "tool_input": {"command": 'psql -h prod.example.com -c "DROP TABLE x"'}}
        res = subprocess.run([sys.executable, str(PLUGIN / "hooks" / "code_hooks.py"), "pre-bash"],
                             input=json.dumps(event), capture_output=True, text=True,
                             env=dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project)))
        self.assertEqual(res.returncode, 2)
        self.assertIn("not a local database", res.stderr)


class MergedMigrationTest(unittest.TestCase):
    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.project, check=True, capture_output=True)

    def setUp(self):
        self.project = tmpdir(self)
        (self.project / ".sdlc").mkdir()
        (self.project / ".sdlc" / "build.yaml").write_text("migrations_path: db/migrations/\n", encoding="utf-8")
        (self.project / "db" / "migrations").mkdir(parents=True)
        (self.project / "db" / "migrations" / "V1__init.sql").write_text("create table a (id int);\n",
                                                                          encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
        self.git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init")
        self.git("checkout", "-q", "-b", "story/shop-s2")

    def pre_write(self, rel):
        event = {"tool_name": "Edit", "tool_input": {"file_path": str(self.project / rel), "new_string": "x"}}
        return hooks.pre_write(event, self.project)

    def test_a_merged_migration_cannot_be_edited(self):
        code, problems = self.pre_write("db/migrations/V1__init.sql")
        self.assertEqual(code, 2)
        self.assertIn("Add a new migration", problems[0])

    def test_a_new_migration_and_other_files_pass(self):
        self.assertEqual(self.pre_write("db/migrations/V2__orders.sql"), (0, []))
        self.assertEqual(self.pre_write("src/app.py"), (0, []))

    def test_without_migrations_path_nothing_is_checked(self):
        (self.project / ".sdlc" / "build.yaml").write_text("code_paths: [src/]\n", encoding="utf-8")
        self.assertEqual(self.pre_write("db/migrations/V1__init.sql"), (0, []))


class GuidanceTest(unittest.TestCase):
    def test_build_and_review_carry_the_data_rules(self):
        patterns = (SKILLS / "build-story" / "reference" / "patterns.md").read_text(encoding="utf-8")
        self.assertIn("## 3b. Databases", patterns)
        self.assertIn("services_command", (SKILLS / "build-story" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("**Data**", (SKILLS / "review-story" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("**Data**", (PLUGIN / "agents" / "verifier.md").read_text(encoding="utf-8"))

    def test_the_stack_pr_lists_the_database_keys(self):
        text = (WORKFLOWS / "sdlc-spec-to-stack.yml").read_text(encoding="utf-8")
        for key in ("services_command", "migrations_path", "dev_command"):
            self.assertIn(f'"{key}"', text)


if __name__ == "__main__":
    unittest.main()
