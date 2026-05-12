# Project Runbook (Minimal)

## Current app state
- iOS SwiftUI app in `SWE_Dialogs/` that generates multi-speaker TTS dialogs via Gemini and plays local WAV output.
- Also includes a basic OpenAI text chat tab using Conversations API with local on-device chat persistence.
- The existing `Dialogs` tab is still a prompt-copy/progress checklist. It is a bridge from the old workflow, not the final product shape.

## Expansion direction
- The app is being expanded into a structured Swedish lesson engine for flexible levels such as B1 and B2.
- Target flow: select lesson position -> generate structured lesson -> generate Gemini audio from the dialogue -> listen -> answer comprehension questions -> chat about the dialogue -> do English-to-Swedish translation practice.
- Planned model split:
  - **Generator**: creates the lesson dialogue and 3 comprehension questions from a lesson payload.
  - **Interactor**: chats with the learner, checks comprehension, corrects Swedish, explains grammar, and generates the 5-sentence translation quiz when appropriate.
- Treat `Materials/` as the authoring area for prompts, progression documents, and lesson payload JSONs. The app may later bundle these as resources or merge them into a combined curriculum file.

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
- Use `Materials/Lessons/B1/Lesson_brief_JSONs/B1_Stage_2_Week_3_Day_4.json` as the schema example.
- Lesson payloads are curriculum briefs only. Do not put generated dialogues, answer keys, or learner chat history in them.
- Lesson payload `id` values are globally unique and level-prefixed, e.g. `b1_stage_1_week_1_day_1` and `b2_stage_4_week_4_day_7`.
- Preserve real Swedish characters and valid UTF-8. On Windows, default PowerShell reads can misrender UTF-8 without BOM; validate encoding by reading with explicit UTF-8 before reporting mojibake.
- Deep Research citation artifacts have been removed from the B2 progression document; do not reintroduce `turn...`, `cite`, or special marker glyphs into curriculum files.

## Non-obvious implementation details
- There are **two independent audio controllers** (Create vs History) in `ContentView.swift` to avoid cross-tab player state leakage.
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
- legacy Stage 4 migration keys still read on first launch:
  - `stage4_completed_days`
  - `stage4_prefilled_all_done_v1`
  - `stage4_week4_pending_migration_v1`

## Dialogs screen behavior
- "Dialogs" tab content lives in:
  - `Stage4Plan.swift`
  - `Stage4PlanView.swift`
  - `Stage4ProgressStore.swift`
- The screen now has level, stage, and week selectors above "Show completed".
- Copy action includes a formatted header like:
  - `B1, Stage 4, Week X, Day Y` + blank line + prompt.
- This hardcoded plan can be replaced later by generated/bundled lesson payload JSONs.
- The current Swift app does not yet load the 224 lesson payload JSONs; they are ready as authoring/runtime curriculum material for the next lesson-engine implementation step.

## Quick build command
- `cd SWE_Dialogs && xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' build`
