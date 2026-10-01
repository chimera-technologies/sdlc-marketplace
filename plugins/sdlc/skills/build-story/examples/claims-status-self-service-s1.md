---
id: claims-status-self-service-s1
spec: specs/claims-status-self-service.md
story: S1
jira: CLM-483
branch: story/clm-483-status-endpoint
created: 2026-09-29
---

# Plan: S1 Customer claim status endpoint in claims-core

## Story
A read-only endpoint in claims-core returns a customer's open claims with
customer status codes, filtered on the server by the authenticated customer
ID. Covers REQ-1 and the logging part of SEC-6.1.

## Files
| File | Change |
|---|---|
| claims-core/api/customer_status.py | new: `GET /customers/{customerId}/claims/status` handler |
| claims-core/api/routes.py | changed: register the new route behind the portal service credential |
| tests/api/test_customer_status.py | new: tests for AC-1 to AC-3 |

## Tests
| AC | Acceptance criterion | Test |
|---|---|---|
| AC-1 | Returns only claims owned by the given customer (REQ-1). | tests/api/test_customer_status.py › "S1 AC-1: only the customer's own claims" |
| AC-2 | Returns status codes, not internal states. | tests/api/test_customer_status.py › "S1 AC-2: status codes, never internal states" |
| AC-3 | Access is logged with customer ID and time, without claim content. | tests/api/test_customer_status.py › "S1 AC-3: access logged without claim content" |

## Edge cases
- Customer with no open claims: empty list, 200 (AC-1 test, empty fixture).
- Claim owned by another customer, asked for by ID: 404, not 403, so its existence is not revealed (AC-1 test).
- Claim in an internal state with no customer status yet: shown as "In progress", never the internal name (AC-2 test).
- Logging fails: the request still succeeds and the failure is reported to monitoring; not tested here, the shared logger owns it.

## Steps
1. Write the three failing tests against a seeded test database with two customers.
2. Add the handler: take the customer ID from the verified service token, query open claims for it, map states to codes.
3. Add the access log line (customer ID, claim IDs, time) and register the route.

## Risks and rollback
The endpoint is new and unused until S3 ships, so rollback is reverting the PR.

## Out of scope
- The state-to-status mapping table itself (S2).
- The portal page (S3).
