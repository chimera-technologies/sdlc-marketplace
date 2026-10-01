# Changelog

Releases of the `sdlc` plugin and its reusable workflows. Projects pin one
tag in `.sdlc/sdlc.json`; move to a newer one with
`/sdlc:init upgrade=<tag>`, then do anything listed under **Upgrading**.

## v0.10.0 (2026-10-01)

Big jobs run as Claude Code workflows (the Workflow tool): parallel agents,
then adversarial checks.

- **`requirements-to-intents.js`** (`write-intent`, large documents): one
  reader per document section extracts outcomes and requirements; they are
  grouped into intents (the person confirms the split); one writer per
  intent; two skeptics per draft (faithful to the document, follows the
  skill rules) and a fix pass; a completeness critic lists requirements no
  intent covers.
- **`review-panel.js`** (`review-spec`, `review-story`, large or high-risk):
  four reviewers in parallel, one per lens; every high and medium finding
  must survive two skeptics trying to refute it (a tie refutes); duplicates
  merged; same JSON output as before, so the gates are unchanged.
- **When**: `plugins/sdlc/reference/workflows.md` sets the thresholds;
  `.sdlc/sdlc.json` `workflows: auto | always | off` (default `auto`).
  Below the threshold, or where the Workflow tool is unavailable, the skill
  works in one session as before.
- CI: the `review-spec` and `review-story` steps may use the Workflow tool
  (it runs in headless `claude -p`).

### Upgrading

- `/sdlc:init upgrade=v0.10.0` adds `"workflows": "auto"` to
  `.sdlc/sdlc.json`. Set `"off"` to keep single sessions everywhere.
- Expect higher cost on large PRs and specs (several agents instead of one).

## v0.9.2 (2026-10-01)

- Automatic Build: the preflight no longer runs Graphify's Claude Code
  integration in headless CI runs (`SDLC_HEADLESS=1`). It added a section
  to `CLAUDE.md` on every build; CI reverted it before the PR, but the
  verifier flagged it on every story (S1, S4 in the sandbox). The graph is
  still built; interactive sessions still get the integration.

## v0.9.1 (2026-10-01)

- Automatic Build keeps the Jira story in step (new `jira_story.py`,
  called by `sdlc-build.yml`): a comment with the plan PR link; **In
  Progress** and a comment when the build starts; when the story PR opens,
  a comment with its link and result, and **In Review** if the workflow has
  a status named like "review" (an incomplete, draft build stays In
  Progress). Done on merge is unchanged (`sdlc-story-link.yml`).
  Transitions are picked by status category, a story never moves
  backwards, and Jira errors never fail the build.

### Upgrading

- `/sdlc:init upgrade=v0.9.1`. Nothing to configure; stories without a Jira
  key (Jira off) are skipped.

## v0.9.0 (2026-10-01)

Every accepted spec gets a Jira Epic and its stories, with or without a
Jira ticket behind the intent.

- `sdlc-spec-to-stories.yml` / `spec_stories.py --jira-config .sdlc/jira.yaml`:
  a merged spec whose `record_id` is `none` (an intent from a document, a
  conversation without the Atlassian MCP, or a Maintain breach) now gets
  its Epic created in `space_key` (type `epic_issue_type`, labels
  `from-spec`, `spec-<slug>`, `created_label`), then one Story per `S<n>`
  under it (type `story_issue_type`). Re-runs find the Epic by its label.
  Before, such specs were skipped and had no Jira records at all.
- Intents with a Jira record are unchanged (stories under that Epic, or
  linked to a non-Epic ticket).
- Projects with Jira off: no change.

### Upgrading

- `/sdlc:init upgrade=v0.9.0`. Nothing to configure: it uses the
  `space_key` already in `.sdlc/jira.yaml`. To backfill a spec merged
  earlier without a record: Actions > SDLC push > Run workflow, `rerun`
  `spec-to-stories`, `file` `specs/<slug>.md`.

## v0.8.2 (2026-10-01)

