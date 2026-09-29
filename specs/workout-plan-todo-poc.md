---
id: workout-plan-todo-poc
title: Workout plan to-do list (POC)
intent: intent/workout-plan-todo-poc.md
record_id: SCRUM-7
owner: "@bala-chimera"
tech_lead: "@bala-chimera"
risk: medium
systems: [workout-plan-poc]
created: 2026-09-29
---

# Spec: Workout plan to-do list (POC)

## Summary
A single test user gets a small web app to create a workout plan, add,
edit and delete exercises with sets and reps, and tick them off while a
count ("3/5 done") updates. Data is kept in the browser so it survives
closing and reopening. The POC succeeds if a tester runs the intent's "Leg
Day" scenario in one sitting with every action under 1 second.

## Context
- `workout-plan-poc` is new and built from scratch (intent). No source,
  build files, hosting or CI for it exist in this repository.
- This repository holds the SDLC plugin and artifacts (`intent/`,
  `specs/`). Not found: a target repository or hosting for the app (OQ-3,
  OQ-4).
- Owners: `.sdlc/owners.yaml` has no components, so `default` applies:
  product owner and tech lead are both `@bala-chimera`.
- No technology standards, brand or UX skill is available; only
  `sdlc:security-policy` applies.
- Risk raised from `low` to `medium`: this is a user-visible new app and the
  spec chooses a new technology stack for it.

## Requirements
| ID | Requirement | Verification |
|---|---|---|
| REQ-1 | The user can create a workout plan with a name (e.g. "Leg Day"), and rename or delete it. | UI test: create, rename, delete a plan. |
| REQ-2 | The user can add exercises to a plan, each with a name, a number of sets and a number of reps. | UI test: add 3 exercises with sets and reps; values shown as entered. |
| REQ-3 | The user can edit and delete an exercise. | UI test: edit one exercise's reps, delete another; list updates. |
| REQ-4 | The user can tick and untick an exercise as done. | UI test: tick and untick; state shown on the exercise. |
| REQ-5 | Each plan shows a running count such as "3/5 done" that updates on every tick, untick, add and delete. | UI test: after deleting one of 3 and ticking one, shows "1/2 done". |
| REQ-6 | Plans, exercises and ticks are unchanged after the app is closed and reopened in the same browser. | Manual test: close the tab/browser, reopen, compare. |
| REQ-7 | Every user action (tick, add, edit, delete) updates the screen in under 1 second. | Timed manual test on the tester's machine; browser performance trace for tick. |
| REQ-8 | It runs as a web app in a current desktop browser; no mobile app, no login. | Tester opens it from a URL or local file in the browser. |
| REQ-9 | Invalid input is rejected with a clear message: empty names, names over 100 characters, sets or reps that are not whole numbers from 1 to 100. | UI test per invalid case. |

## Technology and architecture
Greenfield: no existing stack to follow. Options:

| Option | Fit | Skills and cost | Security | Operability |
|---|---|---|---|---|
| A. Static page, plain HTML/CSS/JavaScript, browser `localStorage` | Meets every REQ; data is per browser (OQ-2) | No build, no dependencies; least effort | No server; no data leaves the device | Any static host or local file |
| B. SPA framework (e.g. React) plus `localStorage` | Same as A | Easier to grow; adds toolchain and npm dependencies | SEC-5 per dependency | Build and dependency updates |
| C. Small web server plus database (e.g. SQLite) | Also works across devices | Most effort; needs hosting | Unauthenticated server conflicts with SEC-1.1/1.2 (Areas of concern) | Process and database to run and patch |

**Recommendation: Option A.** Least to build, no security surface beyond
the browser. Storage sits behind one module so B or C can replace it later
(a separate intent) without touching the UI.

Decision needed from: tech lead (@bala-chimera).

## Design
**Components (Option A)**
1. `index.html` plus one stylesheet and one or two script files; no
   external scripts, fonts or CDNs.
2. **Storage module**: the only code that touches `localStorage`. Loads and
   saves one JSON document under a single key, e.g. `workout-plan-poc.v1`.
3. **UI**: plan list (create, select, rename, delete) and plan view
   (exercise list with add, edit, delete, tick; done count in the header).

**Data model** (one JSON document)
- `schemaVersion`: number, starts at 1.
- `plans[]`: `id`, `name`, `exercises[]`.
- `exercises[]`: `id`, `name`, `sets`, `reps`, `done` (boolean).
- IDs are random strings made in the browser. No user identity is stored.

**Data flow**
- On load: parse and check `schemaVersion`; missing key means start empty.
  Unparseable data is kept under a backup key and a message is shown.
- On every change: update state, re-render the plan, save the whole
  document. The data is tiny, so this stays well under 1 second (REQ-7).
- If storage is unavailable or full, warn that changes will not be kept.
- Done count is computed from `exercises[].done`, never stored separately.
- Ticks stay until the user unticks them (see OQ-5).

**Interfaces**: none external. No network calls.

**Rollout and rollback**: static files delivered to the tester (OQ-4).
Rollback is serving the previous files; the versioned data format makes an
older build refuse unknown versions rather than corrupt them.

## Security considerations
| Rule | Applies? | How this design satisfies it |
|---|---|---|
| SEC-1.1 | No | No login, session, endpoints or jobs. Becomes Yes under Option C (Areas of concern). |
| SEC-1.2 | No | No server and no shared resources; data stays in one user's browser. |
| SEC-2.1 | Yes | Stores only plan names, exercise names, sets, reps and done flags. No name, email, body measurements or other personal fields are collected. |
| SEC-2.2 | No | No new company storage or data flow: data never leaves the user's device (see OQ-6 on whether workout data counts as health data). |
| SEC-2.3 | Yes | No logging or analytics; errors shown to the user do not echo stored content. |
| SEC-3.1 | Yes | No secrets exist or are needed; none in the code or repository. |
| SEC-4.1 | Yes | Names and sets/reps validated for type, length and range in the UI before saving (REQ-9); data read from storage is re-validated on load. |
| SEC-4.2 | Yes | User text is rendered with `textContent` (or equivalent encoding), never by joining strings into HTML, so an exercise name cannot inject script. |
| SEC-5.1 | Yes | Option A adds no dependencies. Option B would require pinned dependencies from approved registries with no known critical/high vulnerabilities. |
| SEC-7.1 | No | No external services, CDNs, fonts or analytics. |

