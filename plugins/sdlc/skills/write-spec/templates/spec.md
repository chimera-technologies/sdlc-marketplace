---
id: <same slug as the intent>
title: <short title of the change>
intent: intent/<slug>.md
record_id: <the intent's record_id: Jira Epic/ticket key, or none>
owner: "<@github-handle or @org/team: the intent's owner>"
tech_lead: "<@github-handle or @org/team, required when risk is high>"
risk: <low | medium | high>
systems: [<system-1>, <system-2>]
created: <YYYY-MM-DD>
---

# Spec: <short title>

## Summary
<Three to six sentences: what will change, for whom, and how we will know
it worked. Link the intent's outcome to this design.>

## Context
<What exists today that this builds on: the codebase, services, data and
owners you actually found. Say plainly what you could not find.>

## Requirements
| ID | Requirement | Verification |
|---|---|---|
| REQ-1 | <one testable requirement> | <how it is checked> |

## Technology and architecture
<Existing codebase: state the stack in use and what this change touches.
Greenfield: two or three options with trade-offs, a recommendation, and
"Decision needed from: tech lead". Use approved standards if a standards
skill exists; anything outside them goes under Areas of concern.>

## Design
<How it works: components, data flow, interfaces, rollout and rollback.
Enough for an engineer to plan the build, not the code itself.>

## Security considerations
| Rule | Applies? | How this design satisfies it |
|---|---|---|
| SEC-<n> | <Yes / No / Conditional> | <how, or why not applicable> |

## Open questions
| ID | Source | Question | Status | Answer or next step | Who |
|---|---|---|---|---|---|
| OQ-1 | intent | <question copied from the intent> | <answered / carried forward / open> | <answer, or what is needed> | <@owner> |

## Areas of concern
<Policy conflicts, risks and decisions needed, each with options, a
recommendation and "Decision needed from: <owner>". Write "None." if none.>

## Work breakdown
<One story per independently buildable, testable piece. These become Jira
stories under the intent's Epic when this spec is merged.>

### S1: <story title>
<One or two sentences: what it delivers and for whom.>

Acceptance criteria:
- <observable, testable criterion>

## Out of scope
<What this spec explicitly does not cover.>
