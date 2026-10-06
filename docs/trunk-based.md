# Trunk-based delivery

Every project that uses the sdlc plugin works trunk-based: one base branch
(the trunk, `base_branch` in `.sdlc/sdlc.json`, usually `main`) that is
always releasable, short-lived branches that merge into it, and releases
tagged from it. This page lists the rules and what enforces each one.

## The rules

| Rule | How the loop keeps it |
|---|---|
| **One trunk; everything reaches it through a reviewed PR** | Every artifact has its own short branch and PR (`intent/`, `spec/`, `plan/`, `story/`, `release/`, `test-report/`); the code hooks block `git push` to the base branch and force pushes; branch protection requires a PR |
| **Branches live hours or a day or two** | One story per PR, one story per spec in flight; plans keep stories small; `sdlc-pr` warns on a PR open longer than `max_branch_days` (default 3) |
| **The trunk is always releasable** | Review gate, traceability and tests are required before merge; branches must be up to date with the trunk |
| **Unfinished features are merged, but hidden** | The spec's rollout names a feature flag (default off) for any feature built over several stories; `build-story` puts new behaviour behind it and tests both states; the verifier and review gate flag behaviour reachable with the flag off; only the story the spec names turns it on |
| **Every merge goes to staging** | With Deploy on, `sdlc-release` deploys each merge to staging and smoke-tests it (`staging_on_merge`), one at a time, in merge order; no tag, never production |
| **Production releases tag a commit on the trunk** | `/sdlc:release` writes a record for a commit on the trunk; the workflow refuses a commit that is not on it; there are no release branches and no cherry-picks |
| **Fix forward** | A hotfix is a normal fix PR merged to the trunk, then released as type `hotfix`; a bad release is undone by a `rollback` release of an earlier tag |
| **A red trunk stops the line** | When the tests fail on the trunk, Build starts no new plan or story, nothing deploys or releases (except a rollback), and the bot opens a `main-red` issue; it closes the issue when the tests pass again |

## The flow

```
story branch (hours to 2 days) --PR: review gate, traceability, tests--> trunk
    trunk --every merge--> tests on trunk --green--> staging (deploy + smoke test)
                                          \--red--> main-red issue; Build and Deploy held
    trunk commit --/sdlc:release record PR--> tag --> staging --> production (approved)
```

## Feature flags

Write them into the spec, not into the build:

- **Name and default.** `<feature>_enabled`, default off, read through the
  project's one flag helper (recorded in `PATTERNS.md`). Configuration or
  environment based; no flag vendor is required.
- **Stories.** The spec's rollout says which stories put behaviour behind
  the flag and which one turns it on (usually the last).
- **Tests.** Each flagged story tests both states: off keeps today's
  behaviour, on is the new one.
- **Releases.** The release record lists each flag and its state. A spec
  with stories still to build and no flag is called out as the first risk.
- **Clean-up.** Once the flag is on in production, a follow-up story removes
  it and the old path. Flags are temporary.

## Settings

| Where | Setting | Default |
|---|---|---|
| `.sdlc/sdlc.json` | `staging_on_merge` | `true` (used when the Deploy stage is on) |
| `sdlc-pr.yml` input | `max_branch_days` | `3` (`0` turns the warning off) |
| GitHub branch protection | require a PR, required checks, branches up to date, linear history, squash merging only, delete head branches | set by a repo admin (see [adoption.md](adoption.md)) |
