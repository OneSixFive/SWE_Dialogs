# Project Runbook

This repo is an iOS SwiftUI app for Swedish listening and lesson practice. Keep this file short: it should preserve current architecture and non-obvious operating context, not duplicate what filenames or `rg` can show.

## App Shape
- Main tabs are `Lessons`, `Settings`, and `More`.
- `Lessons` is the current structured lesson engine. `More` keeps the older custom Gemini TTS flow and local audio history.
- There is no active generic OpenAI chat tab now.
- Legacy hardcoded dialog-plan files (`Stage4Plan.swift`, `Stage4PlanView.swift`, `Stage4ProgressStore.swift`) remain in the project but are not shown in the tab bar. Do not treat them as the current lesson flow.

## Lesson Engine
- Curriculum authoring source lives under `Materials/`; bundled runtime resources live under `SWE_Dialogs/SWE_Dialogs/Resources/`.
- Lesson payload JSONs are curriculum briefs only. Do not put generated dialogues, answer keys, audio text, or learner chat history in them.
- `curriculum.json` is the bundled combined lesson resource. It currently contains 224 lessons: 112 B1 and 112 B2, with a 4 stage x 4 week x 7 day grid per level.
- Prompt drafts live in `Materials/Shared_base_prompt.md`, `Materials/Generator_prompt.md`, and `Materials/Interactor_prompt.md`. Runtime copies live in `Resources/TutorPrompts/`; keep both copies in sync when editing prompts.
- Generated dialogue TTS text is derived from parsed dialogue lines (`Anna: ...\nErik: ...`). Do not store `tts_text` as independent model output.

## Model Boundaries
- `OpenAITutorService` uses the Responses API with structured JSON schemas.
- Generator input is one lesson payload. Output is only a 20-line Anna/Erik dialogue plus 3 Swedish comprehension questions, then `LessonValidator` checks it.
- Interactor calls are fresh Responses API requests, not Conversations API threads and not `previous_response_id` chains.
- Interactor input is intentionally ordered for prompt caching:
  1. `course_context_json`
  2. `lesson_payload_json`
  3. `generated_lesson_json`
  4. `full_lesson_chat_history_json`
  5. `lesson_state_json`
  6. `latest_user_message`
- `course_context_json` includes the app course level and the target Swedish explanation level: B2 lessons explain at B1, B1 lessons explain at A2.
- Interactor requests set `prompt_cache_key` per lesson. The app still sends current state every turn; server-side context is not the source of truth.
- Interactor output is `assistant_text`, `state_patch`, and optional `translation_quiz`. The app validates patches and owns state transitions; the interactor cannot mark a lesson completed directly.

## Persistence
- App document files:
  - `generated_lessons.json`: generated lessons keyed by lesson ID.
  - `lesson_sessions.json`: lesson state plus per-lesson chat history.
  - `lesson_audio/*.wav`: generated lesson audio.
  - `history.json` plus root-level `dialog-*.wav`: older custom TTS history.
- `Regenerate Lesson` replaces the generated dialogue/questions and resets that lesson session; this can orphan old chat/audio references by design.

## Audio
- Lesson audio and custom TTS audio use Gemini TTS via `GeminiTTSService`.
- Background playback depends on `SWE_Dialogs/Info.plist` containing `UIBackgroundModes = [audio]`. The target uses the explicit plist (`GENERATE_INFOPLIST_FILE = NO`).
- `ContentView.swift` keeps separate audio controllers for lesson/custom/history flows to avoid playback state leaking between screens.

## Encoding
- Preserve real Swedish characters and valid UTF-8. Lesson JSONs may be UTF-8 without BOM.
- On Windows, default PowerShell reads can misrender Swedish characters. Validate with explicit UTF-8 decoding before reporting mojibake.
- Do not reintroduce old Deep Research citation artifacts such as `turn...`, `cite`, or special citation marker glyphs into curriculum files.

## Verification
- Quick build:
  - `cd SWE_Dialogs && xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' build`
- Full validation:
  - `cd SWE_Dialogs && xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' test`
- If simulator test launch fails with `NSMachErrorDomain Code=-308`, `FBSOpenApplicationErrorDomain Code=6`, `Busy`, or “Application failed preflight checks”, recover with:
  - `xcrun simctl shutdown all`
  - `xcrun simctl boot <SIMULATOR_UDID>`
  - `xcrun simctl bootstatus <SIMULATOR_UDID> -b`
  - rerun tests with `-parallel-testing-enabled NO` if needed.
