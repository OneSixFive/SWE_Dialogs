See [docs/RUNBOOK.md](./docs/RUNBOOK.md) for minimal project context, current app/backend state, and verification commands.

VM note: use SSH user `codex` for routine VM work. That user can work in the remote repo and restart/status/log `svenska-api.service`; do not use broader privileged access for normal app/backend changes.

Runtime workflow note: iOS/frontend changes are developed and verified locally, but the physical/TestFlight app calls the VM backend. Backend and prompt changes only affect that app after the VM repo/runtime copy is updated; mirror urgent VM edits back to local/git to avoid drift. For prompt changes, keep `Materials/` and `SWE_Dialogs/SWE_Dialogs/Resources/TutorPrompts/` synced locally and verify/deploy the VM copies.

Curriculum note: the current lesson engine is structured around curriculum briefs in `Materials/Lessons/` and bundled resources in `SWE_Dialogs/SWE_Dialogs/Resources/`. Keep source materials and bundled runtime copies in sync when editing curriculum or prompts.

Encoding note: lesson JSONs may be valid UTF-8 without BOM. On Windows, default PowerShell text reads can misrender Swedish characters and create false mojibake reports. Validate with explicit UTF-8 decoding before reporting corruption.

Device note: the physical iOS device used for development is `iPhone_D`. Agents may inspect it with Xcode/devicectl when useful.
