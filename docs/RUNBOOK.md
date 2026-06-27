# Project Runbook

This repo is an iOS SwiftUI app for Swedish listening and lesson practice, plus the small backend used by the TestFlight build. Keep this file short: it should preserve non-obvious architecture and operating context, not duplicate what filenames or `rg` can show.

## Current Shape

- The app no longer stores OpenAI/Gemini keys on device. Users sign in with Apple, then the app calls the backend.
- Backend base URL is in `SWE_Dialogs/SWE_Dialogs/BackendConfig.swift`: `https://svenska-api.dima-ib.xyz:8443`.
- Swift provider service files are compatibility wrappers now: `OpenAITutorService` and `GeminiTTSService` call `BackendClient`, not provider APIs directly.
- Main tabs are `Lessons`, `Vocabulary`, `Settings`, and `More`. `Vocabulary` provides backend-owned five-question translation practices and practice history. `Settings` is account/sign-out only; `More` keeps the older custom TTS/history workflow but routes TTS through the backend.
- Legacy hardcoded dialog-plan files (`Stage4Plan.swift`, `Stage4PlanView.swift`, `Stage4ProgressStore.swift`) remain in the project but are not shown in the tab bar.

## Backend

- FastAPI backend lives under `backend/app`.
- VM service: `svenska-api.service`, bound locally on `127.0.0.1:8100`; Caddy exposes it publicly on `https://svenska-api.dima-ib.xyz:8443`.
- Runtime secrets are loaded from `/home/dima/secure-secrets/llm.env`: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `APP_JWT_SECRET`, `APPLE_CLIENT_ID`.
- The usage dashboard is served by the backend at `/admin/usage` and is enabled with `SVENSKA_USAGE_DASHBOARD_TOKEN`.
  Per-user estimated cost is based on the actual model string recorded for each OpenAI request plus `OPENAI_USAGE_PRICE_OVERRIDES_JSON`; when adding or changing model IDs, update that price JSON too or token counts will still record but estimated dollars for the new model will be zero/blank. See `docs/BILLING.md`.
- Auth flow: iOS sends Apple `id_token` plus nonce to `/auth/apple`; backend verifies Apple JWKS/claims, upserts user by Apple `sub`, then returns an app JWT stored in iOS Keychain.
- Protected routes: `/lessons/generate`, `/lessons/message`, `/tts/dialogue`.
- Routine VM work should use SSH user `codex`; that user can work in the repo and restart/status/log `svenska-api.service`, but cannot read secrets or Caddy config.

## Lesson Engine

- Curriculum authoring source lives under `Materials/`; bundled runtime resources live under `SWE_Dialogs/SWE_Dialogs/Resources/`.
- Lesson payload JSONs are curriculum briefs only. Do not put generated dialogues, answer keys, audio text, or learner chat history in them.
- `curriculum.json` is the bundled combined lesson resource. It currently contains 224 lessons: 112 B1 and 112 B2, with a 4 stage x 4 week x 7 day grid per level.
- Prompt source files live only in `Materials/`: `Shared_base_prompt.md` plus the Generator, lesson Interactor, Vocabulary Interactor, and Evaluator role prompts. The backend reads them directly from `Materials/`; do not add duplicate bundled prompt copies.
- Generated dialogue TTS text is derived from parsed dialogue lines (`Anna: ...\nErik: ...`). Do not store `tts_text` as independent model output.

## Model Boundaries

- OpenAI Responses API and Gemini TTS calls happen on the backend.
- Generator input is one lesson payload. Output is only a 20-line Anna/Erik dialogue plus 3 Swedish comprehension questions, then `LessonValidator` checks it in the app.
- Interactor calls are fresh Responses API requests, not Conversations API threads and not `previous_response_id` chains.
- Prompt-cache reuse is a design invariant: keep shared/stable context first, append-only prior history next, and per-turn state/latest input last; avoid duplicated context, preserve stable cache keys/retention, and verify changes with `openai_response_usage`.
- Interactor `prompt_cache_key` values are source-scoped by lesson/practice id hash to keep related turns routed together; `openai_response_usage.input_sections[].prompt_prefix_sha256` helps identify which stable prefix stopped matching without logging prompt text.
- Interactor input order is intentional for prompt caching:
  1. `course_context_json`
  2. `lesson_payload_json`
  3. `generated_dialogue_json`
  4. `prior_lesson_chat_history_json`
  5. `active_comprehension_questions_json`
  6. `active_translation_sentence_json`
  7. `lesson_state_json`
  8. `latest_user_message`
