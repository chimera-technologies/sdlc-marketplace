---
version: <vMAJOR.MINOR.PATCH>
previous: <the previous release tag, or none>
commit: <full sha on the base branch that this release deploys>
type: <release | hotfix | rollback>
owner: "<@release-manager: the service owner in .sdlc/owners.yaml>"
created: <YYYY-MM-DD>
---

# Release: <vMAJOR.MINOR.PATCH>

## Summary
<Two or three sentences: what users get in this release, in plain words.>

## Changes
| Jira | Story | PR |
|---|---|---|
| <ABC-123 or -> | <S<n> title, from the plan> | <#12> |

## Risk and rollback
<The highest risk among the specs involved, anything that changes data or
contracts, and exactly how to roll back (the previous tag to redeploy, or
the runbook in runbooks/).>

## Verification
<The tests that passed on this commit (the main-branch run), and anything
checked by hand.>

## Approvals
<Who approves production: the reviewers of the production environment. The
merge of this PR approves the release record; production waits for them.>
