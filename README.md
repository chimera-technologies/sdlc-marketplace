# sdlc-marketplace

A Claude Code plugin marketplace (`chimera-sdlc`) with one plugin, `sdlc`,
that runs an AI-native software lifecycle in any project and any tech stack:
Plan, Design (spec and UI), Build, PR review, Test, Deploy and Maintain. Each
stage commits an artifact the next stage reads; a human merge approves every
step; hooks and deterministic checks enforce what must always hold.

Adopt it in a project in one command, **`/sdlc:init`**, then follow
[docs/adoption.md](docs/adoption.md).

## Stages

| Stage | Start it with | You get | Approved by |
|---|---|---|---|
| Plan | `/sdlc:write-intent`, or label a Jira ticket `intent` | `intent/<slug>.md` (+ a Jira Epic) | the owner merging the intent PR |
| Design | automatic when an intent merges | `specs/<slug>.md`: requirements, **stack decision**, stories; pre-screened by an adversarial reviewer | owner (+ tech lead for high risk); stories then appear in Jira |
| UI design | automatic with the spec; `/sdlc:design-ui from=mockups` to refine in Figma | HTML mockups and a PNG of each screen in `designs/<slug>/` | owner merging the spec PR (or a design PR) |
| Build | `/sdlc:build-story <KEY>` | plan, tests first, code, independent verifier | plan approved in plan mode |
| PR review | opening the story PR | conformance review gate + Anthropic `code-review` (+ your own reviewers) | the gate, then the owner |
| Test | after the review gate | your project's tests, on your toolchain | green checks |
| Deploy | `/sdlc:release` | release record, tag, staging, production | the production environment's reviewers |
| Maintain | scheduled checks | breaches become intents | the service owner |

Details: [docs/stages.md](docs/stages.md). Configuration:
[docs/configuration.md](docs/configuration.md).

## Any tech stack

Nothing is tied to a language. The spec's tech lead decides the stack;
`/sdlc:init stack=specs/<slug>.md` records it in `.sdlc/build.yaml`
(`toolchains: [java@21]`, `test_command: mvn -B test`, ...). CI installs it
with the `setup-stack` action (Node, Python, Java, .NET, Go built in; any
other toolchain through `setup_command`) and runs the project's own commands.
Test names follow `S<n> AC-<k>` in each language's style.

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
  skills/        init, write-intent, write-spec, review-spec, design-ui, build-story,
                 review-story, release, triage, security-policy
                 (each: SKILL.md + templates/, scripts/, examples/, reference/)
  agents/        verifier (Build)
  hooks/         headless write guard, build guard, intent/spec validation on write
.github/workflows/
  sdlc-*.yml     reusable workflows the projects call
  ci.yml         plugin tests, example validation, actionlint, plugin validate
  evals.yml      end-to-end evals of the skills (manual for now)
.github/actions/setup-stack/        installs a project's declared toolchains
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
  (with **Upgrading** steps if projects must act), tag `v<version>`, push the
  tag. Projects upgrade with `/sdlc:init upgrade=v<version>`.

The worked POC (a workout app taken from a requirement document through
every stage) is in [docs/examples/poc/](docs/examples/poc/) and the
`bala-chimera/workout-plan-poc` repo. The original architecture is
[docs/architecture.html](docs/architecture.html).
