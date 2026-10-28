#!/usr/bin/env python3
"""Code hooks: checks before and after Claude writes code or runs a command.

One script, one mode per hook event (hooks.json wires them up):

  pre-write   PreToolUse Write|Edit|MultiEdit|NotebookEdit. Blocks (exit 2):
              - text that looks like a real secret (cloud keys, tokens,
                private keys): secrets come from the environment or a secret
                store, never from the repo;
              - hand edits of lock files (the package manager writes them);
              - writes into dependency folders (node_modules/, .venv/, ...);
              - edits of a migration file already on the base branch
                (under build.yaml's migrations_path): add a new migration.
  pre-bash    PreToolUse Bash. Blocks commands that change real environments
              or bypass review (terraform apply, kubectl apply, helm upgrade,
              git push --force or to the base branch, --no-verify, rm -rf /),
              and commands that drop or wipe a database (DROP, TRUNCATE,
              flyway clean, prisma migrate reset, ...) unless it is local:
              localhost, a container, or a host with no dot in its name.
              Before a `graphify query|explain|path`, updates a stale graph so
              the answer matches the code just written.
  post-write  PostToolUse Write|Edit|MultiEdit, for files under code_paths:
              runs format_command, then lint_command, on the file (both from
              .sdlc/build.yaml, {file} = the file). Lint errors go back to
              Claude (exit 2). Marks the Graphify graph stale.
  stop        Stop. Updates the graph if code changed this turn (not in
              headless CI runs, which end with the session).

Active only in a repo that has opted in (`.sdlc/`); everything else passes.
A missing tool never blocks: only a failed lint does. Standard library only.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_guard", HERE / "build_guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

_PREFLIGHT = HERE.parent / "skills" / "build-story" / "scripts" / "build_preflight.py"

# High-confidence secret formats only: a false block costs more trust than it saves.
SECRET_PATTERNS = [
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("a Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("a Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    ("an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("an Azure storage key", re.compile(r"AccountKey=[A-Za-z0-9+/]{60,}={0,2}")),
]
# Documentation placeholders are allowed (AKIAIOSFODNN7EXAMPLE).
PLACEHOLDER_RE = re.compile(r"(?i)example|dummy|placeholder|x{8,}|0{8,}")
LOCK_FILES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "poetry.lock",
    "Pipfile.lock", "uv.lock", "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "packages.lock.json",
    "gradle.lockfile", "pubspec.lock", "Podfile.lock", "mix.lock",
}
DEPENDENCY_DIRS = {"node_modules", ".venv", "venv", "site-packages", "__pycache__", ".terraform"}
DANGEROUS_COMMANDS = [
    (re.compile(r"\bterraform\s+(?:-chdir=\S+\s+)?(?:apply|destroy|import|taint|state\s+(?:rm|mv|push))(?=\s|$)"),
     "changes real infrastructure: only the release applies the approved plan. Use terraform validate or plan."),
    (re.compile(r"\bkubectl\s+(?:\S+\s+)*?(?:apply|create|delete|replace|patch|scale|edit|drain|rollout\s+(?:restart|undo))(?=\s|$)"),
     "changes a real cluster: deploys run only in the release. Use kubeconform or a local cluster (kind)."),
    (re.compile(r"\bhelm\s+(?:install|upgrade|uninstall|delete|rollback)(?=\s|$)"),
     "changes a real cluster: deploys run only in the release. Use helm template or helm lint."),
    (re.compile(r"\bgit\s+push\b[^;&|\n]*\s(?:--force(?!-with-lease)\b|-f\b|--mirror\b|--delete\b|:\S)"),
     "rewrites or deletes published history. Push a new commit instead."),
    (re.compile(r"\bgit\s+(?:commit|push|merge|rebase)\b[^;&|\n]*\s--no-verify\b|\bgit\s+commit\b[^;&|\n]*\s-[a-zA-Z]*n[a-zA-Z]*(?=\s|$)"),
     "skips the repo's hooks. Fix what the hook reports instead."),
    (re.compile(r"\brm\s+-[a-zA-Z]*(?:r[a-zA-Z]*f|f[a-zA-Z]*r)[a-zA-Z]*\s+(?:/|~|\$HOME|\*)(?:\s|$)"),
     "deletes far more than the project."),
]
# Statements that drop or wipe data, when a database client runs them (not `grep "drop table"`).
DESTRUCTIVE_SQL_RE = re.compile(r"(?i)\bdrop\s+(?:database|schema|table)\b|\btruncate\s+(?:table\s+)?[\w\"`.]+"
                                r"|\bdropDatabase\s*\(|\bflush(?:all|db)\b")
DB_CLIENT_RE = re.compile(r"(?i)\b(?:psql|mysql|mariadb|sqlcmd|sqlplus|mongosh|mongo|redis-cli|cqlsh"
                          r"|clickhouse(?:-client)?|cockroach\s+sql|prisma\s+db\s+execute)\b")
# Migration and framework commands that drop or wipe data.
DESTRUCTIVE_DB_RE = re.compile(
    r"(?i)\bdropdb\b"
    r"|\bflyway\b[^;&|\n]*\bclean\b|\bliquibase\b[^;&|\n]*\bdrop-?all\b"
    r"|\bprisma\s+(?:migrate\s+reset|db\s+push\b[^;&|\n]*--force-reset)"
    r"|\b(?:rails|rake)\s+db:(?:drop|reset|purge|schema:load)\b|\bartisan\s+(?:migrate:(?:fresh|reset)|db:wipe)\b"
    r"|\bmanage\.py\s+flush\b|\balembic\s+downgrade\s+base\b|\bef\s+database\s+drop\b"
    r"|\bsequelize\b[^;&|\n]*\bdb:drop\b|\btypeorm\b[^;&|\n]*\bschema:drop\b"
    r"|\bknex\s+migrate:rollback\b[^;&|\n]*--all")
# A database host written in a command or setting: a URL's host, a -h/--host option, or Server=/Host=.
DB_HOST_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://(?:[^@/\s'\"]*@)?(\[[^\]]+\]|[^:/?\s'\";,]+)"
                        r"|(?:^|\s)(?:-h|--host)[=\s]+['\"]?([^\s'\";]+)"
                        r"|\b(?:Server|Host|Data Source)\s*=\s*(?:tcp:)?([^;,'\"\s]+)"
                        r"|\bsqlcmd\b[^;&|\n]*?\s-S\s*['\"]?(?:tcp:)?([^\s,;'\"]+)")
# Settings that usually hold the connection (the process environment and .env).
DB_ENV_RE = re.compile(r"(?i)^(?:DATABASE_URL|DB_URL|DB_HOST|PGHOST|MYSQL_HOST|MONGODB_URI|MONGO_URL|REDIS_URL"
                       r"|SPRING_DATASOURCE_URL|\w*CONNECTION_?STRING\w*)$")
IN_CONTAINER_RE = re.compile(r"\b(?:docker|podman)\s+(?:compose\s+)?(?:exec|run)\b|\bdocker-compose\s+(?:exec|run)\b")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
GRAPH_QUERY_RE = re.compile(r"\bgraphify\s+(?:query|explain|path)\b")
# The linter is not installed yet (before the scaffold story adds it): not a lint failure.
TOOL_MISSING_RE = re.compile(r"(?i)command not found|is not recognized as|missing script|could not determine executable"
                             r"|npm (?:ERR!|error) canceled|no module named|cannot find module|ENOENT")


def project_dir(event):
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()).resolve()


def opted_in(project):
    return (project / ".sdlc").is_dir()


def relative(project, file_path):
    """The file's path relative to the project (posix), or None if it is outside."""
    path = Path(file_path)
    if not path.is_absolute():
        path = project / path
    try:
        return path.resolve().relative_to(project).as_posix()
    except ValueError:
        return None


