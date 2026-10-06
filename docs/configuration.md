# Configuration reference

Everything a project configures lives in `.sdlc/`. `/sdlc:init` writes these
files; `sdlc.json` is regenerated from, the rest are the project's to edit
(through PRs) after they are created.

## `.sdlc/sdlc.json` (regenerated source)

| Key | Meaning |
|---|---|
| `sdlc_repo` | The marketplace repo, e.g. `chimera-technologies/sdlc-marketplace` |
| `sdlc_ref` | The plugin release tag every caller and the settings pin, e.g. `v0.6.0` |
| `base_branch` | The protected branch artifacts merge into (default `main`) |
| `maintain_cron` | Schedule of the Maintain checks (default hourly `17 * * * *`) |
| `stages` | `plan`, `design`, `ui_design`, `build`, `pr_review`, `test`, `deploy`, `maintain`: `true`/`false` |
| `models` | `intake`, `spec`, `review`, `build`: the Claude model per headless stage |
| `workflows` | `auto` (default): big jobs run as Claude Code workflows (parallel agents, then skeptics) above the thresholds in `plugins/sdlc/reference/workflows.md`: large requirement documents (`write-intent`), large or high-risk specs (`review-spec`), large story PRs (`review-story`); `always`; `off` (one session) |
| `auto_build` | `true` (default): each story gets a plan PR and is built in CI when it merges (`sdlc-build.yml`); `false`: build by hand with `/sdlc:build-story` |
| `staging_on_merge` | `true` (default): with Deploy on, every merge to the base branch whose tests pass is deployed to staging and smoke-tested (trunk-based; no tag, never production); `false`: staging only with a release ([trunk-based.md](trunk-based.md)) |

Change it and re-run `/sdlc:init` (or `init_project.py --answers`), or move
the tag with `init_project.py --upgrade vX.Y.Z`.

## `.sdlc/owners.yaml`

```yaml
default:
  product_owner: "@po"          # product-facing intents, specs, designs
  service_owner: "@org/sre"     # operational intents; release manager by default
  tech_lead: "@lead"            # high-risk design approval; stack decision
  security_owner: "@lead"       # security policy exceptions
components:
  web:
    product_owner: "@web-po"
    service_owner: "@org/web-sre"
    tech_lead: "@web-lead"
    jira_components: ["Web"]
```

Values must be quoted `"@user"` or `"@org/team"`; validators reject owners
not listed here.

## `.sdlc/jira.yaml`

`enabled: false`, or `enabled: true` with `site` (`<name>.atlassian.net`),
`space_key`, `epic_issue_type` (Epic), `story_issue_type` (Story) and
`created_label` (`intent-created`: never `intent`, which starts the intake).

## `.sdlc/build.yaml` (Build and Test)

| Key | Example | Meaning |
|---|---|---|
| `code_paths` | `[src/, tests/]` | Writes here need the Build preflight, a story branch and a plan (build guard) |
| `test_paths` | `[tests/]`, `[src/test/]` | Where tests live (plan traceability) |
| `toolchains` | `[node@22]`, `[python@3.12]`, `[java@21]`, `[dotnet@8.0]`, `[go@1.23]` | Installed in CI by `setup-stack` |
| `setup_command` | `curl ... \| sh` | Anything else to install (Rust, Ruby, system packages) |
| `install_command` | `npm ci`, `pip install -r requirements.txt` | Dependencies |
| `test_command` | `npx playwright test`, `pytest -q`, `mvn -B test` | The full suite (required for Test) |
| `test_file_command` | `pytest -q {file}` | One test file while building (`{file}`) |
| `report_path` | `playwright-report/` | Uploaded as an artifact after tests |
| `check_command` | `npx tsc --noEmit && npx eslint .`, `ruff check . && mypy .` | Whole-project static checks: run in Build before the suite, by the verifier, and in CI before `test_command` |
| `lint_command` | `npx eslint {file}`, `ruff check {file}` | One file (`{file}`), run by the code hooks after every code write; errors go back to Claude |
| `format_command` | `npx prettier --write {file}`, `ruff format {file}` | One file (`{file}`), run by the code hooks after every code write; never blocks |
| `ui_library` | `shadcn/ui`, `Angular Material`, `MudBlazor` | The UI component library the spec chose; the build uses it for every standard element |
| `graphify_version`, `ponytail_ref` | `0.9.71`, `v4.10.0` | Pins for the Build preflight's token-saving tools |

The stack is the tech lead's decision in the spec; record it with
`/sdlc:init stack=specs/<slug>.md`. Commands must not contain `#`, and the
hooks run `lint_command` and `format_command` in bash, as CI does. A linter
that is not installed yet (before the scaffold story adds it) is skipped,
not reported as a failure.
Test names use `S<n> AC-<k>` in the language's style (`"S1 AC-2: ..."`,
`test_s1_ac_2_...`, `S1Ac2...`).

