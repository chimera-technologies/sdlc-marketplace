# Changelog

Releases of the `sdlc` plugin and its reusable workflows. Projects pin one
tag in `.sdlc/sdlc.json`; move to a newer one with
`/sdlc:init upgrade=<tag>`, then do anything listed under **Upgrading**.

## v0.6.0 (2026-09-30)

The marketplace becomes a boilerplate for any project and any tech stack.

- **Onboarding**: new `sdlc:init` skill and `init_project.py` write a
  project's `.sdlc/` config, `REVIEW.md`, a `CLAUDE.md` block, plugin pins
  and four caller workflows; `--check`, `--upgrade`, `--detect`, `--stack`.
- **Reusable workflows**: the whole loop runs from
  `.github/workflows/sdlc-*.yml` (`workflow_call`), pinned by tag;
  projects no longer copy workflow files.
- **Any stack**: `.github/actions/setup-stack` installs the toolchains in the
  project's `.sdlc/build.yaml` (Node, Python, Java, .NET, Go; others via
  `setup_command`) and runs its own test commands. Test names match
  `S<n> AC-<k>` in any language's style; test paths are configurable.
- **Deploy**: new `sdlc:release` skill, release records in `releases/`,
  `sdlc-release.yml` (tag, GitHub release, staging, production behind the
  environment's reviewers, Jira comments).
- **Maintain**: new `sdlc:triage` skill, `.sdlc/maintain.json` checks,
  `sdlc-maintain.yml` (breaches become intents via the intake).
- Plans older than their design only warn about missing screen references.
- Removed project-specific values from the skills; POC artifacts moved to
  `docs/examples/poc/`; new `docs/adoption.md`, `stages.md`,
  `configuration.md`.

**Upgrading from v0.5.x** (projects that copied workflows):
1. Run `/sdlc:init` in the project; it keeps your `.sdlc/*` files and adds
   `sdlc.json`, `deploy.yaml`, `maintain.json` and the callers.
2. Delete the copied `pr.yml`, `design-check.yml`, `story-check.yml`,
   `ci.yml`; the callers replace them.
3. Record the stack: `/sdlc:init stack=specs/<slug>.md` (or `--detect`).
4. Allow the marketplace's Actions **Access** for your repos, and point the
   Jira Automation URL at the project repo's `/dispatches`.
5. Branch protection check names are now `pr / review-gate`,
   `pr / traceability`, `pr / e2e`, `design-check / validate`,
   `intent-check / validate`, `spec-check / validate`.

## v0.5.0 (2026-09-29)

- **UI design** sub-stage: `sdlc:design-ui` builds screens in Figma (official
  Figma plugin) and stores a PNG per screen in `designs/<slug>/screens/`;
  `validate_design.py`, `export_screens.py` (Figma REST, `FIGMA_TOKEN`).
- A story that appears on a screen must name it in its plan's `## Design`.
- **PR review** stage before Test: `sdlc:review-story` conformance gate
  (fails on `high`) plus advisory reviewers (`code-review` plugin) from
  `.sdlc/review.json`; `REVIEW.md` tunes it.

## v0.4.0 (2026-09-29)

- **Build** stage: `sdlc:build-story` (preflight, plan mode, tests first,
  verifier, story PR), `validate_plan.py`, the `verifier` subagent.
- Build preflight installs and wires up **Graphify** and **Ponytail**; the
  **build guard** hook blocks code until they, the story branch and the plan
  exist.

## v0.3.1 (2026-09-29)

- Validators ignore HTML inside code spans and blocks when looking for
  template placeholders.

## v0.3.0 (2026-09-29)

- **Design** stage: `sdlc:write-spec` (stack decision, stories),
  `sdlc:review-spec` adversarial pre-screen, spec PR gate, Jira stories
  created from a merged spec.

## v0.2.1 (2026-09-29)

- `systems: [unknown]` instead of invented component names.

## v0.2.0 (2026-09-28)

- `sdlc:write-intent` splits a requirement document into intents and
  creates a Jira Epic per intent (after confirmation).
- Headless runs use the Claude CLI directly and a Claude subscription token.

## v0.1.0 (2026-09-28)

- **Plan** stage: `sdlc:write-intent`, intent validator, headless intake from
  Jira, intent check and Jira link-back, guardrail hooks, evals.