def under(rel, prefixes):
    return any(rel == p.strip("/") or rel.startswith(p.strip("/") + "/") for p in prefixes)


def new_text(tool_input):
    """Everything the tool call would write."""
    parts = [tool_input.get(k) or "" for k in ("content", "new_string", "new_source")]
    parts += [e.get("new_string") or "" for e in tool_input.get("edits") or [] if isinstance(e, dict)]
    return "\n".join(parts)


def find_secrets(text):
    found = []
    for what, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            if not PLACEHOLDER_RE.search(m.group(0)):
                found.append(what)
                break
    return found


def base_branch(project):
    try:
        return json.loads((project / ".sdlc" / "sdlc.json").read_text(encoding="utf-8")).get("base_branch") or "main"
    except (OSError, ValueError):
        return "main"


def dangerous(command, base="main"):
    """Why the command is blocked, or None."""
    for pattern, why in DANGEROUS_COMMANDS:
        if pattern.search(command):
            return why
    push = re.search(r"\bgit\s+push\b([^;&|\n]*)", command)
    if push and re.search(rf"(?:^|\s|:){re.escape(base)}(?:\s|$)", push.group(1)):
        return f"pushes straight to {base}: every change reaches {base} through a reviewed PR."
    return None


def is_local(host):
    """Local: this machine, a container, or a name with no dot (a compose service such as `db`)."""
    host = host.lower().strip("[]")
    return host in LOCAL_HOSTS or host.endswith(".localhost") or "." not in host


