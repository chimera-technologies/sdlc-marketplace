---
id: p95-latency-claims-api
title: Claims-core API p95 latency breach
author: Maintain (bands.yaml: p95_latency_ms)
source: maintain
record_id: none
fingerprint: p95-latency-claims-api
owner: "@bala-chimera"
owner_role: service-owner
risk: medium
systems: [claims-core]
created: 2026-09-28
related: []
---

# Intent: Claims-core API p95 latency breach

## Problem
The claims-core service's p95 response latency has breached its tier 3
performance band: the observed value is 2400ms against a band of <=800ms
(3x over). This was detected automatically as breach BR-1. The source
signal does not state which user-facing workflows are slowed, how many
users are affected, or when the breach began.

## Proposed outcome
Claims-core's p95 latency returns to within its tier 3 band (<=800ms), so
that whichever user or downstream workflow depends on this response time
is no longer degraded.

## Affected users and systems
- Users/roles affected: None stated in source.
- Systems/services touched: claims-core

## Constraints
None stated in source.

## Out of scope
None stated.

## Evidence
Maintain breach BR-1: metric p95_latency_ms, tier 3, observed 2400ms vs
band <=800ms.

## Open questions
- Owner to confirm: claims-core is not listed in `.sdlc/owners.yaml`
  components, so this routed to the default owner. Who actually owns it?
- Owner to confirm: which users/workflows depend on claims-core's response
  time and are affected by this breach?
- Owner to confirm: when did the breach begin, and is it ongoing or
  resolved? Not included in the signal.
- Owner to confirm: is there a runbook or dashboard for this metric? None
  was included in the signal.
- Owner to confirm: does claims-core's latency here sit behind a public
  API contract? That would raise this from medium to high risk.

## Success looks like
Claims-core's p95 latency is measured back at or below 800ms, and breach
BR-1 is closed.
