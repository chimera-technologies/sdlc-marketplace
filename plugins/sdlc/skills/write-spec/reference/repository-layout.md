# Repository layout: one repo, or one repo per service

The tech lead decides this in the spec, like the stack. Compare the two for
the project in front of you and recommend one; never decide it yourself.

## One repo

Everything in one repository: a single service, or several services in
folders (`apps/web/`, `services/orders/`), each with its own schema.

- One spec and one PR can change several services at once, so they never
  drift apart.
- One set of `.sdlc/` config, one setup, one release for the whole repo
  (every service ships together).
- Fits: one team, or a few teams on one product; a new product whose
  service boundaries are still moving.

## One repo per service

A **system repo** (intents, specs, the Service map, shared contracts; no
service code) and one repo per service, each with its own build, tests,
releases, environments and owners.

- Each service is released, rolled back and maintained on its own.
- A change inside one service runs the whole loop in that service's repo.
- Every repo is set up once (the system repo writes each one's answers:
  `/sdlc:init system=<owner/system-repo>`), all under one GitHub owner so
  one sdlc-bot App reaches them.
- Fits: several teams that each own services; services that must deploy
  or scale independently; a part that must be isolated (payments and PCI
  scope).

## Questions that decide it

| Question | Points to |
|---|---|
| Does one team own most of the code? | one repo |
| Must services release on different days, or be rolled back alone? | one repo per service |
| Are the service boundaries still changing? | one repo (split later) |
| Is there a part with its own compliance scope (payments, health data)? | one repo per service, or at least that part on its own |
| Does a typical feature touch several services? | one repo makes those changes simpler |

Moving from one repo to one repo per service later is normal; the other way
round is rare. When in doubt, recommend one repo.

## Drawing service boundaries

- One service per business capability (catalog, orders, payments), not
  per technical layer (no "database service", no "API service").
- Each service owns its data: no other service reads its tables; data is
  shared through its API or events.
- A service a team cannot explain in one sentence is two services; two
  services that always change together are one.
- Start with few. Four or five services is a lot for a new product.
