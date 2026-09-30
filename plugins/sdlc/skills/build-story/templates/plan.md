---
id: <spec-slug>-s<n>
spec: specs/<spec-slug>.md
story: S<n>
jira: <JIRA-KEY, e.g. ABC-123, or none without Jira>
branch: <story/<jira-key-lowercase>-<short-name>, or story/<spec-slug>-s<n> without Jira>
created: <YYYY-MM-DD>
---

# Plan: S<n> <story title>

## Story
<One or two sentences from the spec: what this story delivers and for whom.
Name the requirements it covers (REQ-n).>

## Design
<Only when designs/<spec-slug>/design.md has screens for this story (then it
is required): each screen id, what the story must match on it, and the
tokens to use. Delete this section otherwise.>
- <screen-id>: designs/<spec-slug>/screens/<screen-id>.png

## Files
| File | Change |
|---|---|
| <path> | <new / changed: what and why, in a few words> |

## Tests
| AC | Acceptance criterion | Test |
|---|---|---|
| AC-1 | <first acceptance criterion, copied from the spec> | <test file under test_paths> › "S<n> AC-1: <name>" |

## Steps
1. <Write the failing tests for AC-1..n.>
2. <Implement in the smallest steps that turn them green.>

## Risks and rollback
<What could go wrong and how to undo it. "None beyond reverting the PR." is fine.>

## Out of scope
<What this story deliberately leaves to other stories or intents.>
