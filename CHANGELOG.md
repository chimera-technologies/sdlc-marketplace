# Changelog

Releases of the `sdlc` plugin and its reusable workflows. Projects pin one
tag in `.sdlc/sdlc.json`; move to a newer one with
`/sdlc:init upgrade=<tag>`, then do anything listed under **Upgrading**.

## v0.20.0 (2026-10-06)

Every project now works **trunk-based** ([docs/trunk-based.md](docs/trunk-based.md)).

- **A red trunk stops the line.** The generated `sdlc-push.yml` makes
  `build` wait for the tests of the push and skip when they fail, so no new
  plan or story starts on a red base branch. `release` waits too and gets
  `trunk_green`: on a red trunk only a `rollback` record is released. The
  new `trunk` job in `sdlc-main-tests` opens a `main-red` issue when the
  tests fail on the base branch, comments on later red runs, and closes it
  when they pass again.
- **Every merge goes to staging.** `sdlc-release` has a new input,
  `staging_on_merge` (default `false`; `/sdlc:init` sets it from the new
  `.sdlc/sdlc.json` key `staging_on_merge`, default `true`). A push with no
  release record then deploys that commit to staging and smoke-tests it,
  one at a time in merge order; no tag, never production. Production still
  needs a release record and its approvers.
- **Feature flags for multi-story features.** `write-spec` names a flag
  (default off) in the rollout of any feature built over several stories;
  `build-story` puts new behaviour behind it and tests both states; the
  verifier and `review-story` flag behaviour reachable with the flag off as
  high; `release` lists each flag's state and calls out a half-built spec
  without one.
- **Short-lived branches.** `sdlc-pr` warns on a PR open longer than the
  new input `max_branch_days` (default 3). The code hooks already block
  pushes to the base branch and force pushes.
- **Releases from the trunk only**: hotfixes fix forward on the base
  branch; no release branches or cherry-picks (now stated in `release`).

**Upgrading**

1. `/sdlc:init upgrade=v0.20.0` and merge the PR. It adds
   `staging_on_merge: true` to `.sdlc/sdlc.json` and regenerates
   `sdlc-push.yml` with the trunk gates. Set `staging_on_merge` to `false`
   and re-run init if staging must not change on every merge.
2. With Deploy on and `staging_on_merge`, make sure the `staging`
   environment's `deploy_command` and `smoke_command` can run on every merge.
3. Branch protection (a repo admin): require a PR, branches up to date,
   linear history, squash merging only, and delete head branches
   ([adoption.md](docs/adoption.md)).

## v0.19.0 (2026-10-06)

- **Reusable coding patterns.** A generic catalogue,
  `skills/build-story/reference/patterns.md` (reuse first, structure, errors
  and validation, data access, UI components, state and configuration,
  testing, logging), and a project `PATTERNS.md` that `/sdlc:init` creates
  once. `build-story` reads both before planning, names what the story
  reuses, and adds each new reusable piece to `PATTERNS.md` in the same PR
  (the headless build may change it). The verifier and `review-story` flag
  second copies of existing code as medium; `REVIEW.md` lists the rule.
- **Code hooks** (`hooks/code_hooks.py`), in every repo with `.sdlc/`:
  - before a write: blocks real-looking secrets (cloud keys, tokens,
    private keys; obvious placeholders pass), hand edits of lock files, and
    writes into dependency folders;
  - before a command: blocks `terraform apply`/`destroy`, `kubectl
    apply`/`delete`, `helm install`/`upgrade`, force pushes, pushes to the
    base branch and `--no-verify`;
  - after a code write: runs `format_command`, then `lint_command`, on the
    file; lint errors go back to Claude. A linter that is not installed yet
    is skipped;
  - **Graphify stays current**: each code write marks the graph stale; it is
    updated before the next `graphify query`, `explain` or `path`, and at the
    end of each interactive turn. No preflight re-run needed.
- **Plans are validated on write**, like intents and specs.
- **UI component library.** `write-spec` names one for every spec with a UI
  (criteria and common choices in `write-spec/reference/ui-libraries.md`),
  `design-ui` draws its components, the stack records it as `ui_library`,
  and the build uses it for every standard element; a hand-built one the
  library has is a medium finding.
- **Static checks.** New `.sdlc/build.yaml` keys: `check_command` (whole
  project, run in Build, by the verifier, and in CI before the tests),
  `lint_command` and `format_command` (one `{file}`, run by the hooks), and
  `ui_library`. The setup-stack action outputs `check_command`.

**Upgrading**

1. `/sdlc:init upgrade=v0.19.0` and merge the PR. It adds `PATTERNS.md` if
   the repo has none; `REVIEW.md` and `.sdlc/build.yaml` are yours and are
   not rewritten.
