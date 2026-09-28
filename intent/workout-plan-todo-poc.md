---
id: workout-plan-todo-poc
title: Workout plan to-do list (POC)
author: Balamurugan Ashokkumar (requester)
source: human
record_id: SCRUM-7
fingerprint: none
owner: "@bala-chimera"
owner_role: product-owner
risk: low
systems: [workout-plan-poc]
created: 2026-09-28
related: []
---

# Intent: Workout plan to-do list (POC)

## Problem
A user who follows their own workout routine has no simple way to track it
as a checklist. There's no tool to organise a plan's exercises and mark
them off as they're completed during a session.

## Proposed outcome
A user can create a workout plan, add exercises with sets and reps, and
tick each one off as done while working out, seeing a running count of
exercises completed (e.g. "3/5 done"). This is a proof of concept to
validate whether a to-do-list style works for tracking workouts, not a
full product.

## Affected users and systems
- Users/roles affected: a single test user who follows their own workout
  routine (brought from a trainer or found online; the app does not
  prescribe workouts).
- Systems/services touched: new POC web app (`workout-plan-poc`), built
  from scratch.

## Constraints
- Must be a web app for this POC (not mobile).
- Single user, no login/authentication.
- No security hardening needed for this POC.
- Actions like ticking an exercise off must respond in under 1 second.
- Data must persist after the app is closed and reopened.

## Out of scope
- Login/authentication.
- Reminders.
- History or analytics.
- Offline sync.
- Sharing plans with others.
- Reminders and history may be added later only if the POC succeeds, but
  that decision is not part of this intent.

## Evidence
- Source document: "Workout Plan To-Do List: Requirements Document"
  (Sep 28, 2026, author: Balamurugan Ashokkumar).
- Jira SCRUM-7 (Epic created from this document).

## Open questions
- Storage: the source allows either local storage or a simple database
  for the POC ("no security hardening needed") — which should Design
  pick?
- Is a single device/session sufficient, or does "closed and reopened"
  need to survive a different device/browser?

## Success looks like
A tester can, in one sitting: create a plan named "Leg Day", add 3
exercises with sets and reps, edit one and delete another, tick an
exercise and see the done count update (e.g. "1/2 done"), then close and
reopen the app and find the plan and ticks unchanged.
