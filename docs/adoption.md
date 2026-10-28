# Adopt the SDLC loop in a project

About 30 minutes, once per project. You need admin on the project repo and
on the marketplace repo (or someone who has it).

## 1. One-time, for the marketplace (per GitHub account or org)

1. **Let projects use the marketplace.** In `chimera-technologies/sdlc-marketplace`
   > Settings > Actions > General > **Access**, choose "Accessible from
   repositories owned by" your account or organization. Projects then call
   its reusable workflows and read the plugin.
2. **Create the sdlc-bot GitHub App** (Settings > Developer settings > GitHub
   Apps), webhook off, repository permissions Contents RW, Pull requests RW,
   Issues RW, Metadata R (organization Members R for team reviewers).
   Generate a private key. Install it on the marketplace repo.

## 2. In the project

1. **Install the plugin** in Claude Code, in the project folder:
   ```
   claude plugin marketplace add chimera-technologies/sdlc-marketplace
   claude plugin install sdlc@chimera-sdlc --scope project
   ```
2. **Run `/sdlc:init`** in a Claude Code session there. It asks for owners,
   Jira, stages, the stack (or "decide from the spec"), and the tag, then
   writes everything on an `sdlc/init` branch and opens a PR. Merge it.
3. **Install the sdlc-bot App** on the project repo too.
4. **Variables and secrets** (project > Settings > Secrets and variables >
   Actions): see the table in [configuration.md](configuration.md#repo-variables-and-secrets).
   For the Claude credential, create a workspace for the project (or team)
   in the Anthropic Console, set its monthly spend limit, and store its API
   key as `ANTHROPIC_API_KEY`. Then set the per-run and monthly `budgets` in
   `.sdlc/sdlc.json` ([AI spend limits](configuration.md#ai-spend-limits)).
5. **Branch protection** on the base branch: require the checks from
   [stages.md](stages.md) once each has run once (GitHub only lists checks
   it has seen). Skipped checks count as passing, so non-story PRs are not
   blocked by story checks.
6. **Jira Automation** (if Jira is on): rule "Field value changed: Labels",
   condition `labels = intent`, action "Send web request" POST
   `https://api.github.com/repos/<owner>/<project>/dispatches`, headers
   `Authorization: Bearer <fine-grained PAT, Contents: write on this repo>`,
   `Accept: application/vnd.github+json`, body
   `{"event_type":"create-intent","client_payload":{"source":"jira","record_id":"{{issue.key}}"}}`.
7. **Deploy** (if on): create environments `staging` and `production`
   (Settings > Environments), give `production` required reviewers, add
   `DEPLOY_TOKEN` / `DEPLOY_TARGET` if your `deploy_command` needs them, and
   set `deploy_command` in `.sdlc/deploy.yaml`.
8. **UI design** (if on): nothing to set up for the automatic mockups. To
   refine them in Figma, a designer trusts the repo so the Figma plugin
   installs, logs in with `/mcp`, sets `FIGMA_TOKEN` for PNG export, and
   runs `/sdlc:design-ui spec=specs/<slug>.md from=mockups`.

## 3. First run

- Plan: put the requirement document in `requirements/` (init asks for it
  and adds it to the setup PR); merging the setup PR turns it into one
  intent PR per intent. Or `/sdlc:write-intent` with a requirement, or label a Jira ticket
  `intent`. Merge the intent PR: the spec PR follows.
- After the spec merges, a **stack PR** opens by itself with the spec's
  stack and cloud decision for `.sdlc/build.yaml` and `.sdlc/deploy.yaml`
  (each value with the spec line it comes from). The tech lead merges it.
  If the spec still says "Decision needed", no PR opens: decide it, or run
  `/sdlc:init stack=specs/<slug>.md` by hand.
- Build: automatic once the stack is recorded. Each story gets a plan PR;
  merging it builds the story in CI and opens the story PR; merging that
  starts the next story. To build by hand instead, set `"auto_build": false`
  in `.sdlc/sdlc.json`, re-run init, and use `/sdlc:build-story <KEY>`.

## An existing project, or only Build

Init adds only `.sdlc/`, the `sdlc-*.yml` callers, `.claude/settings.json`
and a block in `CLAUDE.md`; the code and its own CI stay as they are. Before
adopting, make the existing suite pass in CI with `test_command`, and use
`{files}` in `check_command` (for example `npx eslint {files}`) so older
lint and type problems do not block new work.

**Learning the codebase.** On a repo that already has code, `/sdlc:init`
also writes the notes Build reads before every story, from the code itself:
`PATTERNS.md` (how this codebase structures features, validates input and
returns errors, reaches the database and services, builds UI, holds state
and writes tests, each with the real files) and an `## Architecture`
section in `CLAUDE.md` (the main modules, entry points, how to run and test,
and the areas that need care). It maps the code with the Graphify graph
first, and `codebase_notes.py check` rejects any section left empty or any
file path that does not exist. The notes come in the setup PR for the tech
lead to correct and to add what the code cannot show. For a project set up
earlier, run `/sdlc:init learn`. Builds warn while the notes are still empty.

To adopt **only Build** on an existing backlog, turn the other stages off
when init asks (or in the answers):

```json
"stages": {"plan": false, "design": false, "ui_design": false,
           "build": true, "pr_review": true, "test": true,
           "deploy": false, "maintain": false}
```

Then build any Jira ticket with `/sdlc:build-story <KEY>` (**ticket mode**):
its acceptance criteria (an "Acceptance criteria" list, Given/When/Then, or
`AC-1:` lines) become a ticket brief, `tickets/<key>.md`, a one-story spec
the plan, the review gate, traceability, Xray and the test report use. A
ticket without criteria gets criteria proposed and approved by the person
first. The brief is committed with the story; nothing watches `tickets/`,
so no Jira stories, stack PR or automatic build come from it. The story PR
gets the full PR review, tests, autofix and Jira statuses. Small changes
need no ticket at all: `/sdlc:fix` (the fix lane).

**Design screens for a ticket**: attach them to the Jira ticket as PNG or
JPEG images. Ticket mode downloads them into `designs/<key>/screens/` and
writes `designs/<key>/design.md`, so the plan, the build, the verifier and
the review gate work against them as they do against a spec's mockups. The
download needs `JIRA_BASE_URL`, `JIRA_USER_EMAIL` and `JIRA_API_TOKEN` in the
developer's environment; without them, save the images into
`designs/<key>/screens/` yourself. The screens are committed with the story.

## Upgrading

`/sdlc:init upgrade=vX.Y.Z` (or `init_project.py --upgrade vX.Y.Z`) moves
every caller and the plugin pin in one PR. Read the marketplace's
[CHANGELOG.md](../CHANGELOG.md) (its **Upgrading** steps) for anything new to
configure. `init_project.py --check` reports any
drift from what init generates.
