# Claude Code workflows in the sdlc plugin

Some jobs are too big for one session to do well: a long requirement
document loses detail, and one reviewer misses what a panel catches. For
those, a skill runs a **Claude Code workflow** (the Workflow tool): several
agents in parallel, then agents that try to refute the results. The scripts
live in `plugins/sdlc/workflows/`; a skill that reaches a threshold below
runs its script.

## When (the project setting)

`.sdlc/sdlc.json` key `workflows` (written by `/sdlc:init`):

- `auto` (default): run the workflow when the threshold is met.
- `always`: run it whatever the size.
- `off`: never; one session, as before.

A missing key means `auto`.

| Skill | Workflow | Threshold for `auto` (any one) |
|---|---|---|
| `write-intent` | `requirements-to-intents.js` | the source document is over ~3,000 words, or has more than 8 top-level sections, or Step 1b finds 3 or more intents |
| `review-spec` | `review-panel.js` (`kind: spec`) | the spec has 5 or more stories, or is over ~2,500 words, or its `risk` is `high` |
| `review-story` | `review-panel.js` (`kind: story`) | the diff (`git diff --stat <base>...HEAD`) changes more than 400 lines or 12 files, or the spec's `risk` is `high` |

Below the threshold, the skill works in one session as written: the extra
agents cost more than they find on small inputs.

## How to run one

Call the Workflow tool (load it with ToolSearch if it is deferred) with
`scriptPath` set to the script and `args` as a JSON object (not a string),
as each skill says. Every script returns JSON in the shape the skill already
writes, so the rest of the skill does not change: the skill, not the
workflow's agents, writes the output files and runs the validators.

Then say in one line that a workflow was used (for example "Reviewed by a
4-lens panel with 2 skeptics per finding"), in the output's summary.

## When it cannot run

If the Workflow tool is not available, or the run fails or returns nothing
usable, do the job in one session exactly as the skill describes and note
"workflow unavailable; single-session" in the summary. A workflow never
blocks the stage.