def hosts_in(text):
    return [h for m in DB_HOST_RE.finditer(text) for h in m.groups() if h]


def env_hosts(project):
    """Database hosts in the environment and the project's .env (only the hosts are kept)."""
    values = [v for k, v in os.environ.items() if DB_ENV_RE.match(k)]
    try:
        for raw in (project / ".env").read_text(encoding="utf-8").splitlines():
            key, sep, val = raw.strip().partition("=")
            key = key[len("export "):] if key.startswith("export ") else key
            if sep and DB_ENV_RE.match(key.strip()):
                values.append(val.strip().strip("'\""))
    except OSError:
        pass
    hosts = []
    for v in values:
        # A bare host (DB_HOST=db) has no URL or Server= around it.
        hosts += hosts_in(v) or ([v] if v and not re.search(r"[=/:;@\s]", v) else [])
    return hosts


def destructive_db(command, project):
    """Why a command that drops or wipes data is blocked, or None (local targets pass)."""
    wipes = DESTRUCTIVE_DB_RE.search(command) or (DB_CLIENT_RE.search(command) and DESTRUCTIVE_SQL_RE.search(command))
    if not wipes or IN_CONTAINER_RE.search(command):
        return None
    hosts = hosts_in(command) or env_hosts(project)
    remote = [h for h in hosts if not is_local(h)]
    # With no host anywhere, a client connects to this machine; a migration tool reads its own config.
    if (hosts and not remote) or (not hosts and not DESTRUCTIVE_DB_RE.search(command)):
        return None
    where = f"{remote[0]}, which is not a local database" if remote else "a database not shown to be local"
    return (f"drops or wipes data on {where}. Run it only against localhost or a container (put the local "
            "DATABASE_URL in the command or in .env); change a real database with a new migration, which the "
            "release runs (migrate_command).")


