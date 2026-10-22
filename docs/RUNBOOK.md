# Project Runbook

This repo is an iOS SwiftUI app for Swedish listening and lesson practice, plus the small backend used by the TestFlight build. Keep this file short: it should preserve non-obvious architecture and operating context, not duplicate what filenames or `rg` can show.

## Current Shape

- The app no longer stores OpenAI/Gemini keys on device. Users sign in with Apple, then the app calls the backend.
- Backend base URL is in `SWE_Dialogs/SWE_Dialogs/BackendConfig.swift`: `https://svenska-api.dima-ib.xyz:8443`.
- Swift provider service files are compatibility wrappers now: `OpenAITutorService` and `GeminiTTSService` call `BackendClient`, not provider APIs directly.
- Main tabs are `Lektioner`, `Ord` (vocabulary), and `Mer`, drawn as a custom key bar (`retroTabBar()` on each root screen; the system tab bar is hidden). `Ord` provides backend-owned five-question translation practices and practice history. `Mer` holds the account plate, sign-out, and the older custom TTS/history workflow (TTS routed through the backend).
- UI follows the retro design in [docs/design/README.md](./design/README.md): shared tokens/components live in `RetroTheme.swift` and `RetroObjects.swift`. Learner-facing labels are Swedish; curriculum metadata (level/stage/week, goals, grammar focus) is not shown to learners. Lesson numbers restart at 1 for each level.
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
- Speaking (the "Speaker") is turn-based: `POST /me/lesson-sessions/{lesson_id}/speaking/sessions` builds the server-owned Speaker instructions and returns a process-local session ID; each `POST .../speaking/sessions/{session_id}/turns` takes one learner WAV (no body for the tutor's opening) and streams NDJSON back: a `turn` line (`transcript`, `say`, `practice_complete`) followed by base64 24 kHz s16le `audio` lines and `done`; `DELETE .../speaking/sessions/{session_id}` ends it. Sessions also expire after 10 minutes. The deployed service is intentionally one Uvicorn worker because Speaking leases and conversation state are process-local.
- Routine VM work should use SSH user `codex`; that user can work in the repo and restart/status/log `svenska-api.service`, but cannot read secrets or Caddy config.

## Lesson Engine

- Curriculum authoring source lives under `Materials/`; bundled runtime resources live under `SWE_Dialogs/SWE_Dialogs/Resources/`.
- Lesson payload JSONs are curriculum briefs only. Do not put generated dialogues, answer keys, audio text, or learner chat history in them.
- `curriculum.json` is the bundled combined lesson resource. It currently contains 224 lessons: 112 B1 and 112 B2, with a 4 stage x 4 week x 7 day grid per level.
- Prompt source files live only in `Materials/`: `Shared_base_prompt.md` plus the Generator, lesson Interactor, Vocabulary Interactor, Evaluator, and `Speaker_prompt.md` role prompts. The backend reads them directly from `Materials/`; do not add duplicate bundled prompt copies.
- Generated dialogue TTS text is derived from parsed dialogue lines (`Anna: ...\nErik: ...`). Do not store `tts_text` as independent model output.

## Model Boundaries

- OpenAI Responses/transcription, ElevenLabs TTS, and Gemini TTS calls happen on the backend.
- A Speaking turn runs `gpt-transcribe` (Swedish, verbatim so learner errors survive) → Speaker `gpt-5.6-sol` at low reasoning → ElevenLabs `eleven_v4_turbo` with the library voice Elin (`4Ct5uMEndw4cJ7q0Jx0l`, needs a paid ElevenLabs plan and `ELEVENLABS_API_KEY`). Models and voice are `SVENSKA_SPEAKER_*` settings. The Speaker prompt receives a focused projection containing only difficulty, communicative goal, scenario, grammar-focus name/description, and rough opening/middle/ending, plus the validated `{speaker,text}` reference-dialogue projection; Speaker requests follow the same cache-first input order as the Interactor (instructions, append-only history chunks, `speaker_state_json`, latest transcript). A turn is committed to conversation state only after the first TTS audio arrives, so provider failures can be retried without double counting.
- Speaking is strict guided/passive answer mode. The Speaker returns `learner_turn`, `correcting`, and `say`; the backend counts 10 substantive learner replies (requested correction repetitions excluded), tells the model `closing_if_accepted`, and marks the practice complete when the closing reply needs no correction. The closing turn is two sentences (reaction + farewell) with no new question. iOS uses one push-to-talk handset button: olive with a green-tinted ring on the learner's turn, tap to record (orange, breathing ring), tap again to send, disabled while waiting for and playing the tutor, with no flashing effects; a "Visa lärarens ord" key reveals the latest reply text, hidden again on each new turn. Recordings under 0.5 s are discarded, recording auto-stops at 60 s, a failed learner turn returns the button without ending practice, and the screen ends on backgrounding or the 10-minute limit.
- Every committed Speaking turn is stored in `speaking_turns` (learner transcript, `learner_turn`, `correcting`, Speaker text, counted replies, completion); no evaluator consumes these records yet. Logs carry per-turn `stt_ms`, `llm_ms`, and `tts_first_audio_ms`.
- Active model defaults are: Lesson Generator `gpt-5.6-sol`/medium, Lesson Interactor `gpt-5.6-sol`/low, Vocabulary Quiz `gpt-5.6-terra`/medium, Vocabulary Interactor `gpt-5.6-terra`/low, and Evaluator `gpt-5.6-sol`/medium. The Lesson Generator, vocabulary roles, and Evaluator are backend-owned settings; the compatibility Interactor request still carries its iOS-selected model.
- New lesson generation resolves the canonical lesson ID through immutable `lesson_artifacts`. Shared reuse requires an exact backend-computed recipe fingerprint covering the canonical curriculum payload, prompts, schema/validator contract, model, reasoning effort, token limit, and manual recipe version. `Regenerate Lesson` requests a private owner-scoped artifact. Existing sessions remain pinned to their artifact when configuration changes; legacy null-artifact sessions are not backfilled.
- `Regenerate Lesson` uses the session-specific regeneration endpoint with a client-persisted operation key and the opaque session concurrency token. Provider generation remains request-driven; successful finalization atomically publishes the private artifact, resets and attaches the session, and queues its artifact audio job before responding. An interrupted request can reclaim its expired lease with the same operation key.
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
- Speaking turn rows are keyed by user, lesson, practice session, and turn index. They survive lesson regeneration and are deleted with the owning user.
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

# Simulator design review without Sign in with Apple (DEBUG builds only):
# launch with -UIPreviewUser; it uses local user 990001 and no backend token,
# so seed Documents/users/990001/{generated_lessons,lesson_sessions}.json to see lesson screens.
xcrun simctl launch --terminate-running-process booted dima.SWE-Dialogs -UIPreviewUser

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
