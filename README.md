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
| 2 Design | Built: `sdlc:write-spec`, `sdlc:review-spec` (adversarial pre-screen), spec-check, spec-to-stories (Jira stories on merge) |
| Cross-cutting | Started: `sdlc:security-policy` (draft), guardrail hooks, CLAUDE.md, CI, evals (6 intent cases), managed-settings example |
| 3 Build | Built: `sdlc:build-story` (preflight: Graphify + Ponytail, plan, tests first, `sdlc:verifier`), build guard hook; product-repo `story-check.yml` |
| 4–6 | Later |

## Layout

```
CLAUDE.md                           rules for Claude in this repo
.claude-plugin/marketplace.json     marketplace chimera-sdlc (only source of skills)
.claude/settings.json               enables sdlc@chimera-sdlc (pinned tag) for interactive use
.sdlc/owners.yaml                   who approves intents (POC: default only)
.sdlc/jira.yaml                     Jira space for Epics created by interactive write-intent
.github/CODEOWNERS
.github/workflows/
  ci.yml                            plugin: unit tests, fixtures, versions, plugin validate
  evals.yml                         plugin: end-to-end evals (POC: manual run only)
  create-intent.yml                 SDLC: headless intake (Jira now; Maintain/Security/Tag later)
  intent-check.yml                  SDLC: validate + route reviewer + Jira link-back
  intent-to-spec.yml                SDLC: intent merged -> write-spec -> review-spec -> spec PR
  spec-check.yml                    SDLC: validate spec + route owner/tech lead + Jira link-back
  spec-to-stories.yml               SDLC: spec merged -> Jira stories under the Epic (no model)
plugins/sdlc/
  .claude-plugin/plugin.json
  .mcp.json                         Atlassian remote MCP (interactive use)
  hooks/hooks.json                  headless write guard + build guard (Pre), intent/spec validation (Post)
  agents/verifier.md                Build: independent check of a story (Sonnet, read and run only)
  skills/security-policy/SKILL.md   DRAFT policy rules SEC-1..8; owner must sign off
  skills/write-spec/                spec template, validate_spec.py, spec_stories.py, example
  skills/review-spec/               adversarial pre-screen + render_review.py
  skills/build-story/               build_preflight.py, plan template, validate_plan.py, example
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

## Design stage flow (headless)

```
intent merged to main
  -> intent-to-spec.yml
       -> /sdlc:write-spec mode=headless      specs/<slug>.md (stack decided here)
       -> validate_spec.py                    draft PR if invalid
       -> /sdlc:review-spec (fresh session)   findings in PR body, label review:clean|concerns|failed
       -> PR on spec/<slug>, reviewers = owner (+ tech lead when risk is high)
  -> spec-check.yml: validate (required check), route, label
  -> OWNER (+ TECH LEAD) merges (accept) or closes with reason (reject)   <- human gate
  -> spec-check.yml link-back: Jira record gets the outcome
  -> spec-to-stories.yml: one Jira story per "### S<n>:" in Work breakdown,
     under the Epic (or linked, if the record isn't an Epic); idempotent
```

The tech stack is decided in the spec's **Technology and architecture**
section: stated from the codebase for existing systems, or two or three
options with a recommendation and a decision for the tech lead for
greenfield work.

## Build stage flow (interactive, in the product repo)

Product repos opt in with `.sdlc/build.yaml` (see `bala-chimera/workout-plan-poc`).

```
/sdlc:build-story SCRUM-8
  -> build_preflight.py      Graphify: pip install graphifyy (pinned), build the code graph
                             (local tree-sitter, no tokens), wire it into Claude Code
                             (machine-specific hooks go to .claude/settings.local.json);
                             Ponytail: enable the pinned plugin, check it is active
  -> plan mode               plans/<spec-slug>-s<n>.md: files, AC-1..n -> named tests  <- human approves
  -> story/<key>-<name>      tests first, implement until green (one test file, line reporter)
  -> validate_plan.py --check-tests, full suite, graphify update
  -> sdlc:verifier           fresh context on Sonnet: PASS/FAIL per criterion
  -> PR "SCRUM-8: <title>"   story-check.yml: plan + AC traceability; CI: e2e tests
  -> owner merges            story-check.yml: Jira story -> Done, merge SHA commented
```

The **build guard** hook blocks writes to the repo's `code_paths` until the
preflight has run (graph present, Ponytail enabled and active), the branch
is the story branch, and the story's plan exists. Token savings come from
Graphify (graph queries instead of reading files), Ponytail (less code
written; about 10% cost in an independent benchmark), the verifier on a
smaller model, one test file at a time with a short reporter, denied reads
of generated folders, and one story per session. RTK was evaluated and left
out: an independent benchmark found it raised cost.

Interactive path: anyone runs `/sdlc:write-intent` (or just asks "turn
CLM-123 into an intent") in Claude Code, which opens the same kind of PR
and goes through the same checks. Given a requirement document, it first
proposes how many intents the document needs (one per distinct outcome),
then, with the Atlassian MCP connected, creates a Jira Epic for each intent
after you confirm, labelled `intent-created` so the Jira flow doesn't draft
a duplicate. Stories come later, from the accepted spec. Non-engineers can do the same in
claude.ai using the GitHub and Atlassian connectors.

## One-time setup

1. **Push and tag:** push this repo to `bala-chimera/sdlc-marketplace` and
   tag it `v0.1.0` (`.claude/settings.json` pins that tag for interactive use).
2. **GitHub App** (e.g. `sdlc-bot-bala-chimera`, webhook off): permissions
   Contents RW, Pull requests RW, Issues RW (PR labels), Metadata R (plus
   organization Members R later, for team reviewers).
   Install it on this repo. PRs opened with its token trigger
   `intent-check` (PRs opened with `GITHUB_TOKEN` would not).
3. **Actions variables and secrets** (Settings → Secrets and variables →
   Actions; never in a file):
   - Variables: `SDLC_APP_ID`, `JIRA_BASE_URL`
     (`https://chimeratechnologies-team-tk54z9ne.atlassian.net`), `JIRA_USER_EMAIL`
   - Secrets: `CLAUDE_CODE_OAUTH_TOKEN` (run `claude setup-token` with your Claude
     subscription; use an `ANTHROPIC_API_KEY` instead for shared/production use),
     `SDLC_APP_PRIVATE_KEY`, `JIRA_API_TOKEN`
4. **Branch protection on `main`:** require the `Intent check / validate`
   and `Spec check / validate` status checks. Private repos on a free GitHub plan can't enforce this;
   the checks still run. With a single owner, don't require a code-owner
   review: you can't approve your own PRs.
5. **Jira Automation rule** (per Jira space):
   - Trigger: *Field value changed*, field **Labels**, change type *Value added*
   - Condition: *Issue fields condition*, **Labels** contains any of `intent`
   - Action: *Send web request*: `POST https://api.github.com/repos/bala-chimera/sdlc-marketplace/dispatches`
     - Headers: `Authorization: Bearer <fine-grained PAT, Contents: write on this repo only>` (hidden),
       `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`
     - Body: *Custom data*: `{"event_type":"create-intent","client_payload":{"source":"jira","record_id":"{{issue.key}}"}}`
   - GitHub answers `204 No Content` on success.
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
