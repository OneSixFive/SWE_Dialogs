# Project Runbook (Minimal)

## Current app state
- iOS SwiftUI app in `SWE_Dialogs/` that generates multi-speaker TTS dialogs via Gemini and plays local WAV output.
- Also includes a basic OpenAI text chat tab using Conversations API with local on-device chat persistence.
- The main tab bar now has a `Lessons` tab backed by bundled curriculum data. The older hardcoded `Dialogs` checklist files still exist but are no longer shown in the tab bar.

## Lesson engine architecture
- The app is being expanded into a structured Swedish lesson engine for flexible levels such as B1 and B2.
- The user should experience one seamless lesson flow; Generator and Interactor are hidden implementation details.
- Static `lesson_payload.json` files are the curriculum source of truth.
- **Generator**: takes one lesson payload and creates only:
  - 20-line Anna/Erik dialogue
  - 3 Swedish comprehension questions
- **App**: validates and persists generated lessons, computes Gemini TTS text from dialogue lines, stores lesson state/progress, and owns valid state transitions.
- **Gemini TTS**: receives only app-rendered speaker-prefixed dialogue text, e.g. `Anna: ...\nErik: ...`.
- **Interactor**: receives `lesson_payload + generated_lesson + lesson_state + latest_user_message`; replies conversationally and returns a structured state patch.
- Do not store `tts_text` as independent generated model content. Generate it from the parsed dialogue array to keep display and audio aligned.
- Treat `Materials/` as the authoring area for prompts, progression documents, and lesson payload JSONs.
- The app runtime currently loads a generated combined resource at `SWE_Dialogs/SWE_Dialogs/Resources/curriculum.json` plus prompt copies in `SWE_Dialogs/SWE_Dialogs/Resources/TutorPrompts/`.

## Confirmed lesson user flow
- User starts from a prominent `Continue` action, with level/stage/week/day selectors available.
- Opening a new day shows `Generate Lesson`; after generation, the saved generated lesson is reused from `generated_lessons.json`.
- If a Gemini key exists, audio generation should happen automatically after lesson generation, with a visible `Regenerate Audio` control.
- The transcript should be shown, not hidden behind a listening-only mode.
- All 3 comprehension questions should be visible; the lesson chat can handle answers in any order.
- After comprehension is complete, the translation quiz should appear as a non-blocking prompt/banner/sheet. The user can ignore it and keep chatting, or start the quiz.
- Each lesson has its own chat history and state in `lesson_sessions.json`.
- Completion is suggested after comprehension + quiz, but the user confirms with `Mark Complete`.
- `Regenerate Lesson` is allowed, but should warn that it replaces dialogue/questions and can orphan old chat/audio.

## Curriculum materials
- Prompt drafts live in:
  - `Materials/Shared_base_prompt.md`
  - `Materials/Generator_prompt.md`
  - `Materials/Interactor_prompt.md`
- Level materials live under `Materials/Lessons/<LEVEL>/`.
- Lesson payload JSONs should live under `Materials/Lessons/<LEVEL>/Lesson_brief_JSONs/`.
- Current progression documents:
  - `Materials/Lessons/B1/Progression_Path_from_A2_to_B1_in_Swedish.md`
  - `Materials/Lessons/B2/Progression_Path_from_B1_to_B2_in_Swedish.md`
- Current generated lesson payload inventory:
  - B1: 112 files in `Materials/Lessons/B1/Lesson_brief_JSONs/`
  - B2: 112 files in `Materials/Lessons/B2/Lesson_brief_JSONs/`
  - Total: 224 lesson payload JSON files.
- Bundled runtime curriculum:
  - `SWE_Dialogs/SWE_Dialogs/Resources/curriculum.json`
  - schema version 1
  - 224 lessons
- Bundled runtime prompt copies:
  - `SWE_Dialogs/SWE_Dialogs/Resources/TutorPrompts/Shared_base_prompt.md`
  - `SWE_Dialogs/SWE_Dialogs/Resources/TutorPrompts/Generator_prompt.md`
  - `SWE_Dialogs/SWE_Dialogs/Resources/TutorPrompts/Interactor_prompt.md`
- Use `Materials/Lessons/B1/Lesson_brief_JSONs/B1_Stage_2_Week_3_Day_4.json` as the schema example.
- Lesson payloads are curriculum briefs only. Do not put generated dialogues, answer keys, or learner chat history in them.
- Lesson payload `id` values are globally unique and level-prefixed, e.g. `b1_stage_1_week_1_day_1` and `b2_stage_4_week_4_day_7`.
- Preserve real Swedish characters and valid UTF-8. On Windows, default PowerShell reads can misrender UTF-8 without BOM; validate encoding by reading with explicit UTF-8 before reporting mojibake.
- Deep Research citation artifacts have been removed from the B2 progression document; do not reintroduce `turn...`, `cite`, or special marker glyphs into curriculum files.

