# Stages

Each stage commits one artifact that the next stage reads, and a human merge
is the approval between stages. Skills do the work; deterministic scripts and
workflows check it; hooks enforce what must always hold.

| # | Stage | Starts with | Artifact | Skill | Workflow (reusable) | Gate (check name) |
|---|---|---|---|---|---|---|
| 1 | Plan | `/sdlc:write-intent`, a Jira ticket labelled `intent`, or a Maintain breach | `intent/<slug>.md` | `write-intent` | `sdlc-intake`, `sdlc-intent-check` | owner merges (`intent-check / validate`) |
| 2 | Design: spec | automatic when an intent merges | `specs/<slug>.md` | `write-spec`, `review-spec` | `sdlc-intent-to-spec`, `sdlc-spec-check`, `sdlc-spec-to-stories` | owner (+ tech lead if risk is high) merges (`spec-check / validate`) |
| 2b | Design: UI | `/sdlc:design-ui spec=specs/<slug>.md` | `designs/<slug>/design.md` + `screens/*.png` | `design-ui` | `sdlc-design-check` | owner merges (`design-check / validate`) |
| 3 | Build | `/sdlc:build-story <KEY>` | `plans/<slug>-s<n>.md`, code, tests | `build-story`, agent `verifier` | (interactive) | plan approved in plan mode; verifier PASS |
| 4 | PR review | a story PR is opened or pushed | review comment, `review:*` label | `review-story` + advisory reviewers | `sdlc-pr` | `pr / review-gate` |
| 5 | Test | after the review gate passes | test results | (project tests) | `sdlc-pr`, `sdlc-main-tests` | `pr / traceability`, `pr / e2e`; owner merges |
| 6 | Deploy | `/sdlc:release` | `releases/<version>.md`, tag | `release` | `sdlc-release` | release PR merged; production waits for its environment's reviewers |
| 7 | Maintain | the schedule in `sdlc-maintain.yml` | new intents | `triage` | `sdlc-maintain` -> `sdlc-intake` | service owner triages the intent PR |

## How the stages connect

```
Jira ticket / document / breach
  -> Plan: intent PR --merge--> Design: spec PR (pre-screened) --merge--> Jira stories
                                   \-> UI design: design PR (screens as PNGs)
  -> Build: /sdlc:build-story (preflight, plan, tests first, verifier) -> story PR
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
- **UI design**: every spec story on a screen or listed as "No UI"; one PNG
  per screen stored in the repo; later plans must name their screens.
- **Build**: the build guard blocks code until the preflight (Graphify and
  Ponytail), the story branch and the approved plan exist; every acceptance
  criterion maps to a named test; an independent verifier on a smaller model.
- **PR review**: conformance to plan, spec, design, `REVIEW.md`, `CLAUDE.md`
  and the security policy gates the PR; advisory reviewers only comment.
- **Test**: tests run only after the review gate; the project's own test
  command from `.sdlc/build.yaml`, on its own toolchain.
- **Deploy**: a validated release record; production needs a named human
  approval (GitHub environment reviewers); rollback is a new record.
- **Maintain**: checks are plain commands in any language; breaches become
  intents, deduplicated; triage chooses rollback (runbook) or fix (story).
