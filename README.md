# sdlc-marketplace

A Claude Code plugin marketplace (`chimera-sdlc`) with one plugin, `sdlc`,
that runs an AI-native software lifecycle in any project and any tech stack:
Plan, Design (spec and UI), Build, PR review, Test, Deploy and Maintain. Each
stage commits an artifact the next stage reads; a human merge approves every
step; hooks and deterministic checks enforce what must always hold.

Adopt it in a project in one command, **`/sdlc:init`**: see
[Set up a new project](#set-up-a-new-project) below, and
[docs/adoption.md](docs/adoption.md) for the details.

## Set up a new project

### Once per GitHub organization

1. **Let projects use the marketplace.** In this repo, go to Settings >
   Actions > General > **Access**, and choose "Accessible from repositories
   owned by" the organization. (For a client's organization, push a copy of
   this repo with its tags into that organization, and use it as
   `sdlc_repo`.)
2. **Create the sdlc-bot GitHub App.** This App is the identity that opens
   PRs and posts comments. One App serves every project in the
   organization. It gives you `SDLC_APP_ID` and `SDLC_APP_PRIVATE_KEY`.
   1. Go to the organization's **Settings > Developer settings > GitHub
      Apps > New GitHub App**. You need to be an organization owner.
   2. Fill in the form:
      - **GitHub App name**: unique across GitHub, for example
        `<org>-sdlc-bot`.
      - **Homepage URL**: any URL, for example the organization's page.
      - **Webhook**: clear **Active**.
      - **Repository permissions**: Contents *Read and write*, Pull
        requests *Read and write*, Issues *Read and write*, Metadata
        *Read-only*.
      - **Organization permissions**: Members *Read-only*. This is only
        needed if you request reviews from teams.
      - **Where can this GitHub App be installed?**: *Only on this
        account*.
   3. Click **Create GitHub App**.
   4. **`SDLC_APP_ID`**: the App's **General** page shows **App ID**, a
      number such as `1234567`. Use the App ID, not the *Client ID*.
   5. **`SDLC_APP_PRIVATE_KEY`**: on the same page, under **Private
      keys**, click **Generate a private key**. GitHub downloads a `.pem`
      file. The secret is the whole file, including the `-----BEGIN` and
      `-----END` lines. Keep it in your password vault, and delete the
      downloaded copy once it's stored.
   6. Click **Install App** in the left menu, then **Install** next to the
      organization. Choose **Only select repositories** and pick this repo.

   You can store the two values once, as **organization** variables and
   secrets (organization Settings > Secrets and variables > Actions, with
   access for the selected repositories). Then each project only needs to
   be added to the App and to that list.

### In each project

```bash
# 1. Install the plugin (in the project folder)
claude plugin marketplace add chimera-technologies/sdlc-marketplace
claude plugin install sdlc@chimera-sdlc --scope project

# 2. Set it up. In a Claude Code session in the project:
/sdlc:init
#    asks: owners, Jira, stages, stack (or "decide from the spec"), release tag;
#    writes everything on an sdlc/init branch and opens a PR. Merge it.
```

3. **Install the sdlc-bot App** on the project repo: go to organization
   Settings > GitHub Apps (*Installed GitHub Apps*) > sdlc-bot >
   **Configure** > Repository access, and add the project.
4. **Add the variables and secrets** in the project, under Settings >
   Secrets and variables > Actions:

   | Name | Kind | For |
   |---|---|---|
   | `SDLC_APP_ID` | variable | the sdlc-bot App: its **App ID** (step 2.4 above) |
   | `SDLC_APP_PRIVATE_KEY` | secret | the sdlc-bot App: the whole `.pem` file (step 2.5 above) |
   | `ANTHROPIC_API_KEY` (recommended) or `CLAUDE_CODE_OAUTH_TOKEN` | secret | every AI step. Use a key from an Anthropic Console workspace that has a monthly spend limit |
   | `JIRA_BASE_URL`, `JIRA_USER_EMAIL` | variables | Jira (optional) |
   | `JIRA_API_TOKEN` | secret | Jira (optional) |
   | `XRAY_CLIENT_ID`, `XRAY_CLIENT_SECRET` | secrets | Xray test cases and results (optional) |

   Add a *variable* on the **Variables** tab and a *secret* on the
   **Secrets** tab. A value on the wrong tab is not read: for example,
   `XRAY_CLIENT_ID` added as a variable silently turns Xray off. You can
   also store them from the command line, in the project folder:

   ```bash
   gh variable set SDLC_APP_ID --body 1234567                 # the App ID
   gh secret set SDLC_APP_PRIVATE_KEY < ~/Downloads/<app>.private-key.pem
   gh secret set ANTHROPIC_API_KEY                            # prompts for the value
   ```

