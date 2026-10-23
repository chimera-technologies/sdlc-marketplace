# sdlc-marketplace

A Claude Code plugin marketplace (`chimera-sdlc`) with one plugin, `sdlc`,
that runs an AI-native software lifecycle in any project and any tech stack:
Plan, Design (spec and UI), Build, PR review, Test, Deploy and Maintain. Each
stage commits an artifact the next stage reads; a human merge approves every
step; hooks and deterministic checks enforce what must always hold.

Adopt it in a project in one command, **`/sdlc:init`**: see
[Set up a new project, step by step](#set-up-a-new-project-step-by-step) below, and
[docs/adoption.md](docs/adoption.md) for the details.

## Set up a new project, step by step

Three parts: **A** once per GitHub organization, **B** once per project,
**C** what happens on the first run. Steps marked *(optional)* can be
skipped; the stage that needs them then stays off or skips that part.

### Before you start

**People**
- A GitHub **organization owner**, for part A (once).
- An **admin of the project repo**, for part B.
- A **Jira admin** of the space, if you use Jira *(optional)*.

**On your machine**

| Tool | Check | Install |
|---|---|---|
| git | `git --version` | [git-scm.com](https://git-scm.com) |
| GitHub CLI, signed in | `gh auth status` | [cli.github.com](https://cli.github.com), then `gh auth login` and `gh auth setup-git` |
| Node.js 18 or newer | `node --version` | [nodejs.org](https://nodejs.org) |
| Claude Code, signed in | `claude --version` | `npm install -g @anthropic-ai/claude-code`, then run `claude` once to sign in |
| Python 3.9 or newer | `python --version` (or `python3`) | [python.org](https://www.python.org) |

You must be able to read this repo: it is private to the organization.
`gh auth setup-git` lets Claude Code clone it when it installs the plugin.

**Accounts**
- An **Anthropic Console** account, for the API key the automation uses.
- **Jira Cloud** *(optional)*, and **Xray** in that Jira *(optional)*.

**GitHub plan.** On the Free plan, private repos share 2,000 Actions minutes
a month across the organization, and branch protection is not available
for them. Everything works, but the required checks are not enforced and
the automation stops when the minutes run out.

### A. Once per GitHub organization

**A1. Let projects use the marketplace.** In this repo, go to **Settings >
Actions > General > Access**, and choose "Accessible from repositories
owned by" the organization. Projects then call its reusable workflows and
read the plugin. (For a client's organization, push a copy of this repo with
its tags into that organization, and use it as `sdlc_repo` in init.)

**A2. Create the sdlc-bot GitHub App.** This App is the identity that opens
PRs and posts comments. One App serves every project in the organization.
It gives you `SDLC_APP_ID` and `SDLC_APP_PRIVATE_KEY`.
1. Go to the organization's **Settings > Developer settings > GitHub Apps >
   New GitHub App**.
2. Fill in the form:
   - **GitHub App name**: unique across GitHub, for example `<org>-sdlc-bot`.
   - **Homepage URL**: any URL, for example the organization's page.
   - **Webhook**: clear **Active**.
   - **Repository permissions**: Contents *Read and write*, Pull requests
     *Read and write*, Issues *Read and write*, Metadata *Read-only*.
   - **Organization permissions**: Members *Read-only*. This is only needed
     if you request reviews from teams.
   - **Where can this GitHub App be installed?**: *Only on this account*.
3. Click **Create GitHub App**.
4. **`SDLC_APP_ID`**: the App's **General** page shows **App ID**, a number
   such as `1234567`. Use the App ID, not the *Client ID*.
5. **`SDLC_APP_PRIVATE_KEY`**: on the same page, under **Private keys**,
   click **Generate a private key**. GitHub downloads a `.pem` file. The
   secret is the whole file, including the `-----BEGIN` and `-----END`
   lines. Keep it in your password vault, and delete the downloaded copy
   once it is stored.
6. Click **Install App** in the left menu, then **Install** next to the
   organization. Choose **Only select repositories** and pick this repo.

**A3. Create the Anthropic API key.** The automation's AI steps run with it.
1. Sign in to [console.anthropic.com](https://console.anthropic.com).
2. **Settings > Workspaces > Create workspace**, one per project or team
   (for example `sdlc-<project>`).
3. In the workspace's **Limits**, set a **monthly spend limit**. It is the
   hard cost ceiling for everything the automation does.
4. **API keys > Create key**, in that workspace. Copy it once: it is shown
   only at creation. It becomes the secret `ANTHROPIC_API_KEY` (step B5).

A subscription token (`claude setup-token`, stored as
`CLAUDE_CODE_OAUTH_TOKEN`) also works, but it belongs to one person and
shares their usage limits. Use an API key for a team.

**A4. Organization-wide variables and secrets** *(optional, saves repeating
B5 in every project)*. In the organization's **Settings > Secrets and
variables > Actions**, add `SDLC_APP_ID` (variable) and
`SDLC_APP_PRIVATE_KEY` (secret), with access for the selected repositories.
A new project is then added to that list instead.

**A5. Jira API token** *(optional)*. The automation signs in to Jira as one
account, usually a service account that can edit the space's issues.
1. Signed in as that account, open
   [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
2. **Create API token**, name it `sdlc`, and copy it. It becomes the secret
   `JIRA_API_TOKEN`.
3. Note the account's email (`JIRA_USER_EMAIL`) and the site URL, such as
   `https://<site>.atlassian.net` (`JIRA_BASE_URL`).

**A6. Jira statuses** *(optional)*. The bot moves each story through To Do,
In Planning, In Progress, Dev Completed, In QA, In Review and Done. Add the
three that most spaces lack: **In Planning**, **Dev Completed** and **In
QA**.
- **Team-managed space**: on the board, click **+** after the last column and
  type each name; or **Space settings > Work types > Story > Edit workflow >
  Add status**.
- **Company-managed space**: **Space settings > Workflows**, edit the Story
  workflow, **Add status**, then **Publish draft**.

In both, tick **Allow all statuses to transition to this one**, and set
each new status's category to **In Progress**. Other names: set
`status_<stage>` in the project's `.sdlc/jira.yaml`.

**A7. Xray** *(optional: test cases and results in Jira)*.
1. Install **Xray Test Management** from the Atlassian Marketplace (Jira
   **Settings > Apps > Find new apps**).
2. In the space, enable the Xray issue types (Test, Test Execution, Test
   Plan): Xray's **Project settings** offer it when you open the space.
3. **Jira Settings > Apps > Xray > API Keys > Create API Key**, for the
   account the automation uses. Copy the **Client ID** and **Client
   Secret**: they become the secrets `XRAY_CLIENT_ID` and
   `XRAY_CLIENT_SECRET`.

### B. In each project

**B1. The repo.** Create it in the organization (or use an existing one).
It needs a `main` branch with at least one commit. Clone it and open a
terminal in its folder.

**B2. Install the plugin**, in the project folder:

```bash
claude plugin marketplace add chimera-technologies/sdlc-marketplace
claude plugin install sdlc@chimera-sdlc --scope project
```

`--scope project` records the plugin in `.claude/settings.json`, so every
teammate who opens the repo in Claude Code gets it too.

**B3. Have these answers ready.** `/sdlc:init` asks for them:

| Question | Example |
|---|---|
| Product owner, service owner, tech lead, security owner (GitHub handles or teams) | `@alice`, `@acme/sre`, `@bob` |
| Jira on or off; site and space key | `acme.atlassian.net`, `ACM` |
| Stages to enable (default all) | `plan, design, ui_design, build, pr_review, test, deploy, maintain` |
| Automatic Build (default yes) | yes: every story gets a plan PR, then CI builds it |
| The stack, or "decide from the spec later" | `node@22`, `npm ci`, `npm test`; a new repo: decide later |
| The release to pin (default: the latest) | `v0.25.0` |
| The requirement document, if you have one | a `.md`, `.txt` or `.pdf` on your machine |

**B4. Run `/sdlc:init`.** Start Claude Code in the project folder (`claude`)
and type `/sdlc:init`. It:
1. finds what it can on its own (the Jira site from `JIRA_BASE_URL`, the
   existing stack, the latest release);
2. asks the rest in one message (B3);
3. writes everything on an `sdlc/init` branch: `.sdlc/` (the config:
   `sdlc.json`, `owners.yaml`, `jira.yaml`, `build.yaml`, `review.json`,
   ...), the `sdlc-*.yml` callers under `.github/workflows/`,
   `.claude/settings.json`, a block in `CLAUDE.md`, `REVIEW.md`,
   `PATTERNS.md`, and your requirement document in `requirements/`;
4. opens the setup PR, and prints a checklist of what is still missing.

Don't merge the setup PR yet: first do B5 and B6.

**B5. Install the sdlc-bot App on the project.** Organization **Settings >
GitHub Apps** (*Installed GitHub Apps*) **> sdlc-bot > Configure >
Repository access**, and add the project.

**B6. Add the variables and secrets** in the project, under **Settings >
Secrets and variables > Actions** (skip the ones you set for the whole
organization in A4):

| Name | Tab | Value |
|---|---|---|
| `SDLC_APP_ID` | Variables | the App ID (A2.4) |
| `SDLC_APP_PRIVATE_KEY` | Secrets | the whole `.pem` file (A2.5) |
| `ANTHROPIC_API_KEY` | Secrets | the API key (A3). Or `CLAUDE_CODE_OAUTH_TOKEN`; set one, not both |
| `JIRA_BASE_URL` | Variables | `https://<site>.atlassian.net` (A5) *(optional)* |
| `JIRA_USER_EMAIL` | Variables | the Jira account's email (A5) *(optional)* |
| `JIRA_API_TOKEN` | Secrets | the Jira API token (A5) *(optional)* |
| `XRAY_CLIENT_ID`, `XRAY_CLIENT_SECRET` | Secrets | the Xray API key (A7) *(optional)* |

A value on the wrong tab is not read: for example, `XRAY_CLIENT_ID` added as
a variable silently turns Xray off. From the command line, in the project
folder:

```bash
gh variable set SDLC_APP_ID --body 1234567
gh secret set SDLC_APP_PRIVATE_KEY < ~/Downloads/<app>.private-key.pem
gh secret set ANTHROPIC_API_KEY                  # prompts for the value
gh variable set JIRA_BASE_URL --body https://<site>.atlassian.net
gh variable set JIRA_USER_EMAIL --body <email>
gh secret set JIRA_API_TOKEN
gh secret set XRAY_CLIENT_ID
gh secret set XRAY_CLIENT_SECRET
```

**B7. Check, then merge the setup PR.** In Claude Code, `/sdlc:init check`
reports anything that differs from what init generates. Then merge the
setup PR. With a requirement document in `requirements/`, the merge starts
the loop by itself (C1).

**B8. Branch protection** *(needs a paid GitHub plan for private repos)*.
**Settings > Branches > Add branch ruleset** (or *Add rule*) for `main`:
require a pull request before merging, and require these status checks once
each has run at least once (GitHub lists only checks it has seen):
`pr / review-gate`, `pr / traceability`, `pr / e2e`, and the
`intent-check / validate`, `spec-check / validate`, `design-check /
validate` checks of the stages you enabled. A skipped check counts as
passed.

**B9. Jira Automation** *(optional, Plan stage)*: a Jira ticket labelled
`intent` becomes an intent PR.
1. Create a GitHub **fine-grained personal access token**. In GitHub, open
   **Settings > Developer settings > Fine-grained tokens > Generate new
   token**. Resource owner: the organization; repository: only the project;
   permission: **Contents: Read and write**.
2. In Jira: **Space settings > Automation > Create rule**:
   - trigger **Field value changed**, field **Labels**;
   - condition **JQL**: `labels = intent`;
   - action **Send web request**: `POST
     https://api.github.com/repos/<owner>/<project>/dispatches`, headers
     `Authorization: Bearer <the token>` and
     `Accept: application/vnd.github+json`, body
     `{"event_type":"create-intent","client_payload":{"source":"jira","record_id":"{{issue.key}}"}}`.

**B10. Spend limits.** In `.sdlc/sdlc.json`, `budgets` sets a cap per run and
per month for the AI steps (defaults are set by init). See
[AI spend limits](docs/configuration.md#ai-spend-limits).

### C. The first run: what happens

| # | What happens | Who acts |
|---|---|---|
| C1 | Merging the setup PR (or a later PR that adds a document to `requirements/`) opens **one intent PR per intent** | the owner reviews and merges each |
| C2 | Each merged intent opens a **spec PR**: requirements, the stack decision, the stories, and HTML mockups of every screen | owner and tech lead review; `/sdlc revise <change>` to change it; merge |
| C3 | The merged spec creates the **Jira stories** with numbered ACs, and opens a **stack PR** (`.sdlc/build.yaml`) | the tech lead merges the stack PR |
| C4 | Story 1 gets a **plan PR**: files, a test per AC, edge cases found by an AI review | the owner merges it (the approval) |
| C5 | CI **builds the story** test-first, a verifier checks every AC, and the **story PR** opens | — |
| C6 | On the story PR: the **review gate** posts findings as comments; the **tests** run; Jira moves to In QA, then In Review | the reviewer answers findings (`/sdlc fix`, `/sdlc dismiss`) and merges |
| C7 | The merge moves the story to **Done**, writes its **test report**, and starts the next story's plan PR | — |

Without a requirement document, start with `/sdlc:write-intent` in Claude
Code, or label a Jira ticket `intent` (B9).

**Other stages** *(optional)*: Deploy needs GitHub environments and a
`deploy_command`; refining mockups in Figma needs a Figma login. See
[docs/adoption.md](docs/adoption.md).

### If something doesn't work

| Symptom | Cause and fix |
|---|---|
| Every check fails within seconds; "The job was not started because recent account payments have failed or your spending limit needs to be increased" | The organization's Actions minutes are used up (Free plan: 2,000 a month). Wait for the monthly reset, or raise the spending limit |
| `claude plugin marketplace add` can't clone the repo | You can't read this private repo yet. Ask for access, then `gh auth setup-git` |
| A workflow says `SDLC_APP_ID` or the private key is missing, or "Resource not accessible by integration" | B5 or B6 not done: the App isn't installed on the project, or a value is missing or on the wrong tab |
| Xray steps are skipped | `XRAY_CLIENT_ID` is a variable, not a secret (B6) |
| A Jira status doesn't change | The status doesn't exist in the workflow, or can't be reached from the current one (A6) |
| An AI step stops with a usage or session limit | The subscription token's limit; use an API key (A3) |
| Builds or tests fail installing packages | The machine or network can't reach the npm or PyPI registry |

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
