# AI-native SDLC: skills and workflows (POC)

Implements the headless loop from `AI-native SDLC architecture.html`, one
stage at a time.

**POC layout:** this one repo, `bala-chimera/sdlc-marketplace` (private), is
both the plugin marketplace and the product repo the loop runs in. Every
owner is `@bala-chimera`. See [Splitting later](#splitting-later) for the
target two-repo setup.

| Stage | Status |
|---|---|
| 1 Plan | Done: `sdlc:write-intent`, create-intent, intent-check, intent-to-spec (boundary) |
| Cross-cutting | Started: `sdlc:security-policy` (draft), guardrail hooks, CLAUDE.md, CI, evals (6 cases), managed-settings example |
| 2 Design | Next: `sdlc:write-spec`, adversarial pre-screen reviewer |
| 3–6 | Later |

## Layout

```
CLAUDE.md                           rules for Claude in this repo
.claude-plugin/marketplace.json     marketplace chimera-sdlc (only source of skills)
.claude/settings.json               enables sdlc@chimera-sdlc (pinned tag) for interactive use
.sdlc/owners.yaml                   who approves intents (POC: default only)
.github/CODEOWNERS
.github/workflows/
  ci.yml                            plugin: unit tests, fixtures, versions, plugin validate
  evals.yml                         plugin: end-to-end evals (POC: manual run only)
  create-intent.yml                 SDLC: headless intake (Jira now; Maintain/Security/Tag later)
  intent-check.yml                  SDLC: validate + route reviewer + Jira link-back
  intent-to-spec.yml                SDLC: Plan -> Design trigger on merge
plugins/sdlc/
  .claude-plugin/plugin.json
  .mcp.json                         Atlassian remote MCP (interactive use)
  hooks/hooks.json                  headless write guard (Pre) + intent validation (Post)
  skills/security-policy/SKILL.md   DRAFT policy rules SEC-1..8; owner must sign off
  skills/write-intent/
    SKILL.md                        interactive + headless entry
    reference/headless.md           rules when no human can answer
    templates/intent.md             the template (frontmatter + 8 sections)
    scripts/validate_intent.py      deterministic validator (stdlib only)
    examples/…                      worked example + owners fixture, seed for evals
intent/                             accepted intents (one per merged PR)
specs/                              specs generated from intents
tests/                              stdlib unittest: validator, hooks, eval scoring
evals/                              run_evals.py + write-intent cases (see evals/README.md)
platform/managed-settings.json      example for IT to deploy (not needed for the POC)
```

The SDLC workflows use the plugin from the same checkout (`plugins/sdlc`),
so a skill change takes effect in CI as soon as it is merged to `main`.

## Plan stage flow (headless)

```
Jira ticket labelled "intent"
  -> Jira Automation: POST /repos/bala-chimera/sdlc-marketplace/dispatches {event_type: create-intent}
  -> create-intent.yml: dedup -> fetch ticket (curl, token never given to Claude)
       -> claude-code-action: /sdlc:write-intent mode=headless
       -> validate -> PR on intent/<jira-key> (draft if invalid), reviewer = owner
       -> Jira comment + remote link to PR
  -> intent-check.yml: validate (required check), label source/risk, request owner
  -> OWNER merges (accept) or closes with reason (reject)   <- human gate
  -> intent-check.yml link-back: Jira gets outcome + merge SHA
  -> intent-to-spec.yml: Design starts
```

Interactive path: anyone runs `/sdlc:write-intent` (or just asks "turn
CLM-123 into an intent") in Claude Code, which opens the same kind of PR
and goes through the same checks. Non-engineers can do the same in
claude.ai using the GitHub and Atlassian connectors.

## One-time setup

1. **Push and tag:** push this repo to `bala-chimera/sdlc-marketplace` and
   tag it `v0.1.0` (`.claude/settings.json` pins that tag for interactive use).
2. **GitHub App** (`sdlc-bot`): permissions Contents RW, Pull requests RW,
   Metadata R (plus organization Members R later, for team reviewers).
   Install it on this repo. PRs opened with its token trigger
   `intent-check` (PRs opened with `GITHUB_TOKEN` would not).
3. **Actions variables and secrets** (Settings → Secrets and variables →
   Actions; never in a file):
   - Variables: `SDLC_APP_ID`, `JIRA_BASE_URL`
     (`https://chimeratechnologies-team-tk54z9ne.atlassian.net`), `JIRA_USER_EMAIL`
   - Secrets: `ANTHROPIC_API_KEY`, `SDLC_APP_PRIVATE_KEY`, `JIRA_API_TOKEN`
4. **Branch protection on `main`:** require the `Intent check / validate`
   status check. Private repos on a free GitHub plan can't enforce this;
   the checks still run. With a single owner, don't require a code-owner
   review: you can't approve your own PRs.
5. **Jira Automation rule** (per Jira space):
   - Trigger: *Label added* = `intent` (or *Issue transitioned* to "Ready for intent")
   - Action: *Send web request*: `POST https://api.github.com/repos/bala-chimera/sdlc-marketplace/dispatches`
     - Headers: `Authorization: Bearer <fine-grained PAT, Contents: write on this repo only>`,
       `Accept: application/vnd.github+json`
     - Body: `{"event_type":"create-intent","client_payload":{"source":"jira","record_id":"{{issue.key}}"}}`
6. **Interactive use:** trust the repo's `.claude/settings.json` when
   prompted, then run `/mcp` once to authenticate Atlassian. To try
   unreleased plugin changes, run `claude --plugin-dir plugins/sdlc`.
7. **Releasing a plugin version:** bump the version (see CLAUDE.md), tag
   `v<version>`, and update the `ref` in `.claude/settings.json`.

## Try it without Jira

Actions → *Create intent (headless Plan)* → Run workflow with
`source=maintain`, `fingerprint=p95-latency-claims-api`, and a `signal`
such as
`{"metric":"p95_latency_ms","tier":3,"value":2400,"band":"<=800","service":"claims-core","breach_id":"BR-1"}`.

## Splitting later

Before a second team uses the skills, split this repo in two:

- `sdlc-marketplace` keeps `.claude-plugin/`, `plugins/`, `tests/`,
  `evals/`, `platform/`, `ci.yml` and `evals.yml`.
- Each product repo gets `.claude/`, `.sdlc/`, `intent/`, `specs/` and the
  three SDLC workflows. In those workflows, add back a step that checks out
  the marketplace at a pinned tag into `.sdlc-plugin/` (repo variables
  `SDLC_PLUGIN_REPO`, `SDLC_PLUGIN_REF`), and point `PLUGIN_DIR` and
  `VALIDATE` at `.sdlc-plugin/plugins/sdlc/...`.

Why split: one marketplace serves many product repos, skill changes are
released by tag instead of taking effect on merge, and the agent working
in a product repo can't change the rules that check it.

## Recommended add-ons

- **Anthropic document skills** (`pdf`, `docx`, `pptx`): let write-intent
  read requirement documents in Step 1.
- **Fireflies MCP** (optional): lets you turn a meeting transcript into an
  intent.
- **Evals (wave 3):** grow `evals/write-intent/` to 20–50 accepted intents
  with their source tickets, then turn on the PR and nightly triggers in
  `evals.yml` so a change is blocked if the pass rate drops.