## Non-obvious implementation details
- There are **two independent audio controllers** (Create vs History) in `ContentView.swift` to avoid cross-tab player state leakage.
- Lesson-engine stores/services:
  - `CurriculumStore`: loads bundled lesson payloads by level/stage/week/day.
  - `LessonGenerationStore`: persists generated dialogues/questions per lesson.
  - `LessonSessionStore`: persists phase, question progress, chat, mistakes, quiz, audio filename, and completion.
  - `OpenAITutorService`: separates Generator/Interactor calls from the existing generic `ChatStore`.
- iOS system controls are wired in `AudioPlayerController.swift` using:
  - `MPNowPlayingInfoCenter`
  - `MPRemoteCommandCenter`
  - `AVAudioSession` interruption handling.
- Background playback depends on explicit plist setup:
  - `SWE_Dialogs/Info.plist` contains `UIBackgroundModes = [audio]`.
  - App target uses `GENERATE_INFOPLIST_FILE = NO` and `INFOPLIST_FILE = Info.plist` in the `.pbxproj`.

## TTS model wiring
- Model picker is in Create tab (`ContentView.swift`).
- API call + model enum are in `GeminiTTSService.swift`.
- Current supported model IDs:
  - `gemini-2.5-flash-preview-tts`
  - `gemini-2.5-pro-preview-tts`
  - `gemini-3.1-flash-tts-preview`

## Persistence keys (UserDefaults/AppStorage)
- `gemini_api_key`
- `openai_api_key`
- `openai_chat_model`
- `tts_model_raw`
- `stage4_show_completed`
- `dialogs_selected_level`
- `dialogs_selected_stage`
- `dialogs_selected_week`
- `dialogs_completed_b1_stage_1`
- `dialogs_completed_b1_stage_2`
- `dialogs_completed_b1_stage_3`
- `dialogs_completed_b1_stage_4`
- `lessons_selected_level`
- `lessons_selected_stage`
- `lessons_selected_week`
- legacy Stage 4 migration keys still read on first launch:
  - `stage4_completed_days`
  - `stage4_prefilled_all_done_v1`
  - `stage4_week4_pending_migration_v1`

## Runtime documents
- `generated_lessons.json`: generated dialogue/questions keyed by lesson ID.
- `lesson_sessions.json`: lesson phase, accepted comprehension questions, mistake notes, quiz, chat messages, audio filename, completion.
- `lesson_audio/*.wav`: generated lesson audio files.
- Existing manual TTS files and `history.json` remain for the Create/History flow.

## Dialogs screen behavior
- Legacy "Dialogs" content lives in:
  - `Stage4Plan.swift`
  - `Stage4PlanView.swift`
  - `Stage4ProgressStore.swift`
- The legacy screen has level, stage, and week selectors above "Show completed".
- Copy action includes a formatted header like:
  - `B1, Stage 4, Week X, Day Y` + blank line + prompt.
- This hardcoded plan is now legacy. Keep the files until the new Lessons flow has been verified in Xcode and on-device/simulator.
- Keep the manual Create/History TTS flow during migration.

## Current lesson-engine implementation files
- `LessonModels.swift`
- `CurriculumStore.swift`
- `LessonGenerationStore.swift`
- `LessonSessionStore.swift`
- `OpenAITutorService.swift`
- `LessonView.swift`
- `FileStorage.swift` now also saves lesson audio under `lesson_audio/`.
- `ContentView.swift` now shows `LessonsHomeView` in the tab bar.
- `SWE_DialogsTests.swift` checks bundled curriculum count, uniqueness, and B1/B2 stage/week/day grid.

## Verification notes
- Local Windows workspace cannot run `xcodebuild`; run the quick build command on a macOS/Xcode environment.
- Local PowerShell resource checks passed for `Resources/curriculum.json`: schema version 1, 224 actual lessons, 224 unique IDs, 112 B1 and 112 B2.
- Full Xcode validation should include both app build and tests. The shared scheme at `SWE_Dialogs/SWE_Dialogs.xcodeproj/xcshareddata/xcschemes/SWE_Dialogs.xcscheme` marks test bundles non-parallelizable. Keep this: on the current local Xcode/CoreSimulator setup, default parallel test execution can clone simulators and fail runner launch with `NSMachErrorDomain Code=-308 (ipc/mig) server died`.
- If the full test command hangs while launching `SWE_DialogsUITests.xctrunner`, first boot the target simulator explicitly:
  - `xcrun simctl bootstatus <SIMULATOR_UDID> -b`
  - Then rerun tests. As a one-off fallback, add `-parallel-testing-enabled NO`; do not treat that simulator IPC failure as an app logic failure unless it reproduces with serial testing.

## Quick build command
- `cd SWE_Dialogs && xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' build`
- Full validation command:
  - `cd SWE_Dialogs && xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' test`