## Open questions
| ID | Source | Question | Status | Answer or next step | Who |
|---|---|---|---|---|---|
| OQ-1 | intent | Storage: the source allows either local storage or a simple database for the POC ("no security hardening needed") — which should Design pick? | answered | Local storage (Option A), because it meets every requirement with no server; subject to the tech lead's stack decision above. | @bala-chimera |
| OQ-2 | intent | Is a single device/session sufficient, or does "closed and reopened" need to survive a different device/browser? | open | Option A keeps data per browser on one device. If a different device/browser is required, Option C is needed and risk becomes high (SEC-1). Product owner to confirm. | @bala-chimera |
| OQ-3 | spec | Which repository will hold the `workout-plan-poc` code? No app repository was found, and this repository keeps product code separate from plugin changes. | open | Name or create the repository before S1 starts. | @bala-chimera |
| OQ-4 | spec | How does the tester open the app: a local file, or a static host? No hosting was found. | open | Pick one; any static host works for Option A. Must not add a third-party service without SEC-7 review if data would be sent to it (it is not in Option A). | @bala-chimera |
| OQ-5 | spec | Should ticks reset for a new workout session (e.g. a "clear all ticks" action)? The intent does not say, and history is out of scope. | open | Default: ticks stay until unticked. A reset action is a small addition to S4 if wanted. | @bala-chimera |
| OQ-6 | spec | Does exercise data (names, sets, reps) count as health data under the policy? | open | Design treats it as not personal data because it stays on the device and holds no identity. Policy owner to confirm. | @bala-chimera |

## Areas of concern
- **Intent says "no security hardening needed"; the policy still applies.**
  The intent cannot waive `sdlc:security-policy`. With Option A the
  applicable rules (SEC-2.1, SEC-4, SEC-5) are met at almost no cost, so
  there is no conflict. Options: meet them as designed, or seek an
  exception. Recommendation: meet them as designed.
  Decision needed from: policy owner (@bala-chimera).
- **Cross-device persistence would change the risk.** If OQ-2 is answered
  "different device/browser", a server and database are needed. An
  unauthenticated, network-reachable server storing user data conflicts
  with SEC-1.1 (existing identity provider) and SEC-1.2 (server-side
  authorization), and the intent rules out login. Options: keep single
  browser (Option A); run Option C only on the tester's own machine
  (localhost, not network-reachable); or add the existing identity
  provider, which contradicts the intent. Recommendation: keep Option A
  for the POC. If Option C is chosen, raise risk to high.
  Decision needed from: tech lead and policy owner (@bala-chimera).

## Work breakdown

### S1: App shell and local storage module
Static web app skeleton plus the storage module that loads, validates and
saves the versioned JSON document in the browser.

Acceptance criteria:
- Opening `index.html` in a desktop browser shows an empty plan list with no network requests.
- Saved data is reloaded unchanged after closing and reopening the browser (REQ-6).
- Unparseable stored data is kept under a backup key and a message is shown.
- When storage is unavailable, a warning says changes will not be kept.
- The repository contains no secrets and no third-party dependencies.

### S2: Create, rename and delete workout plans
Plan list where the user creates a named plan, opens it, renames it or
deletes it.

Acceptance criteria:
- Creating "Leg Day" adds it to the list and it survives a reload (REQ-1).
- Renaming and deleting a plan update the list and survive a reload.
- Empty names and names over 100 characters are rejected with a message (REQ-9).
- A plan name containing `<script>` is shown as text, not run (SEC-4.2).

### S3: Add, edit and delete exercises with sets and reps
Within a plan, the user adds exercises with name, sets and reps, and can
edit or delete them.

Acceptance criteria:
- Adding 3 exercises shows each with its sets and reps (REQ-2).
- Editing an exercise's sets or reps shows the new values after a reload (REQ-3).
- Deleting an exercise removes it and it stays removed after a reload.
- Sets or reps that are not whole numbers from 1 to 100 are rejected with a message (REQ-9).

### S4: Tick off exercises with a running done count
The user ticks and unticks exercises during a session and sees a running
done count (e.g. "3/5 done") for the plan.

Acceptance criteria:
- Ticking and unticking change the exercise's done state and survive a reload (REQ-4, REQ-6).
- The count updates on every tick, untick, add and delete; with 2 exercises and 1 ticked it shows "1/2 done" (REQ-5).
- A tick updates the screen in under 1 second (REQ-7).

### S5: Deliver the POC and run the acceptance scenario
Make the app available to the tester as decided in OQ-4 and run the
intent's "Leg Day" scenario.

Acceptance criteria:
- The tester can open the app in their browser without installing anything (REQ-8).
- The full scenario passes in one sitting: create "Leg Day", add 3 exercises, edit one, delete one, tick one and see "1/2 done", close and reopen with plan and ticks unchanged.
- Results are recorded on SCRUM-7 for the go/no-go decision.

## Out of scope
- Login/authentication.
- Reminders.
- History or analytics.
- Offline sync.
- Sharing plans with others.
- Mobile apps.
- Sync across devices or browsers (unless OQ-2 changes it, which needs a spec update).
- Deciding whether reminders or history are added later.