5. **Branch protection** on `main`: require the checks that init lists
   (`pr / review-gate`, `pr / traceability`, `pr / e2e`, and the
   `*-check / validate` checks of the enabled stages) once each has run.
6. **Jira** (optional):
   - Add the statuses In Planning, Dev Completed and In QA to the space's
     workflow. The bot moves each story through them.
   - With the Plan stage on, add a Jira Automation rule for the `intent`
     label (init prints the exact rule).
7. **Spend limits:** set `budgets` in `.sdlc/sdlc.json` (per run and per
   month). See [AI spend limits](docs/configuration.md#ai-spend-limits).

Then start: merge a requirement document into `requirements/`, run
`/sdlc:write-intent`, or label a Jira ticket `intent`. Each stage after that
opens its own PR.

## An existing project, or only Build

Init only adds `.sdlc/`, the `sdlc-*.yml` callers, `.claude/settings.json`
and a block in `CLAUDE.md`. Your code and your own CI stay as they are.
Before adopting:
- make the existing tests pass in CI with `test_command`;
- use `{files}` in `check_command` (for example `npx eslint {files}`), so
  older lint problems don't block new work;
- record the codebase's conventions in `PATTERNS.md`.

**Only Build**, on an existing backlog: turn the other stages off in
`.sdlc/sdlc.json` (or when init asks), then regenerate with
`/sdlc:init upgrade=<current tag>`:

```json
"stages": {"plan": false, "design": false, "ui_design": false,
           "build": true, "pr_review": true, "test": true,
           "deploy": false, "maintain": false},
"auto_build": false
```

Then build any Jira ticket with **`/sdlc:build-story <KEY>`** (ticket mode).
It takes the ticket's acceptance criteria (an "Acceptance criteria" list,
Given/When/Then, or `AC-1:` lines) and writes them to
`tickets/<key>.md`. If the ticket has none, Claude proposes criteria for
the developer to approve. Then it plans, writes the tests first, builds,
verifies and opens the PR. The PR gets the full review gate, tests, autofix,
Xray and Jira statuses. Small changes need no ticket: use `/sdlc:fix`.

## Everyday commands

| Where | Command | What it does |
|---|---|---|
| Claude Code | `/sdlc:write-intent` | Turn a requirement into an intent (Plan) |
| Claude Code | `/sdlc:build-story <KEY>` | Build one story or Jira ticket test-first, verified, as a PR |
| Claude Code | `/sdlc:fix` | A small change without intent, spec or plan (the fix lane) |
| Claude Code | `/sdlc:release` | Cut a release (Deploy) |
| Claude Code | `/sdlc:init upgrade=vX.Y.Z` | Move the project to a new plugin release |
| PR comment | `/sdlc revise <request>` | Revise an intent, spec or plan PR on its branch |
| PR comment | `/sdlc fix <n> [how]`, `/sdlc fix all` | Fix review findings on a story PR |
| PR comment | `/sdlc dismiss <n> <reason>` | Accept a finding; the next review won't report it again |
| Actions | **SDLC push** > Run workflow > `rerun` | Re-run one stage for one file (for example `spec-to-stories`) |

## Stages

| Stage | Start it with | You get | Approved by |
|---|---|---|---|
| Plan | merge a requirement document into `requirements/` (or `/sdlc:write-intent`, or label a Jira ticket `intent`) | `intent/<slug>.md` (+ a Jira Epic) | the owner merging the intent PR |
| Design | automatic when an intent merges | `specs/<slug>.md`: requirements, **stack decision**, stories; pre-screened by an adversarial reviewer | owner (+ tech lead for high risk); stories then appear in Jira |
| UI design | automatic with the spec; `/sdlc:design-ui from=mockups` to refine in Figma | HTML mockups and a PNG of each screen in `designs/<slug>/` | owner merging the spec PR (or a design PR) |
| Build | automatic after each merge (or `/sdlc:build-story <KEY>`, also for a Jira ticket without a spec) | per story: a plan PR, then CI builds it test-first with an independent verifier and opens the story PR | owner merging the plan PR |
| PR review | opening the story PR | conformance review gate + Anthropic `code-review` (+ your own reviewers); each high or medium finding as a PR comment the reviewer answers with `/sdlc fix` or `/sdlc dismiss` | the gate, then the owner |
| Test | after the review gate | your project's tests, on your toolchain; failing tests fixed automatically (autofix); results and screenshots in Xray; after the merge, a test report per story in `test-reports/` | green checks |
| Deploy | `/sdlc:release` | release record, tag, staging, production | the production environment's reviewers |
| Maintain | scheduled checks | breaches become intents | the service owner |