2. Add to `REVIEW.md`'s "Always check" the two new rules (follows
   `PATTERNS.md`; UI from `ui_library`), as in a newly generated one.
3. Add `check_command`, `lint_command`, `format_command` and `ui_library` to
   `.sdlc/build.yaml` (or re-record the stack with `/sdlc:init
   stack=specs/<slug>.md`). Empty keys turn each feature off.
4. Fill in `PATTERNS.md` with what the codebase already does (the next
   story can do this: ask for it in the plan).

## v0.18.0 (2026-10-06)

- **A test report for every merged story.** After a story PR merges and the
  tests on main have run, the new `report` job in `sdlc-main-tests` writes
  `test-reports/<plan-id>/`: every test named for the story with its status
  in Build, the PR and main (`test-cases.md`), the result of each testing
  flow with links to the CI jobs and the runners' summary lines
  (`README.md`), and the plan review, verifier report and review gate
  (`review-findings.md`). It rebuilds the index `test-reports/README.md` and
  opens the report as a `test-report/<plan-id>` PR, labelled `test-report`.
  Other merges are skipped. New script:
  `skills/build-story/scripts/test_report.py` (standard library only).
- CI logs give counts, not test names, so each test shows the result of the
  run that included it; a test the plan names but the repo lacks shows as
  missing.

**Upgrading**

1. `/sdlc:init upgrade=v0.18.0` (or `init_project.py --upgrade v0.18.0`)
   and merge the PR. It gives the `tests` job of `sdlc-push.yml` read access
   to actions, checks, issues and pull requests, which the report needs. A
   caller left on the old permissions fails to start the `v0.18.0` tests
   workflow, so do not move `sdlc_ref` by hand.
2. Optional: add `test-reports/` to `.github/CODEOWNERS` if someone other
   than the default owner should merge the reports.

## v0.17.0 (2026-10-05)

- **The marketplace moved to `chimera-technologies/sdlc-marketplace`.** The
  generator and every reusable workflow default to it (`sdlc_repo`).
  Projects that pass `sdlc_repo` explicitly (all generated callers do)
  keep working until they upgrade.
- **sdlc-bot tokens cover only the project repo and the plugin repo.** Each
  workflow scopes its App token with `repositories:` instead of getting
  every repo the App is installed on, so an org can install the App on
  many repos without widening what one run can touch. The plugin repo
  must have the same owner as the project (already required for private
  reusable workflows).

**Upgrading**

1. The project must be in the `chimera-technologies` organization: a
   private reusable workflow can only be called from the same owner.
   Transfer a personal repo first (Settings > Transfer).
2. Install the org's sdlc-bot App on the project and on
   `sdlc-marketplace`, and set the project's `SDLC_APP_ID` and
   `SDLC_APP_PRIVATE_KEY` to that App's values.
3. Set `"sdlc_repo": "chimera-technologies/sdlc-marketplace"` in
   `.sdlc/sdlc.json`, then `/sdlc:init upgrade=v0.17.0` (or
   `init_project.py --upgrade v0.17.0`) and merge the PR. It rewrites the
   callers and the marketplace source in `.claude/settings.json`.
4. On each machine: `claude plugin marketplace remove chimera-sdlc`, then
   `claude plugin marketplace add chimera-technologies/sdlc-marketplace`.

## v0.16.3 (2026-10-03)

- **Stack proposals give a `test_file_command` that runs any test file.**
  With more than one test runner (for example Vitest and Playwright), the
  stack step proposes one project script that picks the runner
  (`npm run test:file -- {file}`) instead of a single runner's command,
  which could not run the other kind (found in skills-dashboard).
- **The first story adds the scripts the build commands need**
  (`build-story`), and `review-plan` rates a plan that leaves one missing,
  or a test file the command could not run, as `critical`.

### Upgrading

- `/sdlc:init upgrade=v0.16.3`. A stack PR opened by an earlier version can
  be refreshed: close it and merge any change, or re-run the `stack` step
  (Actions > SDLC push > Run workflow).

## v0.16.2 (2026-10-03)

