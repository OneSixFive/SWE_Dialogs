# Beads Task Tracker

This repository uses `bd` as its task tracker. Use the smallest command set below instead of reading the full CLI help for routine work.

## Required Workflow

If substantial requested work does not already have a bead, create one:

```bash
bd q "Short task title"
```

`bd q` prints the issue ID. Capture it and use it for the remaining commands.

Claim and start the issue:

```bash
bd assign <ISSUE_ID> dima
bd update <ISSUE_ID> -s in_progress
```

Add a note when the task meaningfully changes state or an important fact is discovered:

```bash
bd update <ISSUE_ID> --notes "What changed, what was found, or what remains"
```

Close the issue only when the work is complete:

```bash
bd close <ISSUE_ID>
```

## Practical Rules

- Run `bd` in the checkout selected as the task's edit origin: local for app/cross-cutting work, or VM for backend-only and prompt-only live work.
- Do not operate on one bead concurrently from both checkouts.
- Run Beads commands one at a time. Its embedded backend may hold an exclusive lock.
- If a command reports that another process holds the exclusive lock, wait a few seconds and retry once after the earlier command exits.
- Keep titles short and concrete.
- Prefer one bead per user-visible task.
- Use notes for decisions, verification results, and discovered edge cases.
- Do not leave an active bead unassigned or in an open state after its work is complete.
- Create a separate follow-up bead for work that should not be silently folded into the current task.

The repository uses the `svenska-` issue prefix and an embedded Dolt database managed under `.beads/`.
