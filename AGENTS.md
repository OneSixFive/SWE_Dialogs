# Project Context

See [docs/RUNBOOK.md](./docs/RUNBOOK.md) for minimal project context, current app/backend state, and verification commands.
For OpenAI usage/cost or billing-endpoint work, also see [docs/BILLING.md](./docs/BILLING.md).
Before changing OpenAI request construction, preserve prompt-cache optimization and follow the invariants and input order in [docs/RUNBOOK.md](./docs/RUNBOOK.md#model-boundaries).

# VM Access

- Use SSH user `codex` for routine VM work.
- The `codex` user can work in the remote repo and restart/status/log `svenska-api.service`.
- Do not use broader privileged access for normal app/backend changes.

# Git Sync Workflow

Use git as the normal sync path between local and VM.

Default rules:
- Choose one edit origin for each change.
- Commit and push from that origin.
- Pull into the other environment with `git pull --ff-only`.
- Agents are encouraged to use git freely to keep local, origin, and VM synchronized before and after changes.
- Prefer the repo scripts for routine sync commands:
  - Stage files intentionally, then run `scripts/git-commit-push.sh "Commit message"` to commit staged changes and push the current branch.
  - Run `scripts/vm-sync.sh` to fast-forward pull on the VM and check backend health.
  - Use `scripts/vm-sync.sh --backend-tests --restart-backend` after backend runtime code changes.

Preferred edit origin:
- iOS/frontend or cross-cutting app + backend/prompt work: edit, build, and test locally; commit/push locally; then pull on the VM.
- Backend-only or prompt-only work where live VM behavior is the target: edit on the VM; verify there; commit/push from the VM; then pull locally.

After syncing to the VM:
- Restart `svenska-api.service` only when backend runtime code changed.
- Check service status/logs when backend behavior is relevant.
- Prompt-only changes may not require restart if the backend reads prompt files per request.

Avoid direct file copying between local and VM as a routine workflow. Use `scp` or other hot patches only for explicit emergency/live-test cases, then reconcile immediately through git so neither side stays dirty or divergent.

# Prompts And Curriculum

- Prompt source files live only in `Materials/`.
- The backend reads prompts directly from `Materials/`; do not add duplicate bundled prompt copies.
- The current lesson engine is structured around curriculum briefs in `Materials/Lessons/` and bundled resources in `SWE_Dialogs/SWE_Dialogs/Resources/`.
- Keep source materials and bundled runtime copies in sync when editing curriculum.

# Encoding

Lesson JSONs may be valid UTF-8 without BOM. On Windows, default PowerShell text reads can misrender Swedish characters and create false mojibake reports. Validate with explicit UTF-8 decoding before reporting corruption.

# Device

The physical iOS device used for development is `iPhone_D`. Agents may inspect it with Xcode/devicectl when useful.

# Beads Issue Tracker

This project uses `bd` for task tracking.

## Beads Rules

- Use `bd` as the source of truth for open tasks.
- Run `bd` in the checkout chosen as the edit origin under the Git Sync Workflow above. Do not update the same task independently in both local and VM checkouts.
- For the minimal agent workflow and command set, see [docs/BEADS.md](./docs/BEADS.md).
- Use Beads for medium-or-larger functionality work.
- Do not create beads for small tasks such as:
  - runbook or `AGENTS.md` wording/configuration updates
  - general questions or codebase questions
  - tiny one-off inspections or clarifications
  - other similarly small tasks that do not represent real product or system work
- If requested work is substantial and does not already have a `bd` issue, create one before starting.
- Claim the issue being worked on and mark it in progress.
- Close issues when the work is complete.
- Create linked follow-up issues for newly discovered work that is outside the current task.