def merged_migration(project, rel):
    """True if rel is under build.yaml's migrations_path and already on the base branch."""
    cfg = guard.load_build_config(project) or {}
    if not cfg.get("migrations_path") or not under(rel, [cfg["migrations_path"]]):
        return False
    base = base_branch(project)
    for ref in (f"origin/{base}", base):
        try:
            res = subprocess.run(["git", "cat-file", "-e", f"{ref}:{rel}"], cwd=project,
                                 capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if res.returncode == 0:
            return True
    return False


def load_preflight():
    spec = importlib.util.spec_from_file_location("build_preflight", _PREFLIGHT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def refresh_graph(project):
    """Update a stale graph. Returns a report line or None; never raises."""
    try:
        return load_preflight().refresh_if_stale(project)
    except SystemExit as e:
        return f"graphify: update failed, graph left stale ({str(e)[:300]})"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"graphify: update failed, graph left stale ({e})"


def mark_stale(project, rel):
    out = project / "graphify-out"
    graph_ready = (out / "graph.json").is_file() or guard.no_code_marker(project).is_file()
    if not graph_ready:
        return  # no preflight yet: the build guard handles that
    stale = out / "STALE"
    seen = set(stale.read_text(encoding="utf-8").splitlines()) if stale.is_file() else set()
    if rel not in seen:
        with open(stale, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(rel + "\n")


def run_command(template, rel, project, timeout=90):
    """Run a build.yaml command with {file} filled in, in bash as CI does.

    Returns (exit code, output), or None if it could not run (no bash, a
    timeout, or the tool is not installed: exit 126 or 127).
    """
    command = template.replace("{file}", f'"{rel}"')
    try:
        res = subprocess.run(["bash", "-c", command], cwd=project, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode in (126, 127) or (res.returncode != 0 and TOOL_MISSING_RE.search(res.stdout + res.stderr)):
        print(f"SDLC code hooks: could not run `{command}`: {(res.stdout + res.stderr).strip()[:200]}", file=sys.stderr)
        return None
    return res.returncode, (res.stdout + res.stderr).strip()


# ------------------------------------------------------------------ modes

def pre_write(event, project):
    rel = relative(project, (event.get("tool_input") or {}).get("file_path")
                   or (event.get("tool_input") or {}).get("notebook_path") or "")
    if rel is None:
        return 0, []
    problems = []
    name = rel.rsplit("/", 1)[-1]
    if name in LOCK_FILES:
        problems.append(f"{rel} is a lock file: change dependencies with the package manager "
                        "(for example npm install <pkg>, pip install, go get), which rewrites it.")
    if DEPENDENCY_DIRS & set(rel.split("/")[:-1]):
        problems.append(f"{rel} is inside a dependency or generated folder: change the project's own code, "
                        "or the dependency's version.")
    if merged_migration(project, rel):
        problems.append(f"{rel} is a migration already on {base_branch(project)}: databases have run it, so "
                        "changing it leaves them out of step with the code. Add a new migration instead.")
    for what in find_secrets(new_text(event.get("tool_input") or {})):
        problems.append(f"the text written to {rel} contains what looks like {what}. Read secrets from the "
                        "environment or the secret store, and use an obvious placeholder in examples and tests.")
    return (2 if problems else 0), problems


def pre_bash(event, project):
    command = (event.get("tool_input") or {}).get("command") or ""
    why = dangerous(command, base_branch(project)) or destructive_db(command, project)
    if why:
        return 2, [f"`{command.strip()[:200]}` {why}"]
    if GRAPH_QUERY_RE.search(command):
        note = refresh_graph(project)
        if note:
            print(note, file=sys.stderr)
    return 0, []


def post_write(event, project):
    rel = relative(project, (event.get("tool_input") or {}).get("file_path") or "")
    cfg = guard.load_build_config(project)
    if rel is None or cfg is None or not under(rel, cfg["code_paths"]) or not (project / rel).is_file():
        return 0, []
    mark_stale(project, rel)
    if cfg.get("format_command"):
        run_command(cfg["format_command"], rel, project)   # fixes what it can; never blocks
    if cfg.get("lint_command"):
        res = run_command(cfg["lint_command"], rel, project)
        if res and res[0] != 0:
            lines = res[1].splitlines()
            return 2, [f"lint_command found problems in {rel}. Fix them (the first 40 lines):",
                       *lines[:40], *(["..."] if len(lines) > 40 else [])]
    return 0, []


def stop(event, project):
    if os.environ.get("SDLC_HEADLESS") == "1" or guard.load_build_config(project) is None:
        return 0, []
    note = refresh_graph(project)
    if note:
        print(note, file=sys.stderr)
    return 0, []


MODES = {"pre-write": pre_write, "pre-bash": pre_bash, "post-write": post_write, "stop": stop}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in MODES:
        print(f"usage: code_hooks.py {{{'|'.join(MODES)}}}", file=sys.stderr)
        return 0
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    project = project_dir(event)
    if not opted_in(project):
        return 0
    code, problems = MODES[argv[0]](event, project)
    if problems:
        label = "Blocked by the SDLC code hooks" if argv[0].startswith("pre") else "SDLC code hooks"
        print(f"{label}:", file=sys.stderr)
        for i, p in enumerate(problems):
            # post-write: one finding, then the linter's own lines as they are
            print(p if argv[0] == "post-write" and i else f"- {p}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
