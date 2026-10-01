---
name: init
description: Set up a project repo to use the SDLC loop (Plan, Design, UI
  design, Build, PR review, Test, Deploy, Maintain) from this plugin, or
  upgrade or check an existing setup, or record the tech stack the spec
  decided. Use when someone says "set up the SDLC here", "onboard this repo",
  "use the sdlc plugin in this project", "upgrade the sdlc plugin", "record
  the stack from the spec", or runs /sdlc:init.
argument-hint: "[stack=specs/<slug>.md] [upgrade=vX.Y.Z] [check]"
---

# Set up a project for the SDLC loop

Goal: the project gets its `.sdlc/` config, `REVIEW.md`, an SDLC block in
`CLAUDE.md`, the plugin pins in `.claude/settings.json`, and small GitHub
workflow callers pinned to one tag of this plugin. Everything is written
by `${CLAUDE_SKILL_DIR}/scripts/init_project.py`; you only interview and
confirm. Nothing is written straight to the base branch.

Arguments: `$ARGUMENTS`

## Choose the mode

- `check`: run `python "${CLAUDE_SKILL_DIR}/scripts/init_project.py" --check`
  and report the result. Stop.
- `upgrade=vX.Y.Z`: go to "Upgrade".
- `stack=specs/<slug>.md`: go to "Record the stack".
- Otherwise: "Set up". If `.sdlc/sdlc.json` already exists, say so and ask
  whether to regenerate (keeps existing `.sdlc/*` config) or stop.

## Set up

1. **Look first.** Confirm this is a git repo with a GitHub remote
   (`git remote get-url origin`) and note the default branch. Run
   `python "${CLAUDE_SKILL_DIR}/scripts/init_project.py" --detect` for a stack
   suggestion from the repo's files (it may be empty for a new repo).
2. **Ask in one message**, with sensible defaults filled in, and let the
   person correct them:
   - Owners (GitHub handles or `@org/team`): product owner, service owner,
     tech lead, security owner (default: the tech lead).
   - Jira: yes or no; if yes, the site (`<name>.atlassian.net`) and space key.
     With Jira on, every accepted spec gets an Epic and one Story per spec
     story automatically (when the spec merges), whether or not the intent
     came from a Jira ticket.
   - Stages to enable (default all): plan, design, ui_design, build,
     pr_review, test, deploy, maintain.
   - Automatic Build (default yes): each story gets a plan PR, and merging
     it builds the story in CI and opens the story PR. No = build every
     story by hand with `/sdlc:build-story`.
   - Stack: the detected one, or "decide from the spec later". The stack is
     the tech lead's call in the spec; do not invent one for a new repo.
   - The plugin tag to pin (default: the latest `v*` tag of
     `bala-chimera/sdlc-marketplace`, e.g. from
     `git ls-remote --tags https://github.com/bala-chimera/sdlc-marketplace`).
3. **Write the answers** to `.sdlc-output/init-answers.json`:

   ```json
   {"sdlc_ref": "v0.9.2", "base_branch": "main",
    "owners": {"product_owner": "@po", "service_owner": "@org/sre", "tech_lead": "@lead", "security_owner": "@lead"},
    "jira": {"enabled": true, "site": "acme.atlassian.net", "space_key": "ACM"},
    "stages": {"ui_design": false}, "auto_build": true,
    "stack": {"toolchains": ["python@3.12"], "install_command": "pip install -r requirements.txt",
              "test_command": "pytest -q", "test_file_command": "pytest -q {file}", "test_paths": ["tests/"]}}
   ```
4. **Branch and generate**: `git checkout -b sdlc/init`, then
   `python "${CLAUDE_SKILL_DIR}/scripts/init_project.py" --answers .sdlc-output/init-answers.json`.
   Show the person the list of files it created or updated.
5. **Commit and PR**: stage exactly the files it listed (never `git add -A`),
   commit `sdlc: set up the SDLC loop (<tag>)`, push, and open a PR (with
   `gh`, or give the compare link). Tell the person the PR is a config
   change for a platform or tech-lead review.
6. **Hand over the checklist** the script printed: marketplace access, the
   sdlc-bot GitHub App, repo variables and secrets, branch protection,
   Jira Automation, deploy environments, Figma. Offer to walk through any
   of them.

## Record the stack

After a spec's Technology and architecture decision is accepted:

1. Read the spec's decision and the repo's files. Propose `toolchains`
   (`node@<v>`, `python@<v>`, `java@<v>`, `dotnet@<v>`, `go@<v>`; anything
   else via `setup_command`), `install_command`, `test_command`,
   `test_file_command` (with `{file}`), `test_paths`, `code_paths` and
   `report_path`. Commands must not contain `#`.
2. Confirm with the person, write them to `.sdlc-output/init-stack.json`,
   and run `python "${CLAUDE_SKILL_DIR}/scripts/init_project.py" --stack .sdlc-output/init-stack.json`.
3. Commit `.sdlc/build.yaml` on a `sdlc/stack-<slug>` branch and open a PR.
   Build stories can start once it merges.

## Upgrade

1. `git checkout -b sdlc/upgrade-<tag>`, then
   `python "${CLAUDE_SKILL_DIR}/scripts/init_project.py" --upgrade <tag>`.
2. Read the marketplace's `CHANGELOG.md` for the versions in between and
   tell the person anything that needs action (new secrets, new checks).
3. Commit the files it listed, push, open a PR. Merging moves every stage to
   the new tag at once.