## `PATTERNS.md` (coding patterns)

Created once by `/sdlc:init`, then owned by the project: the codebase's
reusable patterns (structure, errors and validation, data access, UI
components, state and configuration, testing). `build-story` reads it
before planning, reuses what it names, and adds each new reusable piece in
the same PR; the verifier and the PR review check changes against it. The
generic catalogue it starts from is
`plugins/sdlc/skills/build-story/reference/patterns.md`.

## Code hooks

The plugin's hooks run in every repo with `.sdlc/`, interactive and in CI:

| When | What |
|---|---|
| Before a write | Blocks text that looks like a real secret, hand edits of lock files, and writes into dependency folders |
| Before a command | Blocks `terraform apply`/`destroy`, `kubectl apply`/`delete`, `helm install`/`upgrade`, force pushes, pushes to the base branch and `--no-verify`; updates a stale Graphify graph before `graphify query`, `explain` or `path` |
| After a code write | Runs `format_command`, then `lint_command`, on the file; lint errors go back to Claude. Marks the graph stale |
| End of each turn | Updates the graph if code changed (interactive sessions) |

So the Graphify graph always matches the code just written, without
re-running the preflight.

## `.sdlc/review.json` (PR review)

```json
{
  "gate": {"skill": "sdlc:review-story", "model": "claude-sonnet-5", "fail_on": "high"},
  "advisory": [
    {"name": "code-review", "marketplace": "https://github.com/anthropics/claude-code.git",
     "plugin": "code-review@claude-code-plugins",
     "prompt": "/code-review:code-review --comment {repo}/pull/{pr}",
     "allowed_tools": "mcp__github_inline_comment__create_inline_comment"},
    {"name": "my-check", "prompt": "/my-check {pr}"}
  ]
}
```

`fail_on` is `high`, `medium` or `low`. Advisory reviewers are any plugin
skill (marketplace + plugin + prompt) or a skill in the repo's
`.claude/skills/` (prompt only); they comment and never block. What the gate
flags is tuned in `REVIEW.md`.

## `.sdlc/deploy.yaml` (Deploy)

| Key | Default | Meaning |
|---|---|---|
| `version_scheme` | `semver` | Tags `vMAJOR.MINOR.PATCH` |
| `cloud` | `none` | `aws`, `azure` or `gcp`: the architect's choice in the spec; OIDC login per environment |
| `iac`, `iac_dir`, `iac_var_file`, `iac_backend_config` | `none`, `infra`, empty, empty | `terraform`: plan and apply per environment (`{env}` in the file paths); destroy or replace stops the release unless re-run with `allow_destroy` |
| `smoke_command` | empty | Run after each deploy with `SMOKE_URL`; a failure stops the release |
| `production_plan_environment` | `production-plan` | Reviewer-free environment with a read-only identity, for the production plan the approvers see |
| `deploy_command` | empty | Run per environment with `SDLC_ENV`, `SDLC_VERSION`, `SDLC_COMMIT`, `DEPLOY_TOKEN` (secret) and `DEPLOY_TARGET` (variable); empty = tag and GitHub release only |
| `staging_environment` | `staging` | Deployed automatically; empty = no staging |
| `production_environment` | `production` | Give it required reviewers (the release manager) |

## `.sdlc/maintain.json` (Maintain)

```json
{"checks": [
  {"name": "api-p95-latency", "source": "maintain", "fingerprint": "api-p95-latency",
   "command": "python scripts/checks/latency.py --band 800", "timeout": 120}
]}
```

A check exits 0 when healthy, or exits 1 and prints one JSON object (the
signal) on a breach. `source` is `maintain`, `claude-security` or
`claude-tag`; `fingerprint` (a-z, 0-9, -) deduplicates intents. Test a
check without sending anything: `python <plugin>/skills/triage/scripts/run_checks.py`.

## Repo variables and secrets

| Name | Kind | Needed for |
|---|---|---|
| `SDLC_APP_ID` | variable | every workflow (the sdlc-bot GitHub App) |
| `SDLC_APP_PRIVATE_KEY` | secret | every workflow |
| `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` | secret | intake, spec, PR review |
| `JIRA_BASE_URL`, `JIRA_USER_EMAIL` | variables | Jira (if enabled) |
| `JIRA_API_TOKEN` | secret | Jira (if enabled) |
| `DEPLOY_TOKEN` / `DEPLOY_TARGET` | secret / variable, per environment | `deploy_command` |
| `AWS_ROLE_ARN`, `AWS_REGION` / `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` / `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT` | variables on each environment (`staging`, `production-plan` with a read-only identity, `production`) | OIDC cloud login in releases, for the `cloud` in `.sdlc/deploy.yaml` |
| `SMOKE_URL` | variable, per environment | `smoke_command` |
| `FIGMA_TOKEN` | environment variable on the designer's machine | PNG export after refining the mockups in Figma (not needed for the automatic mockups) |
