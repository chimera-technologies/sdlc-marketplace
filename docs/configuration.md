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
| `autofix_attempts` | `2` (default): when a story PR's tests or traceability fail, the bot goes back to Build on the same branch and pushes a fix to the PR, at most this many times; `0` turns it off |
| `budgets` | AI spend limits for the CI runs (see [AI spend limits](#ai-spend-limits)): `per_run_usd` (a cap per stage) and `monthly_usd` (0 = none) |

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
| `check_command` | `npx tsc --noEmit && npx eslint .`, `npx eslint {files}`, `ruff check {files}` | Static checks: run in Build before the suite, by the verifier, and in CI before `test_command`. With `{files}`, only the code files the change touched are checked (an existing codebase's old problems do not block new work) |
| `lint_command` | `npx eslint {file}`, `ruff check {file}` | One file (`{file}`), run by the code hooks after every code write; errors go back to Claude |
| `format_command` | `npx prettier --write {file}`, `ruff format {file}` | One file (`{file}`), run by the code hooks after every code write; never blocks |
| `ui_library` | `shadcn/ui`, `Angular Material`, `MudBlazor` | The UI component library the spec chose; the build uses it for every standard element |
| `results_path` | `.sdlc-results/*.xml` | Glob of the JUnit XML files `test_command` writes (one per runner, in a folder no runner cleans): per-test results for Xray |
| `evidence_path` | `test-results/` | Folder of the screenshots the browser tests save (Playwright `screenshot: 'on'`); attached to each test's result in Xray |
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

## AI spend limits

Every headless Claude step in the workflows is wrapped by the `ai-budget`
action (`.github/actions/ai-budget/`):

- **Per run (hard):** `--max-budget-usd` from `budgets.per_run_usd.<stage>`
  stops a run that costs more. A stopped build opens a draft PR, a stopped
  review fails the gate. Defaults are about 5-10 times a normal run
  (`build` 30, `review` 10, `spec` 10, ...); 0 turns a cap off.
- **Per month (soft):** each run's cost is added to a monthly issue labelled
  `sdlc-spend` (total and by stage). With `budgets.monthly_usd` set, AI
  steps stop once it is reached (the bot comments; at 80% it warns first).
  Two runs finishing at once can lose one update, so the limit is soft.
- **Hard ceiling:** the monthly spend limit of the Anthropic Console
  workspace the `ANTHROPIC_API_KEY` belongs to. Give each project or team
  its own workspace and key.

With a subscription token the figures are what the runs would cost at API
prices, not money billed.

```json
"budgets": {"per_run_usd": {"build": 20, "review": 8}, "monthly_usd": 300}
```

## Reviewing intent, spec and plan PRs

- **Edit the PR directly**: every later stage reads the merged file, so
  edits count. The validators run again on every push.
- **The pre-screen runs again** after new commits on a spec or plan PR
  (`sdlc-prescreen.yml`), on the PR as it is now, as one comment updated
  in place.
- **`/sdlc revise <request>`** as a PR comment (owners, members and
  collaborators only) has Claude make the change on the PR's branch, then
  reply with what changed (`sdlc-revise.yml`). On a spec PR the mockups are
  revised too when the stories or screens change; `/sdlc revise design:
  <request>` changes only the mockups. Nothing is pushed unless the
  validators pass, and merging is still the reviewer's decision.

## When a story PR's tests fail

The `autofix` job in `sdlc-pr.yml` sends the story back to Build on the
same branch:

1. It runs the failing checks again (traceability, the static checks, the
   test suite) and keeps their output. If they pass this time, the failure
   was flaky: it says so on the PR and changes nothing.
2. `build-story mode=fix-tests` reads that output, fixes the code (or
   writes a missing planned test), runs the checks and the verifier, and
   writes a report. It never deletes, skips or weakens a test to make it
   pass; it changes a test only when the test contradicts the plan or
   depends on timing, and says why.
3. The fix is pushed to the same PR as an `autofix:` commit, with the
   report as a comment. The review gate and the tests run again on it.

After `autofix_attempts` (2) failed rounds it stops and asks a person on
the PR. SDLC files are never changed, and the run has its own AI cap
(`budgets.per_run_usd.autofix`, default 20).

## Test cases and results in Jira (Xray)

With [Xray](https://marketplace.atlassian.com/apps/1211769) on the Jira
site and an Xray API key in the repo secrets `XRAY_CLIENT_ID` and
`XRAY_CLIENT_SECRET`, every story's test cases and results are kept in Jira
(`xray_sync.py`):

| When | In Jira |
|---|---|
| The plan is approved (the build starts) | One Xray **Test** per planned test case (each AC, EC and BUG), linked to the story; a **Test Plan** for the story; a **Test Execution** "planned" with every test at TODO |
| The story PR's tests run | A **Test Execution** "PR #n" with each test PASSED or FAILED, the failure text, and the screenshots of every browser test |
| The tests on the base branch after the merge | A **Test Execution** "main, after PR #n", the same way |

Each execution is linked to the story and added to its Test Plan, so the
story shows its tests and their history. A test is the same Xray Test from
run to run. Tests named for the story but not in the plan are recorded too.
Xray never blocks a run: without the secrets the steps skip, and an API
problem is a warning.

Set up once: install Xray, map its work types in the space (Test, Test
Execution, Test Plan, Test Set, Precondition), create an API key, add the
two secrets. The project's tests must write JUnit XML (`results_path`) and
screenshots (`evidence_path`); the scaffold story sets this up when the keys
are in `.sdlc/build.yaml`. A regional Xray (EU, US, AU) sets the repo
variable `XRAY_BASE_URL`.

## Answering review findings on a PR

The review gate posts its summary as one comment, and each **high** and
**medium** finding as its own numbered comment (low findings stay in the
summary). The comments of an earlier review are minimized as outdated. The
reviewer answers with a comment:

| Comment | What happens |
|---|---|
| `/sdlc fix 1` | `build-story mode=fix-findings` fixes finding 1 on the PR's branch as suggested, checks and verifies, and pushes to the PR; the review gate and the tests run again |
| `/sdlc fix 1 2 keep the links, update the design` | Fixes findings 1 and 2 the reviewer's way (the story's design may change when asked) |
| `/sdlc fix all` | Every finding of the latest review |
| `/sdlc dismiss 2 fine for the prototype` | Accepts finding 2; the next review does not report it again. Dismissing a high finding re-runs the gate at once |

Only owners, members and collaborators can ask (`sdlc-fix-findings.yml`,
called from `sdlc-comment.yml`). The fix has its own AI cap
(`budgets.per_run_usd.review-fix`, default 20) and never changes the plan,
the spec or other SDLC files.

## The fix lane

Small changes that restore behaviour (a bug fix, a typo, a dependency bump)
do not need an intent, spec and plan: `/sdlc:fix` works on a `fix/<name>`
branch, writes a failing test first, and opens a PR. The build guard allows
code on `fix/` branches without a plan; the PR still goes through the review
gate and the tests (not traceability). A fix PR over `fix_max_lines` (300)
changed lines gets a warning: bigger changes are stories.

## Repo variables and secrets

| Name | Kind | Needed for |
|---|---|---|
| `SDLC_APP_ID` | variable | every workflow (the sdlc-bot GitHub App) |
| `SDLC_APP_PRIVATE_KEY` | secret | every workflow |
| `ANTHROPIC_API_KEY` (recommended) or `CLAUDE_CODE_OAUTH_TOKEN` | secret | every AI step. Use an API key from an Anthropic Console workspace for CI: it belongs to the organisation and the workspace's spend limit is the hard cost ceiling. A subscription token (`claude setup-token`) belongs to one person and shares their usage limits. Set one, not both |
| `JIRA_BASE_URL`, `JIRA_USER_EMAIL` | variables | Jira (if enabled) |
| `JIRA_API_TOKEN` | secret | Jira (if enabled) |
| `DEPLOY_TOKEN` / `DEPLOY_TARGET` | secret / variable, per environment | `deploy_command` |
| `AWS_ROLE_ARN`, `AWS_REGION` / `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` / `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT` | variables on each environment (`staging`, `production-plan` with a read-only identity, `production`) | OIDC cloud login in releases, for the `cloud` in `.sdlc/deploy.yaml` |
| `SMOKE_URL` | variable, per environment | `smoke_command` |
| `FIGMA_TOKEN` | environment variable on the designer's machine | PNG export after refining the mockups in Figma (not needed for the automatic mockups) |
