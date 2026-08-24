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
  The same backend also serves the usage dashboard through Caddy at `https://jahausage.dima-ib.xyz:8443/admin/usage`.
- Runtime secrets are loaded from `/home/dima/secure-secrets/llm.env`: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `APP_JWT_SECRET`, `APPLE_CLIENT_ID`.
- The usage dashboard is served by the backend at `/admin/usage` and is enabled with `SVENSKA_USAGE_DASHBOARD_TOKEN`.
  Per-user estimated cost is based on the actual model string recorded for each OpenAI request plus `OPENAI_USAGE_PRICE_OVERRIDES_JSON`; when adding or changing model IDs, update that price JSON too or token counts will still record but estimated dollars for the new model will be zero/blank. See `docs/BILLING.md`.
- Auth flow: iOS sends Apple `id_token` plus nonce to `/auth/apple`; backend verifies Apple JWKS/claims, upserts user by Apple `sub`, then returns an app JWT stored in iOS Keychain.
- Protected routes include `/lessons/artifacts/resolve`, its job-status route, legacy `/lessons/generate`, `/lessons/message`, `/tts/dialogue`, and authenticated lesson-session/Speaking routes.
- Speaking bootstrap is `POST /me/lesson-sessions/{lesson_id}/speaking/realtime-call` with raw SDP. The backend owns the Realtime model/session config and prompt, validates a 20-line reference-dialogue projection, and returns SDP plus a process-local lease token. The lease binds user, lesson, session, and OpenAI `call_id`; authenticated `DELETE`, the 10-minute server expiry task, and graceful backend shutdown all call `POST /v1/realtime/calls/{call_id}/hangup` where the provider ID is available. Before returning SDP, the backend starts a read-only WebSocket sideband for the same call and records each observed `response.done` as an idempotent `Speaking` usage event. Sideband failure logs `speaking_accounting_gap` without interrupting practice. The deployed service is intentionally one Uvicorn worker because V1 active-session/rate leases and sideband tasks are process-local.
- Routine VM work should use SSH user `codex`; that user can work in the repo and restart/status/log `svenska-api.service`, but cannot read secrets or Caddy config.

## Lesson Engine

- Curriculum authoring source lives under `Materials/`; bundled runtime resources live under `SWE_Dialogs/SWE_Dialogs/Resources/`.
- Lesson payload JSONs are curriculum briefs only. Do not put generated dialogues, answer keys, audio text, or learner chat history in them.
- `curriculum.json` is the bundled combined lesson resource. It currently contains 224 lessons: 112 B1 and 112 B2, with a 4 stage x 4 week x 7 day grid per level.
- Prompt source files live only in `Materials/`: `Shared_base_prompt.md` plus the Generator, lesson Interactor, Vocabulary Interactor, Evaluator, and `Speaking_prompt.md` role prompts. The backend reads them directly from `Materials/`; do not add duplicate bundled prompt copies.
- Generated dialogue TTS text is derived from parsed dialogue lines (`Anna: ...\nErik: ...`). Do not store `tts_text` as independent model output.

## Model Boundaries

