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

## Upgrading

`/sdlc:init upgrade=vX.Y.Z` (or `init_project.py --upgrade vX.Y.Z`) moves
every caller and the plugin pin in one PR. Read the marketplace's
[CHANGELOG.md](../CHANGELOG.md) (its **Upgrading** steps) for anything new to
configure. `init_project.py --check` reports any
drift from what init generates.