- PR review: the advisory reviewers (`anthropics/claude-code-action`) now
  run on story PRs opened by automatic Build. The action refuses PRs from
  bots unless allowed; `sdlc-pr.yml` allows exactly the sdlc-bot App
  (`allowed_bots` = the App's slug), no other bot.

## v0.8.1 (2026-09-30)

- The Build preflight no longer fails on a first story: when none of
  `.sdlc/build.yaml`'s `code_paths` holds a file yet, it warns, skips the
  Graphify graph, and leaves `graphify-out/NO-CODE-YET`, which the build
  guard accepts in place of the graph. The next preflight (build-story
  re-runs it after implementing) builds the real graph and removes the
  marker.

### Upgrading

- `/sdlc:init upgrade=v0.8.1`. A first story that stopped at the preflight
  can then be re-run as it was (`/sdlc:build-story S1`, or re-run the
  automatic Build: Actions > SDLC push > rerun `build`).

## v0.8.0 (2026-09-30)

Build is now automatic, one story at a time, with a plan PR before any code.

- **New `sdlc-build.yml`** (called on every push to the base branch):
  `next_story.py` finds each spec's first unfinished story from git and the
  PR list. No plan yet: `sdlc:build-story mode=plan` writes the plan and it
  opens as a PR on `plan/<slug>-s<n>`; merging it approves the plan. Plan
  merged: `mode=build` follows it in CI (preflight with Graphify and a
  pinned Ponytail, tests first, verifier) and opens the story PR (a draft
  when incomplete). Merging the story PR starts the next story. A closed
  plan or story PR stops that spec; nothing starts before the stack is
  recorded; a story PR open without a plan pauses it (manual build).
- **Guarded**: the build writes anywhere except the SDLC's own files
  (`SDLC_WRITE_DENY` in the headless write guard; changes there are also
  reverted before the PR); checkouts keep no credentials; no `git push`,
  `gh` or `curl` for Claude; dependency and build output never committed.
- **Build without Jira**: stories use `story/<spec-slug>-s<n>` and
  `jira: none`; the build guard and traceability find a plan by its
  `branch:` (older plans still by Jira key).
- `.sdlc/sdlc.json`: new `auto_build` (default `true`) and `models.build`.
  `setup-stack`: new `install-if-code` input.

### Upgrading

- Run `/sdlc:init upgrade=v0.8.0`: `sdlc-push.yml` gains the `build` job.
  **Automatic Build is on by default**: after the upgrade merges, the next
  push plans the first unfinished story of every spec. To keep building by
  hand, set `"auto_build": false` in `.sdlc/sdlc.json` before upgrading.
- Stories already built by hand count as done when a PR from their plan's
  `branch:` has merged.

## v0.7.0 (2026-09-30)

UI design is now automatic: every spec PR comes with mockups of its screens.

- **Design workflow** (`sdlc-intent-to-spec.yml`, new input `ui_design`,
  default `false`): after the spec, `sdlc:design-ui` runs headless and
  writes one static HTML mockup per screen plus `designs/<slug>/design.md`;
  `render_mockups.py` renders each to PNG with the runner's headless Chrome
  (scripts and network blocked); the design is validated and added to the
  spec PR, with the screens shown in the PR body. A design that fails is
  left out (kept as a run artifact), so the spec PR is never blocked.
- **design-ui skill**: `to=mockup` (headless and interactive),
  `from=mockups` to import the mockups into Figma for a designer, and the
  existing `to=figma` / `from=live`. Figma cannot be driven from CI (its MCP
  server takes only a person's OAuth login), so Figma stays interactive.
- **Design manifest**: new `source: mockup | figma` key (default `figma`,
  so existing designs stay valid); the Screens table's second column is now
  `Source` (a Figma node id, or `mockups/<screen>.html`). Mockups must be
  self-contained: no scripts, event handlers, frames or remote URLs.
- New `render_mockups.py`, `templates/mockup.html` and a mockup example.

### Upgrading

- Run `/sdlc:init upgrade=v0.7.0`: the regenerated `sdlc-push.yml` passes
  `ui_design: true` to the Design stage when UI design is on.
- Specs merged before the upgrade have no mockups: run
  `/sdlc:design-ui spec=specs/<slug>.md to=mockup` and open a design PR.

## v0.6.3 (2026-09-30)

- The Test stage also skips (with a notice) while none of `.sdlc/build.yaml`'s
  `code_paths` exist, so recording the stack before the first story
  scaffolds the project no longer fails the stack PR or `main` (for example
  `npm ci` with no `package.json`). New `setup-stack` input
  `skip-without-code`. Story PRs still always install and test.

## v0.6.2 (2026-09-30)

- A project whose stack is still "decided by the spec" no longer fails the
  Test stage: `sdlc-pr.yml` (`e2e`) and `sdlc-main-tests.yml` skip the tests
  with a notice while `.sdlc/build.yaml` has no `test_command`. Story PRs
  still require one.

## v0.6.1 (2026-09-30)

- `init_project.py` and `build_preflight.py` run on Python 3.9 again
  (they used `Path.write_text(newline=)`, which needs 3.10).
- Reusable workflows: shellcheck findings fixed.

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