- **Merging the spec accepts its recommended stack.** When the tech lead
  merged or approved a PR that changed the spec, the stack step treats the
  option the spec recommends as decided (even where it still says
  "Decision needed from: tech lead"), and the stack PR cites it ("accepted
  by @lead, spec PR #6"). Specs with no single recommendation, or accepted
  by someone else, stay undecided as before.
- **Catch-up**: while no stack is recorded, each push also takes merged
  specs that never got a stack PR, so an upgrade (or a later acceptance)
  opens the stack PR without a manual re-run.

### Upgrading

- `/sdlc:init upgrade=v0.16.2`; merging it opens the stack PR for a merged
  spec that is still waiting.

## v0.16.1 (2026-10-02)

- `sdlc-requirements.yml` also picks up every requirement document that was
  never turned into intents: one merged before the repo had this workflow
  (for example before upgrading to v0.16), or one whose run failed (for
  example on a usage limit). A document counts as done once an intent on
  the base branch or any intent PR (open, merged or closed) names it, so a
  rejected split is not redone and an open one is not duplicated. Every
  intent PR now names its document.

### Upgrading

- `/sdlc:init upgrade=v0.16.1`. Merging the upgrade turns any unprocessed
  document in `requirements/` into intent PRs.

## v0.16.0 (2026-10-02)

A requirement document starts the loop by itself.

- **New `sdlc-requirements.yml`** (push caller job `requirements`, re-run
  option `requirements`): a push that adds or changes a document in
  `requirements/` (`.md`, `.txt`, `.pdf`) runs `sdlc:write-intent
  mode=headless source=document`. It splits the document into intents
  (large ones through the `requirements-to-intents` workflow) and opens one
  intent PR per intent, for its owner, with the sections it covers, why it
  stands alone, its sibling intents and anything no intent covers. Merging
  an intent PR accepts it (Design starts); closing it rejects it; that is
  where the split is confirmed. Existing intents are never rewritten; a
  changed document only adds intents for new outcomes (fingerprint
  `req-<document>-<slug>`).
- **`/sdlc:init`** creates `requirements/`, finds documents already there
  (`--discover` lists them), asks for one when there is none, copies it in
  and commits it with the setup PR: merging the setup PR starts the loop.
- New intent `source: document`; `models.requirements` (default
  claude-opus-5-5).

### Upgrading

- `/sdlc:init upgrade=v0.16.0`, then commit a requirement document to
  `requirements/` in a PR; merging it opens the intent PRs.

## v0.15.0 (2026-10-02)

`/sdlc:init` finds what is already set up and configures itself.

- **New `init_project.py --discover`** (read-only, via `gh`): the repo and
  default branch, the latest plugin tag, the signed-in user (default
  owner), the repo's variables and secret names (never values), the Jira
  site from `JIRA_BASE_URL`, the Claude login (API key or subscription;
  on a subscription builds default to `claude-sonnet-5`), and the
  variables and secrets the setup still needs (`missing`).
- **The init skill uses it**: Jira is on whenever a site is found or the
  Atlassian MCP is connected (one Jira space = used; several = the person
  picks); it asks only what it could not find, and ends by listing what is
  still missing. Jira is never left off because a question was skipped.
- **Re-running init updates `jira.yaml`** when the Jira answer differs
  (turning Jira on, a new site or space); other `.sdlc/*` config is kept.
- Fix: `--upgrade` and `--check` read Jira from `jira.yaml` instead of
  assuming it is off.

### Upgrading

- A repo set up with Jira off by mistake: run `/sdlc:init` again (it finds
  the Jira site and space) and merge the PR. Or `/sdlc:init upgrade=v0.15.0`
  to only move the pin.

## v0.14.0 (2026-10-02)

Recording the stack is automatic: merging a spec opens the stack PR.

- **New `sdlc-spec-to-stack.yml`** (called on push, next to
  spec-to-stories): `sdlc:init mode=headless` reads the merged spec's
  Technology and architecture decision and writes a proposal with the spec
  line behind each value (`evidence`), or `decided: false` with the reason
  when the spec still says "Decision needed" (it never picks between
  options). `init_project.py --stack` validates and applies it; only when
  `.sdlc/build.yaml` or `.sdlc/deploy.yaml` changes does a stack PR
  (`sdlc/stack-<slug>`) open for the tech lead, with a value-by-value table
  and the diff. Not decided: no PR; the run summary and the spec's Jira
  record say so. Merging the stack PR starts the automatic Build.
- **`init_project.py --stack` validates** before writing (toolchains with
  presets, a test_command, `{file}` in test_file_command, relative paths,
  no `#`, valid cloud and IaC); `--dry-run` only checks.
- **Stack check on PRs** (`sdlc-spec-check.yml` job `stack`, check
  `spec-check / stack`): any PR that changes `.sdlc/build.yaml` or
  `.sdlc/deploy.yaml`, including a tech lead's hand edits in the stack PR,
  is validated as it is (`init_project.py --check-stack-files`). An
  undecided stack (all empty) passes. Add it to the required checks.
- Caller: a `stack` job and re-run option; `models.stack` (default
  claude-sonnet-5).

### Upgrading

- `/sdlc:init upgrade=v0.14.0`. `/sdlc:init stack=` still works by hand.

## v0.13.0 (2026-10-01)

Infrastructure as code, containers and Kubernetes, on whichever cloud the
architect chooses.

- **The cloud is decided in the spec**, like the stack: `write-spec`'s
  Technology and architecture section decides the cloud (AWS, Azure, GCP,
  or none), the IaC tool, containers and orchestration, environments, OIDC
  and state; `/sdlc:init stack=` records it in `.sdlc/deploy.yaml`
  (`cloud`, `iac`, `iac_dir`, `iac_var_file`, `iac_backend_config`,
  `smoke_command`). Nothing assumes a cloud the spec does not name.
- **Release** (`sdlc-release.yml`, new input `allow_destroy`): OIDC login
  per environment (`.github/actions/cloud-login`; identity in each GitHub
  environment's variables, no long-lived keys). Terraform (`iac.py`):
  staging plan and apply; the production plan runs in a reviewer-free
  `production-plan` environment with a read-only identity, is shown in the
  run, and **exactly that plan** is applied after the production approval.
  A plan that destroys or replaces anything stops the release until a
  person re-runs it with `allow_destroy`. `smoke_command` runs after each
  deploy; a staging failure means production never runs.
- **New `sdlc:infra-policy`** (INF-1..8: least privilege and OIDC, no public
  admin ports, encryption, remote locked state and no secrets in IaC,
  change safety, pinned non-root scanned images, Kubernetes workload
  hardening, the pipeline as the only path to production), applied by
  write-spec, review-spec, review-plan and review-story with SEC rules.
  Specs may cite INF rows in Security considerations.
- **Risk rubric**: IAM, network exposure, data stores, IaC state, destroy or
  replace, and the production pipeline are `high`.
- **Toolchains**: `terraform@`, `helm@`, `kubectl@` built into setup-stack.
  `init --detect` reports Terraform, Dockerfiles, Helm charts and Kubernetes
  manifests with suggested tools, checks and code paths (never a cloud).
- **Build**: never applies infrastructure (blocked commands, no cloud
  credentials); Graphify does not index `.tf`/YAML, so build-story reads
  those files directly.
- **Infrastructure stories wait for the cloud decision**: the spec marks
  them `Infrastructure: yes`; automatic Build holds them until
  `.sdlc/deploy.yaml` records a cloud, an IaC tool or a deploy_command, and
  builds the application stories meanwhile (still one story per spec in
  flight).

### Upgrading

- `/sdlc:init upgrade=v0.13.0`. The release caller now grants
  `id-token: write` and has an `allow_destroy` re-run input.
- Projects with a cloud: create the `production-plan` environment and set
  each environment's OIDC variables (see the init checklist); configure the
  cloud to trust this repo's GitHub OIDC tokens.
- `.sdlc/deploy.yaml` from earlier versions keeps working (new keys default
  to none); run `/sdlc:init stack=specs/<slug>.md` to record a cloud.

## v0.12.0 (2026-10-01)

What the plan review finds now gets fixed in the story, not just reported.

- **Must fix**: every missed edge case and every critical or high bug from
  `review-plan`. `render_plan_review.py` numbers them (`EC-n`, `BUG-n`) and
  writes `--must-fix`; the plan job then runs `build-story mode=revise`,
  which handles each in the plan and lists it under a new
  `## Review findings` section (`| ID | Finding | Handling | Test |`).
- **Enforced**: `validate_plan.py --review` fails the plan when a must-fix
  ID has no row, and `--check-tests` (the story PR's traceability check)
  fails when a finding's `S<n> EC-1` / `S<n> BUG-1` test does not exist.
  The verifier and the review gate treat an unfixed finding as high; the
  build reports PASS only when every finding is fixed.
- **Decisions**: a finding that needs a product decision is written as
  `Decision needed: ...`; the plan PR opens as a draft for the owner.
- **Low bugs** are optional: listed in the plan PR and posted as a comment
  on the Jira story.

### Upgrading

- `/sdlc:init upgrade=v0.12.0`. Nothing to configure.

## v0.11.0 (2026-10-01)

Every plan is checked for missed edge cases and potential bugs before it is
approved.

- **Plans get an `## Edge cases` section** (after Tests): each case, how it
  is handled, and the test or step that covers it. `build-story` always
  writes it, so the build implements it. The validator warns (does not fail)
  on older plans without it.
- **New `sdlc:review-plan` skill**: a fresh reviewer (never the author)
  reports missed edge cases and potential bugs rated **critical / high /
  low**, each with a concrete scenario. Large or high-risk plans use the
  review panel workflow (`review-panel.js` `kind: plan`: inputs, failures,
  correctness, regressions-security lenses; skeptics per finding).
- **Plan PRs** (`sdlc-build.yml`) show the review (`render_plan_review.py`):
  a critical bug opens the plan PR as a draft; labels
  `plan-review:clean|concerns|blocking|failed`. Interactive `build-story`
  runs the review before showing the plan.

### Upgrading

- `/sdlc:init upgrade=v0.11.0`. Nothing to configure. Plans approved before
  the upgrade keep working (the Edge cases section is optional for them).

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
