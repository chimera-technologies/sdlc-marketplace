# Stages

Each stage commits one artifact that the next stage reads, and a human merge
is the approval between stages. Skills do the work; deterministic scripts and
workflows check it; hooks enforce what must always hold.

| # | Stage | Starts with | Artifact | Skill | Workflow (reusable) | Gate (check name) |
|---|---|---|---|---|---|---|
| 1 | Plan | `/sdlc:write-intent`, a Jira ticket labelled `intent`, or a Maintain breach | `intent/<slug>.md` | `write-intent` | `sdlc-intake`, `sdlc-intent-check` | owner merges (`intent-check / validate`) |
| 2 | Design: spec | automatic when an intent merges | `specs/<slug>.md` | `write-spec`, `review-spec` | `sdlc-intent-to-spec`, `sdlc-spec-check`, `sdlc-spec-to-stories` | owner (+ tech lead if risk is high) merges (`spec-check / validate`) |
| 2b | Design: UI | automatic with the spec (HTML mockups); `/sdlc:design-ui` to redo them or refine them in Figma | `designs/<slug>/design.md` + `mockups/*.html` + `screens/*.png` | `design-ui` | `sdlc-intent-to-spec`, `sdlc-design-check` | owner merges the spec PR, or a design PR (`design-check / validate`) |
| 3 | Build | automatic, one story at a time: a plan PR, then the build when it merges; or `/sdlc:build-story <KEY>` by hand | `plans/<slug>-s<n>.md` (plan PR), then code and tests (story PR) | `build-story`, agent `verifier` | `sdlc-build` | owner merges the plan PR; verifier PASS |
| 4 | PR review | a story PR is opened or pushed | review comment, `review:*` label | `review-story` + advisory reviewers | `sdlc-pr` | `pr / review-gate` |
| 5 | Test | after the review gate passes | test results | (project tests) | `sdlc-pr`, `sdlc-main-tests` | `pr / traceability`, `pr / e2e`; owner merges |
| 6 | Deploy | `/sdlc:release` | `releases/<version>.md`, tag | `release` | `sdlc-release` | release PR merged; production waits for its environment's reviewers |
| 7 | Maintain | the schedule in `sdlc-maintain.yml` | new intents | `triage` | `sdlc-maintain` -> `sdlc-intake` | service owner triages the intent PR |

## How the stages connect

```
Jira ticket / document / breach
  -> Plan: intent PR --merge--> Design: spec PR (pre-screened, with UI mockups) --merge--> Jira stories
                                   \-> optional: /sdlc:design-ui from=mockups -> Figma -> design PR
  -> Build (per story, in order): plan PR --merge--> build in CI (preflight, tests first, verifier) -> story PR
     (story PR merged -> the next story's plan PR)
  -> PR review: review-gate (+ advisory) -> Test: traceability + tests -> merge -> Jira story Done
  -> Deploy: /sdlc:release -> release PR --merge--> tag -> staging -> production (approved)
  -> Maintain: scheduled checks -> breach -> intake -> Plan
```

## What each stage guarantees

- **Plan**: `validate_intent.py` (structure, owner, record, no placeholders);
  duplicates skipped by Jira key or fingerprint; Jira gets the PR link and the
  outcome. Headless runs can write only `intent/` (hook).
- **Design**: every intent open question carried into the spec; the stack
  decided in "Technology and architecture"; an adversarial pre-screen in a
  fresh session; stories created only from a merged, valid spec.
- **UI design**: made with every spec, no accounts needed: one static HTML
  mockup per screen, rendered to PNG by headless Chrome with scripts and
  network blocked. Every spec story on a screen or listed as "No UI"; one
  PNG per screen stored in the repo; later plans must name their screens. A
  design that fails validation is left out of the spec PR, never blocks it.
  Figma is optional: `/sdlc:design-ui from=mockups` imports the mockups for a
  designer, and the design PR replaces the PNGs with Figma exports. (CI
  cannot drive Figma: its MCP server accepts only a person's OAuth login.)
- **Build**: the build guard blocks code until the preflight (Graphify and
  Ponytail), the story branch and the approved plan exist; every acceptance
  criterion maps to a named test; an independent verifier on a smaller model.
  Automatic (`auto_build`, default on): after every merge, `next_story.py`
  finds each spec's first unfinished story from git and the PR list alone.
  No plan yet -> a plan PR (merging it is the plan approval); plan merged ->
  the build runs in CI and opens the story PR (a draft if incomplete);
  story PR merged -> the next story. One story per spec in flight; a closed
  plan or story PR stops that spec until someone re-runs it. Nothing starts
  until `.sdlc/build.yaml` has a `test_command`. The build may not change
  `.github/`, `.sdlc/`, `specs/`, `plans/` or other SDLC files (hook, and
  reverted before the PR). Works with or without Jira (branches
  `story/<jira-key>-<name>` or `story/<spec-slug>-s<n>`).
- **PR review**: conformance to plan, spec, design, `REVIEW.md`, `CLAUDE.md`
  and the security policy gates the PR; advisory reviewers only comment.
- **Test**: tests run only after the review gate; the project's own test
  command from `.sdlc/build.yaml`, on its own toolchain.
- **Deploy**: a validated release record; production needs a named human
  approval (GitHub environment reviewers); rollback is a new record.
- **Maintain**: checks are plain commands in any language; breaches become
  intents, deduplicated; triage chooses rollback (runbook) or fix (story).
