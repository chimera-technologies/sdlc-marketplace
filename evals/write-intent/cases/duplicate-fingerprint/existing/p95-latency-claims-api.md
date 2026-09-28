---
id: p95-latency-claims-api
title: Claims API responses are too slow for customers
author: Maintain (bands.yaml: p95_latency_ms)
source: maintain
record_id: none
fingerprint: p95-latency-claims-api
owner: "@example-org/claims-sre"
owner_role: service-owner
risk: medium
systems: [claims-core]
created: 2026-09-27
related: []
---

# Intent: Claims API responses are too slow for customers

## Problem
Since 14:05 UTC on 2026-09-27, the slowest 5% of claims-core API responses
take about 2.4 seconds, three times the agreed limit of 800 ms. Customers
and handlers using claim screens wait noticeably longer.

## Proposed outcome
Claims screens respond as quickly as before: p95 latency back inside its
band and staying there.

## Affected users and systems
- Users/roles affected: external customers, claims handlers
- Systems/services touched: claims-core API

## Constraints
None stated in source.

## Out of scope
None stated.

## Evidence
- Breach BR-1, tier 3, p95_latency_ms 2400 against band 800 or less (15m window), 2026-09-27T14:05:00Z
- Dashboard: https://grafana.example.com/d/claims-core
- Runbook: runbooks/claims-core-latency.md

## Open questions
- Owner to confirm: was there a deploy or traffic change at the time of the breach?

## Success looks like
p95 latency stays at or under 800 ms for two weeks.
