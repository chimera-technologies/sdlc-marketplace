---
id: <short-slug>
title: <short title>
author: <name> (<team/role>)
source: <human | jira | maintain | claude-security | claude-tag | document>
record_id: <JIRA-KEY, e.g. CLM-123, or none>
fingerprint: <dedup key from a headless source, or none>
owner: "<@github-handle or @org/team of the approver>"
owner_role: <product-owner | service-owner>
risk: <low | medium | high>
systems: [<system-1>, <system-2>]
created: <YYYY-MM-DD>
related: []
---

# Intent: <short title>

## Problem
<What can't the user/team do today? Who is affected? Use their words, not
solution language. 2-5 sentences.>

## Proposed outcome
<What does "better" look like? Describe the outcome, not the implementation.
Avoid naming specific technologies or UI unless that's the actual ask.>

## Affected users and systems
- Users/roles affected: <e.g. claims handlers, external customers>
- Systems/services touched: <e.g. claims-core API, portal>

## Constraints
<Anything the solution must respect: compliance, data handling, budget,
timeline, existing auth, no new PII, etc. List as bullets.>
- <constraint 1>

## Out of scope
<What this intent explicitly does NOT cover, to prevent scope creep in
Design. Write "None stated." if the author has nothing to add.>

## Evidence
<Links that back the problem: Jira ticket, incident, breach log, scan
finding, dashboard, customer quote. Required when source is not "human";
write "None." otherwise.>

## Open questions
<Anything unresolved that Design/engineering needs to answer or flag back.
In headless mode, every gap the source could not answer goes here.>
- <question 1>

## Success looks like
<How would the author know this worked, in one or two sentences. Ideally
measurable, but qualitative is fine at this stage.>
