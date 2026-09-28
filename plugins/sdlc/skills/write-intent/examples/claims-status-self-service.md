---
id: claims-status-self-service
title: Let customers check claim status themselves
author: Priya Nair (Claims Operations, team lead)
source: jira
record_id: CLM-482
fingerprint: none
owner: "@claims-po"
owner_role: product-owner
risk: medium
systems: [claims-core, customer-portal]
created: 2026-09-28
related: []
---

# Intent: Let customers check claim status themselves

## Problem
Customers call the claims line just to ask "where is my claim?". Claims
handlers spend roughly a third of their day on these calls instead of
processing claims, and customers wait on hold for an answer that already
exists in our system.

## Proposed outcome
A customer can see the current status of their own claim, and what happens
next, without contacting a handler. Handlers get those hours back for
actual claim work.

## Affected users and systems
- Users/roles affected: external customers with an open claim, claims handlers
- Systems/services touched: claims-core API, customer portal

## Constraints
- Customers must only ever see their own claims (existing portal login).
- No new personal data is collected or stored.
- Status wording must be approved by Legal before it is shown to customers.

## Out of scope
- Uploading documents or changing a claim.
- Status for claims handled by third-party administrators.

## Evidence
- Jira CLM-482 (reporter: Priya Nair)
- Call-reason report, Q3: "claim status" is the top call reason

## Open questions
- Which internal claim states map to which customer-facing statuses?
- Should customers be notified when the status changes, or only see it on demand?

## Success looks like
"Claim status" calls drop by at least half within three months of launch,
with no rise in complaints about wrong or confusing status.
