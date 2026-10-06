---
name: release
description: Prepare a release, hotfix or rollback of a project (the Deploy
  stage) as a release record releases/<version>.md and a release PR; merging
  it tags the release, deploys to staging and waits for the production
  approver. Use when someone says "cut a release", "release what's merged",
  "prepare v1.2.0", "roll back to v1.1.0", or runs /sdlc:release.
argument-hint: "[version=vX.Y.Z] [type=release|hotfix] [rollback=vX.Y.Z]"
---

# Prepare a release

Goal: `releases/<version>.md` on a `release/<version>` branch and a PR. The
release is always a commit already on the base branch (trunk-based: no
release branches, no cherry-picks); the `release/<version>` branch only
carries the record. Every merge to the base branch is already on staging
(`staging_on_merge`); a release is what takes one to production. The
owner's merge approves the record; the release workflow then tags it,
creates the GitHub release, deploys to staging with the project's
`deploy_command`, and deploys to production only after the reviewers of the
production environment approve. Claude never deploys or approves.

With infrastructure (`.sdlc/deploy.yaml` `iac: terraform`, on the cloud the
spec chose): staging is planned and applied first; the production plan is
shown in the run for the approvers, and exactly that plan is applied after
approval; `smoke_command` runs after each deploy and a failure on staging
stops production. A plan that destroys or replaces anything stops the
release: say so in the record's Risks section if it is expected, and tell
the person they must re-run the release with `allow_destroy` (Actions >
SDLC push > Run workflow, rerun `release`) after reading the plan.

Files in this skill:
- Template: `${CLAUDE_SKILL_DIR}/templates/release.md`
- Validator: `${CLAUDE_SKILL_DIR}/scripts/validate_release.py`
- Example: `${CLAUDE_SKILL_DIR}/examples/v1.1.0.md`

Arguments: `$ARGUMENTS`

## Step 1: what is being released

1. `git fetch --tags`, then the latest release tag:
   `git tag --list 'v*' --sort=-v:refname | head -n1` (none = first release).
2. The base branch head: `git rev-parse origin/<base>` (from
   `.sdlc/sdlc.json`). This is the `commit` the release deploys.
3. The changes since the last tag:
   `git log --first-parent --format='%h %s' <last-tag>..origin/<base>`. Story
   merges read `Merge pull request #<n> from .../story/<key>-...` or
   `<KEY>: <title>`; match each to its plan in `plans/` (`jira: <KEY>`) for
   the story title. Include non-story merges (fixes, config) as rows with
   Jira `-`.
4. **Rollback** (`rollback=vX.Y.Z`): the commit is that tag's commit
   (`git rev-list -n1 vX.Y.Z`), type `rollback`, and Changes lists what is
   being backed out. A rollback is released even while the base branch is
   red; nothing else is (an open `main-red` issue means: fix first).
5. **Hotfix**: fix forward on the trunk. The fix is a normal story or fix PR
   merged to the base branch, then released with type `hotfix`; never patch
   a tag or keep a release branch.
6. **Feature flags**: for each spec in Changes whose rollout names a flag,
   check where it stands at this commit: its stories all merged and the
   flag turned on, or still building with the flag off. List each flag and
   its state under Risk and rollback ("`bulk_edit_enabled`: off, S3 of S5
   built"). A spec with stories still to build and **no** flag means
   half-built behaviour would reach users: say so as the first risk and
   ask the person whether to wait.

## Step 2: the version

Semver from the last tag: **major** if a spec involved changes a public API
contract or needs a data migration, **minor** for new stories, **patch** for
fixes only (type `hotfix`). Propose it with the reason and let the person
confirm or change it. A rollback gets the next patch version.

## Step 3: write and validate

Write `releases/<version>.md` from the template: frontmatter (`version`,
`previous`, full 40-character `commit`, `type`, `owner` = the service owner
in `.sdlc/owners.yaml`, `created`), then Summary (what users get, plain
words), Changes, Risk and rollback (highest spec risk, data or contract
changes, the exact rollback), Verification (the tests that passed on that
commit's main-branch run), Approvals. Validate:
`python "${CLAUDE_SKILL_DIR}/scripts/validate_release.py" --owners .sdlc/owners.yaml releases/<version>.md`

## Step 4: PR and Jira

1. `git checkout -b release/<version>`, add only the release file, commit
   `release: <version>`, push, open a PR `release: <version>` requesting the
   owner (with `gh`, or the compare link).
2. If the Atlassian MCP is connected, comment the PR link on each story in
   Changes. The release workflow comments again when production is done.
3. Tell the person: merging the PR starts the release; production waits for
   the production environment's reviewers in the Actions run.