- OpenAI Responses API, OpenAI Realtime bootstrap, and Gemini TTS calls happen on the backend.
- Speaking uses `gpt-realtime-2.1`, `marin`, semantic VAD/low eagerness, and `max_output_tokens=1024`. iOS uses exact-pinned `stasel/WebRTC` 151.0.0; OpenAI credentials never reach the device. The prompt receives a focused projection containing only difficulty, communicative goal, scenario, grammar-focus name/description, and rough opening/middle/ending, plus the validated `{speaker,text}` reference-dialogue projection. Generator-only examples, vocabulary chunks, quotas, comprehension questions, and translation quiz fields are excluded.
- Speaking V1 is strict guided/passive answer mode. The model acts as a natural conversation partner, owns progression, semantically counts 10 substantive learner replies (excluding requested correction repetitions), then gives a fixed two-sentence closing turn: one content-specific reaction and one farewell, with no question or new response opportunity. It then calls the client-handled `end_speaking_practice` tool. iOS waits for remaining farewell playback, closes WebRTC, invokes the authenticated DELETE/provider hangup path, and shows Practice complete; no client turn counter is used. The Speaking screen opens idle and starts microphone permission, synchronization, and WebRTC only after an explicit Start practice tap. The iOS client independently enforces the 10-minute maximum, fails connection establishment if the WebRTC data channel does not open within 25 seconds after SDP negotiation, gates the microphone until the tutor's opening playback ends, and ends on backgrounding.
- The read-only Speaking sideband durably stores user-scoped diagnostic events in `speaking_realtime_events`: complete `response.done` payloads (including assistant transcripts and function calls), completed/failed learner input-transcription events if the provider emits them, and VAD speech-start/stop boundaries. Streaming audio and transcript deltas are deliberately not stored. Speaking does not currently enable a separate input-transcription model, so learner transcripts are not expected until that is explicitly added; no evaluator consumes these records yet.
- Active model defaults are: Lesson Generator `gpt-5.6-sol`/medium, Lesson Interactor `gpt-5.6-sol`/low, Vocabulary Quiz `gpt-5.6-terra`/medium, Vocabulary Interactor `gpt-5.6-terra`/low, and Evaluator `gpt-5.6-sol`/medium. The Lesson Generator, vocabulary roles, and Evaluator are backend-owned settings; the compatibility Interactor request still carries its iOS-selected model.
- New lesson generation resolves the canonical lesson ID through immutable `lesson_artifacts`. Shared reuse requires an exact backend-computed recipe fingerprint covering the canonical curriculum payload, prompts, schema/validator contract, model, reasoning effort, token limit, and manual recipe version. `Regenerate Lesson` requests a private owner-scoped artifact. Existing sessions remain pinned to their artifact when configuration changes; legacy null-artifact sessions are not backfilled.
- Generator input is one lesson payload. Output is only a 20-line Anna/Erik dialogue plus 3 Swedish comprehension questions, then `LessonValidator` checks it in the app.
- Interactor calls are fresh Responses API requests, not Conversations API threads and not `previous_response_id` chains.
- Prompt-cache reuse is a design invariant: keep shared/stable context first, append-only prior history next, and per-turn state/latest input last; avoid duplicated context, preserve stable cache keys/retention, and verify changes with `openai_response_usage`. GPT-5.6 requests use explicit input-block breakpoints plus `prompt_cache_options={mode: explicit, ttl: 30m}`; older eligible models retain automatic caching and legacy retention.
- Interactor `prompt_cache_key` values are source-scoped by lesson/practice id hash to keep related turns routed together; `openai_response_usage.input_sections[].prompt_prefix_sha256` helps identify which stable prefix stopped matching without logging prompt text.
- Interactor input order is intentional for prompt caching:
  1. `course_context_json`
  2. `lesson_payload_json`
  3. `generated_dialogue_json`
  4. zero or more immutable `prior_lesson_chat_history_chunk_####_json` items
  5. `active_comprehension_questions_json`
  6. `active_translation_sentence_json`
  7. `lesson_state_json`
  8. `latest_user_message`
- `generated_dialogue_json` and prior chat history are sent before dynamic lesson state to preserve prompt-cache reuse as the conversation grows. History is split deterministically after assistant turns so completed chunks remain byte-stable; the current latest user message is excluded and sent separately as `latest_user_message`. `active_comprehension_questions_json` contains only the current learner-visible comprehension question until the app enters discussion. `active_translation_sentence_json` contains only the current learner-visible translation sentence; `lesson_state_json.translation_quiz.sentences_en` is trimmed to that same single active sentence for Interactor calls.
- `course_context_json` includes the app course level and the target Swedish explanation level: B2 lessons explain at B1, B1 lessons explain at A2.
- Interactor output is `assistant_text`, `state_patch`, and optional `translation_quiz`. The app validates patches and owns state transitions; the interactor cannot mark a lesson completed directly.
- After the third comprehension question, the app waits for the learner to tap Next before entering the `discussion` phase. That phase shows a local chat invitation to reread the dialog and ask clarification questions; the next Next tap requests the translation quiz.
- Vocabulary Interactor input keeps progression/selected targets/quiz/history before the active question, state, and latest learner message. The backend derives the first incomplete lesson and sends its level, stage, and cutoff; iOS cannot supply target IDs or progression.
- Evaluator input keeps metadata, bounded candidate catalog, current user state, source context, optional quiz, optional lookup events, and turn-numbered evidence in that order. The v3 candidate projection contains only target key, kind, display text, and description; its separate user-state projection contains only status and success streak for already-tracked keys. Lookup events are only for manual translation lookup jobs.
- Evaluator v3 returns every candidate key in `checked_target_keys` but emits `updates` only for results capable of changing persisted learning state. It omits no-evidence candidates and positive demonstrations for untracked candidates; demonstrations for tracked candidates remain actionable. The backend validates complete checked-key coverage before applying any update. Queued v1/v2 snapshots retain their legacy full-results schema and validation path.
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
- Speaking Realtime records are append-only rows keyed by user, lesson, practice session, and provider event/response identifiers. They survive lesson regeneration and are deleted with the owning user.
- Shared artifact WAV files: `SVENSKA_SHARED_AUDIO_DIRECTORY`, defaulting beside the SQLite file at `shared_lesson_audio/`. Back up this directory together with SQLite; DB metadata and files are one logical backup set.
- User learning state is relational in `user_learning_targets` with append-only `learning_evidence_events`; `evaluation_jobs` is the durable outbox, and `vocabulary_practice_sessions` stores the five-question quiz/chat lifecycle. Do not use the older migration-3 vocabulary/grammar tables for this loop.
- `Regenerate Lesson` replaces the generated dialogue/questions and resets that lesson session; this can orphan old chat/audio references by design.
- Treat `server_updated_at` in lesson-session responses as an opaque concurrency token on iOS. Preserve it byte-for-byte, allow one in-flight upload per lesson, coalesce newer local saves, and recover a `409` using the structured current-session payload before retrying newer local state.