Details: [docs/stages.md](docs/stages.md). Configuration:
[docs/configuration.md](docs/configuration.md).

## Big jobs: Claude Code workflows

Large requirement documents, large or high-risk specs and large story PRs
are handled by Claude Code workflows: several agents in parallel, then
skeptics that try to refute the results, and (for documents) a critic that
lists requirements no intent covers. Small inputs stay in one session. See
[plugins/sdlc/reference/workflows.md](plugins/sdlc/reference/workflows.md).

## Any tech stack

Nothing is tied to a language. The spec's tech lead decides the stack;
`/sdlc:init stack=specs/<slug>.md` records it in `.sdlc/build.yaml`
(`toolchains: [java@21]`, `test_command: mvn -B test`, ...). CI installs it
with the `setup-stack` action (Node, Python, Java, .NET, Go, Terraform, Helm,
kubectl built in; any other toolchain through `setup_command`) and runs the
project's own commands. Test names follow `S<n> AC-<k>` in each language's style.

The same goes for **where it runs**: the architect picks the cloud (AWS,
Azure, GCP or none) and the IaC tool in the spec, and `.sdlc/deploy.yaml`
records it. Releases log in with OIDC, plan Terraform on staging, show the
production plan to its approvers and apply exactly that plan, stop on
anything destroyed or replaced, and smoke-test each environment.
`sdlc:infra-policy` covers IaC, images, Kubernetes and the pipeline.

## How a project uses it

```
your-project/
  .sdlc/            sdlc.json (plugin tag, stages), owners, jira, build, review, deploy, maintain
  .claude/settings.json          plugin pins (sdlc, ponytail, figma)
  .github/workflows/sdlc-*.yml   ~20-line callers written by /sdlc:init, pinned to one tag
  CLAUDE.md                      an <!-- sdlc --> block, regenerated
  REVIEW.md                      what the PR review flags
  intent/ specs/ designs/ plans/ releases/ runbooks/
```

The callers invoke this repo's **reusable workflows**
(`.github/workflows/sdlc-*.yml`) at a pinned tag, so a fix reaches every
project by bumping one tag (`/sdlc:init upgrade=vX.Y.Z`).

## This repo

```
.claude-plugin/marketplace.json      the marketplace
plugins/sdlc/
  skills/        init, write-intent, write-spec, review-spec, design-ui, build-story, fix, review-plan,
                 review-story, release, triage, security-policy, infra-policy
                 (each: SKILL.md + templates/, scripts/, examples/, reference/)
  agents/        verifier (Build)
  workflows/     Claude Code workflows for big jobs: requirements-to-intents, review-panel
  reference/     workflows.md: when each workflow runs (thresholds, auto/always/off)
  hooks/         headless write guard, build guard, code hooks (secrets, lock files, dangerous
                 commands, format and lint after each write, Graphify kept current),
                 intent/spec/plan validation on write
.github/workflows/
  sdlc-*.yml     reusable workflows the projects call
  ci.yml         plugin tests, example validation, actionlint, plugin validate
  release-tag.yml  tags each new version when it merges, with its GitHub release
  evals.yml      end-to-end evals of the skills (manual for now)
.github/actions/setup-stack/        installs a project's declared toolchains
.github/actions/ai-budget/          AI spend limits around every headless Claude step
tests/           unit tests (stdlib unittest)
evals/           end-to-end eval cases (see evals/README.md)
platform/        managed-settings example for IT
docs/            adoption, stages, configuration, architecture, POC examples
```

## Develop

- Unit tests: `python -m unittest discover -s tests -v`
- Try the plugin without a release: `claude --plugin-dir plugins/sdlc`
- Release: bump `version` in `plugins/sdlc/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`, add a [CHANGELOG.md](CHANGELOG.md) entry
  (with **Upgrading** steps if projects must act), and merge the PR. The
  `release-tag` workflow tags the merge `v<version>` and publishes the GitHub
  release with that CHANGELOG entry, so the release is usable at once.
  Projects upgrade with `/sdlc:init upgrade=v<version>`.

The worked POCs:
- `chimera-technologies/skills-dashboard`, a skills dashboard taken from a
  requirement document through intent, spec, UI design, plans and stories,
  with Jira, Xray and the PR review loop;
- the first one, a workout app, in [docs/examples/poc/](docs/examples/poc/). The original architecture is
[docs/architecture.html](docs/architecture.html).
