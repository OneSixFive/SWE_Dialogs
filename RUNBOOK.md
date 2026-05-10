# Project Runbook (Minimal)

## What this app is
- iOS SwiftUI app in `SWE_Dialogs/` that generates multi-speaker TTS dialogs via Gemini and plays local WAV output.
- Also includes a basic OpenAI text chat tab using Conversations API with local on-device chat persistence.

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

## Quick build command
- `cd SWE_Dialogs && xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' build`
