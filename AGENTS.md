See [RUNBOOK.md](./RUNBOOK.md) for the minimal project context, current app state, and expansion direction.

Important: the Swift app still reflects the current prototype, but the project is being expanded into a structured Swedish lesson app. Curriculum/lesson JSON work under `Materials/Lessons/` is part of that direction and should not be treated as unrelated.

Encoding note for lesson JSONs: files may be valid UTF-8 without BOM. On Windows, default PowerShell text reads can misrender Swedish characters and create false mojibake reports. Validate by reading bytes/text with explicit UTF-8 decoding before reporting corruption.
