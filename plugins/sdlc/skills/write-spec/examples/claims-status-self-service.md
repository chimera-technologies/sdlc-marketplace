---
id: claims-status-self-service
title: Let customers check claim status themselves
intent: intent/claims-status-self-service.md
record_id: CLM-482
owner: "@claims-po"
tech_lead: "@claims-tech-lead"
risk: medium
systems: [claims-core, customer-portal]
created: 2026-09-29
---

# Spec: Let customers check claim status themselves

## Summary
Signed-in customers get a claim status page in the customer portal showing
the current customer-facing status of each of their open claims and what
happens next. The portal reads status from a new read-only claims-core
endpoint that maps internal claim states to a small set of Legal-approved
customer statuses. Success is measured by "claim status" calls to the claims
line, which the intent expects to halve within three months.

## Context
- claims-core already exposes claim data to internal tools over its REST
  API; there is no customer-facing endpoint today.
- The customer portal already signs customers in through the company
  identity provider and knows the customer ID of the signed-in user.
- The internal claim state list lives in claims-core; nothing maps it to
  customer wording yet (intent open question 1).

## Requirements
| ID | Requirement | Verification |
|---|---|---|
| REQ-1 | A signed-in customer sees every open claim they hold, and only those. | Automated test: customer A cannot see customer B's claim by any route. |
| REQ-2 | Each claim shows one Legal-approved status and a one-line "what happens next". | Wording table signed off by Legal; UI test per status. |
| REQ-3 | Status is no more than 15 minutes out of date. | Integration test against a changed claim. |
| REQ-4 | No new personal data is collected or stored. | Data review in the Build PR. |

## Technology and architecture
Existing stack, no new technology:
- claims-core: its existing service and database; add one read-only
  endpoint `GET /customers/{customerId}/claims/status`.
- customer-portal: its existing web front end and back end; add one page
  and one server-side call to claims-core.
- Authentication: the existing portal sign-in and the existing
  service-to-service credentials between portal and claims-core.
No caching layer is added (see Areas of concern).
- **Data store:** claims-core's existing database; the portal stores nothing new
- **Migrations:** claims-core's existing migration tool; one new migration
  adds the status mapping table (S2), and changes no existing table
- **Test database:** claims-core's existing test database setup
- **Test data:** each test creates its customers and claims; the mapping
  table is reference data, seeded by its migration
- **Run locally:** unchanged; claims-core's existing local setup

## Design
1. The portal back end takes the customer ID from the signed-in session,
   never from the request, and calls the new claims-core endpoint.
2. claims-core returns only claims owned by that customer, each with its
   customer status code, not the internal state.
3. A mapping table in claims-core converts internal states to customer
   status codes; the portal holds the Legal-approved wording for each code.
4. The page lists claims newest first. Claims run by third-party
   administrators are excluded (out of scope in the intent).
5. Rollout behind a portal feature flag, first to staff test accounts,
   then to all customers. Rollback is switching the flag off.

## Security considerations
| Rule | Applies? | How this design satisfies it |
|---|---|---|
| SEC-1.1 | Yes | Uses the existing portal sign-in; no new login or token mechanism. |
| SEC-1.2 | Yes | claims-core filters by the session's customer ID on the server; REQ-1 test covers cross-customer access. |
| SEC-1.3 | Yes | Existing short-lived, scoped portal-to-claims-core credentials. |
| SEC-2.1 | Yes | Returns claim ID, customer status code and next step only; no free-text notes or handler details. |
| SEC-2.3 | Yes | Logs record claim ID and status code, never names or claim content. |
| SEC-6.1 | Yes | Each status view is logged as access to personal data, with customer ID and time. |

## Open questions
| ID | Source | Question | Status | Answer or next step | Who |
|---|---|---|---|---|---|
| OQ-1 | intent | Which internal claim states map to which customer-facing statuses? | open | Claims Operations drafts the mapping table; Legal approves the wording. Blocks S2. | @claims-po |
| OQ-2 | intent | Should customers be notified when the status changes, or only see it on demand? | answered | On demand only for this release; notifications would add contact data handling and become their own intent. | @claims-po |

## Areas of concern
- **Legal sign-off is on the critical path.** No status can be shown until
  Legal approves the wording (intent constraint). Options: start S1 and S3
  in parallel with the Legal review, or wait. Recommendation: parallel.
  Decision needed from: @claims-po.

## Work breakdown

### S1: Customer claim status endpoint in claims-core
Read-only endpoint returning a customer's open claims with customer status
codes, filtered on the server by the authenticated customer ID.

Acceptance criteria:
- Returns only claims owned by the given customer (REQ-1).
- Returns status codes, not internal states.
- Access is logged with customer ID and time, without claim content.

### S2: Internal-state to customer-status mapping
Mapping table in claims-core from every internal claim state to one
customer status code, with Legal-approved wording held in the portal.

Acceptance criteria:
- Every internal state maps to exactly one customer status.
- Wording matches the Legal-approved table (REQ-2).

### S3: Claim status page in the customer portal
Portal page listing the signed-in customer's open claims with status and
next step, behind a feature flag.

Acceptance criteria:
- Shows every open claim for the signed-in customer, newest first.
- Excludes claims run by third-party administrators.
- Can be switched off with the feature flag.

## Out of scope
- Status change notifications (see OQ-2).
- Uploading documents or changing a claim.
- Claims handled by third-party administrators.