- `generated_dialogue_json` and prior chat history are sent before dynamic lesson state to preserve prompt-cache reuse as the conversation grows. `prior_lesson_chat_history_json` excludes the current latest user message, which is sent separately as `latest_user_message`. `active_comprehension_questions_json` contains only the current learner-visible comprehension question until the app enters discussion. `active_translation_sentence_json` contains only the current learner-visible translation sentence; `lesson_state_json.translation_quiz.sentences_en` is trimmed to that same single active sentence for Interactor calls.
- `course_context_json` includes the app course level and the target Swedish explanation level: B2 lessons explain at B1, B1 lessons explain at A2.
- Interactor output is `assistant_text`, `state_patch`, and optional `translation_quiz`. The app validates patches and owns state transitions; the interactor cannot mark a lesson completed directly.
- After the third comprehension question, the app waits for the learner to tap Next before entering the `discussion` phase. That phase shows a local chat invitation to reread the dialog and ask clarification questions; the next Next tap requests the translation quiz.
- Vocabulary Interactor input keeps progression/selected targets/quiz/history before the active question, state, and latest learner message. The backend derives the first incomplete lesson and sends its level, stage, and cutoff; iOS cannot supply target IDs or progression.
- Evaluator input keeps metadata, bounded candidate catalog, current user state, source context, optional quiz, optional lookup events, and turn-numbered evidence in that order. Lookup events are only for manual translation lookup jobs.
- Lesson and vocabulary-practice completion enqueue immutable evaluator snapshots transactionally. Manual text-selection translation requests enqueue bounded `translation_lookup` Evaluator snapshots with `lookup_events_json`. A background worker validates bounded Evaluator results and applies deterministic active/resolved mastery transitions; evaluation never blocks completion.
- `lookup_requested` is a non-punitive vocabulary signal used for practice priority; it does not count as failed production, increment struggle count, reset success streak, or resolve mastery.
- On app launch, iOS additively reconciles locally completed curriculum lesson IDs through `/me/lesson-progress/sync`. The backend validates IDs and still derives level/stage itself; this backfills pre-server progress without creating historical Evaluator jobs.

## Persistence

- iOS document files:
  - `generated_lessons.json`: generated lessons keyed by lesson ID.
  - `lesson_sessions.json`: lesson state plus per-lesson chat history.
  - `lesson_audio/*.wav`: generated lesson audio.
  - `history.json` plus root-level `dialog-*.wav`: older custom TTS history.
- Backend SQLite file: `backend/data/svenska.db`.
- User learning state is relational in `user_learning_targets` with append-only `learning_evidence_events`; `evaluation_jobs` is the durable outbox, and `vocabulary_practice_sessions` stores the five-question quiz/chat lifecycle. Do not use the older migration-3 vocabulary/grammar tables for this loop.
- `Regenerate Lesson` replaces the generated dialogue/questions and resets that lesson session; this can orphan old chat/audio references by design.
- Treat `server_updated_at` in lesson-session responses as an opaque concurrency token on iOS. Preserve it byte-for-byte, allow one in-flight upload per lesson, coalesce newer local saves, and recover a `409` using the structured current-session payload before retrying newer local state.

## Audio

- Lesson audio and custom TTS audio call backend `/tts/dialogue`, which returns WAV audio generated by Gemini TTS.
- Background playback depends on `SWE_Dialogs/Info.plist` containing `UIBackgroundModes = [audio]`. The target uses the explicit plist (`GENERATE_INFOPLIST_FILE = NO`).
- `ContentView.swift` keeps separate audio controllers for lesson/custom/history flows to avoid playback state leaking between screens.

## Encoding

- Preserve real Swedish characters and valid UTF-8. Lesson JSONs may be UTF-8 without BOM.
- On Windows, default PowerShell reads can misrender Swedish characters. Validate with explicit UTF-8 decoding before reporting mojibake.
- Do not reintroduce old Deep Research citation artifacts such as `turn...`, `cite`, or special citation marker glyphs into curriculum files.

## Verification

```bash
# iOS quick build
cd SWE_Dialogs
xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' build

# iOS full validation
xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' test

# backend tests
cd ../backend
PYTHONPATH=. .venv/bin/pytest -q tests

# live backend health
curl -fsS https://svenska-api.dima-ib.xyz:8443/health
```

If simulator test launch fails with `NSMachErrorDomain Code=-308`, `FBSOpenApplicationErrorDomain Code=6`, `Busy`, or "Application failed preflight checks", recover with `xcrun simctl shutdown all`, boot the target simulator, wait for `bootstatus -b`, then rerun tests with `-parallel-testing-enabled NO` if needed.