## Audio

- Lesson audio uses authenticated, durable jobs: `POST /me/lesson-sessions/{lesson_id}/audio/generate` idempotently queues/resumes work, `GET .../audio/status` exposes durable state, and `GET .../audio` returns hash-bound WAV data with `ETag` and `X-Lesson-Audio-Content-Hash`. Artifact-pinned sessions share one global artifact audio job/file; legacy sessions retain the per-user BLOB path.
- `lesson_audio_jobs` uses leased claims, bounded retry/backoff, and `(user_id, lesson_id, content_hash)` uniqueness. The service-owned worker survives client cancellation and reclaims expired leases after restarts.
- Artifact `content_hash` is derived server-side from canonical Anna/Erik TTS text and the full current audio recipe fingerprint. A TTS recipe change reuses the lesson but queues one new matching WAV. iOS treats the server-returned hash as authoritative.
- Generated lesson audio is stored in the authenticated lesson-audio cache. Pruning retains the five newest completed lesson audios plus any active incomplete lesson or audio protected by an active job.
- Lesson-session state deliberately omits the local audio filename; iOS uses `has_audio` plus the authenticated audio endpoint to restore audio, while preserving or recovering a matching local lesson WAV when server metadata is temporarily absent.
- iOS persists the matching content hash with its local cache reference, automatically requests missing audio once, polls only while foregrounded, and exposes Generate/Retry without gating Back or Menu.
- Custom TTS continues to use synchronous `/tts/dialogue`. The legacy lesson `PUT .../audio` compatibility path remains until the minimum supported app version uses durable jobs.
- Audio operations: authenticated dashboard-token metrics are at `/admin/audio/metrics` and include shared artifact/job/file counts. Preview a bounded recent-user legacy backfill with `cd backend && PYTHONPATH=. .venv/bin/python scripts/backfill_lesson_audio_jobs.py --active-days 30 --limit 100`; add `--apply` to enqueue. Artifact invalidation/private GC uses `scripts/manage_lesson_artifacts.py`, which is dry-run unless `--apply` is present. Do not backfill legacy lessons into the shared cache.
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

# audio worker/storage diagnostics (requires dashboard token)
curl -fsS -H "X-Dashboard-Token: $SVENSKA_USAGE_DASHBOARD_TOKEN" \
  https://svenska-api.dima-ib.xyz:8443/admin/audio/metrics

# live backend health
curl -fsS https://svenska-api.dima-ib.xyz:8443/health
```

## TestFlight Release

- Increment the app target's `CURRENT_PROJECT_VERSION` before each upload. Keep `CODE_SIGN_STYLE = Automatic`; do not add `CODE_SIGN_IDENTITY = Apple Distribution` to the project or pass it to the archive command. With automatic signing, the archive may show `Apple Development`—that is expected; the App Store Connect export re-signs it for distribution.
- Run the iOS tests, then archive with automatic provisioning:

```bash
xcodebuild -project SWE_Dialogs/SWE_Dialogs.xcodeproj \
  -scheme SWE_Dialogs -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath /tmp/SWE_Dialogs.xcarchive \
  -allowProvisioningUpdates archive
```

- Export and upload with a temporary export-options plist containing `destination=upload`, `method=app-store-connect`, `signingStyle=automatic`, `teamID=77FQ75SS6P`, and `manageAppVersionAndBuildNumber=false`:

```bash
xcodebuild -exportArchive \
  -archivePath /tmp/SWE_Dialogs.xcarchive \
  -exportPath /tmp/SWE_Dialogs-upload \
  -exportOptionsPlist /tmp/ExportOptions-SWE_Dialogs.plist \
  -allowProvisioningUpdates
```

Confirm `Upload succeeded`, then wait for App Store Connect processing before expecting the build in TestFlight. Commit and push the build-number change, pull it to the VM with `scripts/vm-sync.sh`, and do not restart the backend for an iOS-only release.

If simulator test launch fails with `NSMachErrorDomain Code=-308`, `FBSOpenApplicationErrorDomain Code=6`, `Busy`, or "Application failed preflight checks", recover with `xcrun simctl shutdown all`, boot the target simulator, wait for `bootstatus -b`, then rerun tests with `-parallel-testing-enabled NO` if needed.
