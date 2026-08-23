# SWE_Dialogs — Shared Lesson and Audio Artifacts Implementation Plan

**Repository:** `OneSixFive/SWE_Dialogs`

**Architecture status:** approved product decisions; ready for implementation

**Date:** 2026-08-23 (Stockholm)

**Rollout:** cold shared cache; no historical backfill

---

## 1. Goal

Make a generated lesson reusable across users when they request the same canonical curriculum lesson and the stored artifact was produced with the backend's current complete generation configuration.

The canonical identity is the existing lesson ID, for example:

```text
b1_stage_1_week_1_day_1
```

That ID uniquely represents UI course level (`B1` or `B2`), stage, week, and day. Do not use `course_position.level` as the cache key; that field represents the instructional target level and can contain values such as `A2`.

The visible behavior remains unchanged:

- The button continues to say **Generate Lesson**.
- A current shared artifact is loaded instead of making another provider request.
- The lesson appears as soon as its text artifact is ready.
- Audio downloads immediately when already available.
- If audio is missing, one durable shared job generates it while the lesson remains usable and the UI shows its existing preparing/loading state.
- **Regenerate Lesson** always creates a private alternative for that user and never replaces the shared artifact.

The core architecture principle is:

> Generated lesson and audio content can be shared; learner state can never be shared.

---

## 2. Approved product decisions

| Area | Decision |
|---|---|
| Configuration authority | Backend is authoritative for lesson and audio generation configuration |
| Shared key | Canonical lesson ID plus a complete current recipe fingerprint |
| Lesson compatibility | Includes model, reasoning effort, prompts, schema/validator contract, curriculum payload, and semantic request parameters |
| Audio compatibility | Includes exact dialogue text and the complete current TTS recipe |
| Existing sessions after a config change | Stay pinned to their existing immutable artifact |
| Normal Generate | Resolve or create the current shared artifact |
| Regenerate Lesson | Generate a new private artifact owned by that user |
| Shared publication | Immediate after successful provider response and validation |
| Historical data | Do not backfill into the shared cache |
| Audio miss | Show the lesson immediately; run one durable shared audio job |
| Storage | SQLite metadata plus content-addressed WAV files on the VM |
| User-facing cache indication | None; cache reuse is invisible |

---

## 3. Scope boundaries

### In scope

- Backend-owned lesson generator and TTS settings.
- Deterministic recipe fingerprints and artifact provenance.
- Immutable shared and private lesson artifacts.
- Per-user lesson-session references to artifacts.
- Globally deduplicated shared audio jobs and files.
- Owner-scoped private regenerated lessons and audio.
- Single-flight behavior for simultaneous requests.
- Backward-compatible rollout for existing TestFlight builds.
- Cache observability, invalidation, garbage collection, and operational documentation.

### Out of scope

- Sharing learner messages, progress, translation quiz state, completion, evaluation evidence, or Speaking state.
- Migrating existing generated lessons or audio into shared artifacts.
- Automatically replacing an existing user's lesson when configuration changes.
- Letting an ordinary user replace or invalidate a shared artifact.
- Showing cache-hit messaging in the iOS UI.
- Object storage or CDN integration in V1.
- Pre-generating all 224 curriculum lessons.

---

## 4. Current-state gaps

The current design cannot safely implement sharing by changing a database lookup from `user_id + lesson_id` to `lesson_id` alone.

### Lesson gaps

- `/lessons/generate` accepts the full curriculum payload, model, and reasoning effort from iOS.
- The stored `GeneratedLesson` records the requested model but not reasoning effort, prompt hashes, curriculum hash, generator schema version, or provider-reported model.
- Generated lesson JSON is copied into each user's `lesson_sessions` row.
- Session upload validation checks the lesson/dialogue shape but does not prove that the content came from the current canonical generator request.
- Two simultaneous users can independently generate the same lesson.

### Audio gaps

- The existing audio hash correctly includes canonical dialogue text, TTS model, and voice-config version.
- Audio cache rows and jobs are nevertheless keyed by `user_id`, so identical audio can be generated and stored more than once.
- TTS identity constants are duplicated between iOS and the backend.
- WAV bytes are stored as per-user SQLite BLOBs.

### Configuration gap

The OpenAI Responses API treats model, reasoning, instructions, structured output, and output limits as separate request inputs. The provider-returned model therefore cannot serve as a complete application artifact identity. The application must record provider provenance and calculate its own deterministic recipe fingerprint. See the [official OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).

---

## 5. Target topology

```text
Generate Lesson tap
        │
        ▼
Authenticated resolve request containing only canonical lesson_id
        │
        ▼
Backend loads canonical curriculum payload and current backend config
        │
        ├── compute current lesson recipe fingerprint
        │
        ├── current shared artifact exists ───────────────┐
        │                                                 │
        └── no artifact: claim one durable global job     │
                    │                                     │
                    ├── one worker calls OpenAI           │
                    ├── validate result                   │
                    └── publish immutable artifact ───────┤
                                                          ▼
                              bind artifact to user's lesson session
                                                          │
                              ┌───────────────────────────┴─────────────┐
                              ▼                                         ▼
                       render lesson                         resolve artifact audio
                                                                    │
                                           ┌────────────────────────┴──────────┐
                                           ▼                                   ▼
                                    matching WAV exists             one durable audio job
                                           │                                   │
                                           └──────── download when ready ──────┘
```

User lesson state remains in `lesson_sessions`. Shared content is stored separately and referenced by artifact ID.

---

## 6. Terminology and invariants

### Canonical lesson

A curriculum entry loaded by the backend using its stable `lesson_id`. The backend must use its own bundled/server-side curriculum payload, not a client-supplied payload, when creating a shared or private artifact.

### Lesson recipe

The normalized set of every input that can semantically affect generated lesson output.

### Lesson recipe fingerprint

SHA-256 of a versioned, canonical JSON representation of the lesson recipe. Only an artifact whose `lesson_id` and fingerprint both match the backend's current values can be propagated as a shared hit.

### Lesson artifact

An immutable validated generated dialogue and comprehension-question set plus provenance. It is either:

- `shared`: available to every authenticated user resolving that lesson while the recipe is current; or
- `private`: available only to its owner and created by **Regenerate Lesson**.

### Audio recipe

The normalized backend-owned configuration used to transform canonical dialogue text into a WAV.

### Audio identity

SHA-256 of the canonical dialogue-text hash and audio recipe fingerprint. Audio is compatible only when both match.

### Session pin

A per-user `lesson_sessions` reference to one immutable lesson artifact. A configuration change never rewrites that reference.

### Required invariants

1. Shared lookup never uses model name alone.
2. Private artifacts are never returned to another user.
3. A user session references exactly one current lesson artifact after using the new flow.
4. Existing sessions remain valid even after their artifact stops being the current shared recipe.
5. Audio is served only for the artifact pinned to the authenticated user's session.
6. Audio bytes must match the server-returned content hash and ETag.
7. One shared lesson recipe can have at most one publishable shared artifact.
8. One artifact/audio-recipe combination can have at most one active audio job.
9. Client-supplied payloads or model settings can never populate the shared cache.
10. Prompt-cache input order and explicit GPT-5.6 cache breakpoints remain unchanged.

---

## 7. Backend-owned configuration

Add lesson-generator settings to `backend/app/config.py`:

```text
OPENAI_LESSON_GENERATOR_MODEL
OPENAI_LESSON_GENERATOR_REASONING_EFFORT
SVENSKA_LESSON_GENERATOR_RECIPE_VERSION
```

Add TTS settings rather than keeping them as module-only constants:

```text
GEMINI_LESSON_TTS_MODEL
SVENSKA_LESSON_TTS_VOICE_CONFIG_VERSION
SVENSKA_LESSON_TTS_RECIPE_VERSION
SVENSKA_SHARED_AUDIO_DIRECTORY
```

Defaults should initially match current production:

```text
Lesson Generator: gpt-5.6-sol / medium
TTS: gemini-2.5-pro-preview-tts
Voice config: anna-aoede_erik-enceladus_v1
```

The backend passes these values to providers. New iOS requests do not select a model or reasoning effort.

Keep the existing client fields and legacy endpoint temporarily so older TestFlight builds continue working. Treat that legacy path as private, user-scoped generation and never publish its result into the shared artifact tables.

Whenever an active model ID changes, update `OPENAI_USAGE_PRICE_OVERRIDES_JSON` according to `docs/BILLING.md` before restarting the backend.

---

## 8. Fingerprint specifications

Create one shared canonical-JSON helper in the backend:

- UTF-8 encoding;
- recursively sorted object keys;
- stable array order;
- no insignificant whitespace;
- explicit recipe schema version;
- SHA-256 lowercase hexadecimal output.

Do not construct fingerprints with ad hoc newline concatenation once recipe objects contain more than a few fields.

### 8.1 Lesson recipe document

The V1 lesson recipe must include at least:

```json
{
  "recipe_schema_version": 1,
  "manual_recipe_version": "lesson_generator_v2",
  "provider": "openai",
  "requested_model": "gpt-5.6-sol",
  "reasoning_effort": "medium",
  "max_output_tokens": 4000,
  "shared_base_prompt_sha256": "...",
  "generator_prompt_sha256": "...",
  "response_schema_sha256": "...",
  "validator_contract_version": "generated_lesson_v2",
  "curriculum_payload_sha256": "...",
  "lesson_id": "b1_stage_1_week_1_day_1"
}
```

Also include any future semantically relevant parameter when it becomes active, including `temperature`, `top_p`, verbosity, tool definitions, or other response-format settings.

Do not include transport- or cache-only values that should not affect generated content, such as:

- `prompt_cache_key`;
- prompt-cache retention/TTL;
- request timeout;
- user ID or safety identifier;
- request ID;
- service tier when it does not alter requested semantics.

The manual recipe version is an explicit operational escape hatch. Bump it when a behavioral change cannot be represented by one of the hashed inputs or when all shared artifacts must be invalidated intentionally.

### 8.2 Lesson artifact provenance

Record the complete recipe document or its relevant components, not only the final fingerprint:

- requested model;
- provider-reported response model, when present;
- reasoning effort;
- manual recipe version;
- prompt hashes;
- schema hash;
- validator contract version;
- curriculum hash;
- provider response/request ID when available;
- creating user ID for audit/cost attribution;
- generation timestamp.

Compatibility is decided by the application recipe fingerprint. The provider-reported model is retained as provenance and for diagnosing aliases or provider-side model changes. If exact provider revision pinning becomes required, use a pinned model identifier or bump the manual recipe version; it cannot be inferred safely without making a provider call.

### 8.3 Audio recipe document

The audio recipe must include at least:

```json
{
  "recipe_schema_version": 1,
  "manual_recipe_version": "lesson_tts_v2",
  "provider": "gemini",
  "requested_model": "gemini-2.5-pro-preview-tts",
  "voice_config_version": "anna-aoede_erik-enceladus_v1",
  "text_normalization_version": "anna_erik_dialogue_v1",
  "output_container": "wav",
  "output_encoding": "pcm",
  "channel_configuration": "provider_default"
}
```

If sample rate, channel count, speaking rate, style instruction, safety configuration, or another provider parameter is explicitly controlled later, add it to the recipe.

Calculate:

```text
dialogue_text_hash = SHA256(canonical Anna/Erik TTS text)
audio_recipe_fingerprint = SHA256(canonical audio recipe JSON)
audio_content_hash = SHA256(dialogue_text_hash + ":" + audio_recipe_fingerprint)
```

The backend is authoritative for all three values. iOS persists and compares the returned `audio_content_hash`; it no longer duplicates TTS model/voice constants or predicts the hash itself.

---

## 9. Database model

Use the next available additive SQLite migration. Do not alter or backfill existing session/audio rows into the new artifact system.

### 9.1 `lesson_artifacts`

Suggested columns:

```text
id                         TEXT PRIMARY KEY
lesson_id                  TEXT NOT NULL
scope                      TEXT NOT NULL CHECK ('shared', 'private')
owner_user_id              INTEGER NULL REFERENCES users(id)
recipe_fingerprint         TEXT NOT NULL
recipe_json                TEXT NOT NULL
lesson_content_hash        TEXT NOT NULL
generated_lesson_json      TEXT NOT NULL
requested_model            TEXT NOT NULL
provider_model             TEXT NULL
reasoning_effort           TEXT NOT NULL
provider_request_id        TEXT NULL
created_by_user_id         INTEGER NOT NULL REFERENCES users(id)
created_at                 TEXT NOT NULL
invalidated_at             TEXT NULL
invalidation_reason        TEXT NULL
```

Constraints:

- `scope='shared'` requires `owner_user_id IS NULL`.
- `scope='private'` requires `owner_user_id IS NOT NULL`.
- Partial unique index on `(lesson_id, recipe_fingerprint)` for non-invalidated shared rows.
- Index `(owner_user_id, lesson_id, created_at)` for private artifacts.
- Index `lesson_content_hash` for diagnostics and audio joins.

Artifacts are immutable. Invalidation updates only invalidation metadata. Generating a replacement creates a new row.

### 9.2 `lesson_generation_jobs`

Suggested columns:

```text
id                         INTEGER PRIMARY KEY AUTOINCREMENT
lesson_id                  TEXT NOT NULL
recipe_fingerprint         TEXT NOT NULL
scope                      TEXT NOT NULL CHECK ('shared', 'private')
owner_user_id              INTEGER NULL
requested_by_user_id       INTEGER NOT NULL REFERENCES users(id)
status                     TEXT NOT NULL CHECK ('pending', 'running', 'succeeded', 'failed', 'superseded')
attempt_count              INTEGER NOT NULL DEFAULT 0
next_attempt_at            TEXT NOT NULL
lease_expires_at           TEXT NULL
artifact_id                TEXT NULL REFERENCES lesson_artifacts(id)
last_error_code            TEXT NULL
last_error_summary         TEXT NULL
created_at                 TEXT NOT NULL
updated_at                 TEXT NOT NULL
completed_at               TEXT NULL
```

Constraints:

- One shared job identity per `(lesson_id, recipe_fingerprint, scope='shared')`.
- Private regeneration jobs are never deduplicated across users or separate taps.
- A lease permits recovery after process restart.
- Completing a stale recipe job may retain its immutable artifact for audit, but it must not be returned as the current shared result if backend configuration changed while the job ran.

### 9.3 `lesson_audio_artifacts`

Suggested columns:

```text
id                         TEXT PRIMARY KEY
lesson_artifact_id         TEXT NOT NULL REFERENCES lesson_artifacts(id)
scope                      TEXT NOT NULL CHECK ('shared', 'private')
owner_user_id              INTEGER NULL
dialogue_text_hash         TEXT NOT NULL
audio_recipe_fingerprint   TEXT NOT NULL
content_hash               TEXT NOT NULL
relative_file_path         TEXT NOT NULL
content_type               TEXT NOT NULL DEFAULT 'audio/wav'
byte_count                 INTEGER NOT NULL
provider                   TEXT NOT NULL
model                      TEXT NOT NULL
voice_config_version       TEXT NOT NULL
generated_at               TEXT NOT NULL
created_at                 TEXT NOT NULL
updated_at                 TEXT NOT NULL
```

Constraints:

- Unique `(lesson_artifact_id, audio_recipe_fingerprint)`.
- Unique `content_hash` may deduplicate the physical file, but authorization continues through artifact scope.
- Private audio metadata is owner-scoped and never satisfies another user's shared lookup.

### 9.4 `lesson_audio_jobs`

Evolve the job implementation so new artifact jobs are keyed by `lesson_artifact_id + audio_recipe_fingerprint`, not `user_id + lesson_id + content_hash`.

For rollback compatibility, either:

1. add nullable artifact columns to the existing table and maintain both legacy and artifact job paths; or
2. create `artifact_audio_jobs` and leave `lesson_audio_jobs` untouched until old client support is removed.

The second option is safer for an incremental rollout because existing migration-11 behavior and tests remain isolated.

### 9.5 `lesson_sessions`

Add:

```text
lesson_artifact_id TEXT NULL REFERENCES lesson_artifacts(id)
```

Keep `generated_lesson_json` during the compatibility period:

- Legacy sessions continue using inline JSON with a null artifact reference.
- New sessions pin `lesson_artifact_id`.
- API responses can project `generated_lesson_json` from the referenced artifact so existing lesson/interactor code receives the same logical content.
- New writes should not duplicate artifact JSON into the session row unless a compatibility requirement demands it.

Do not attempt to infer artifact references for legacy rows. That would be backfilling and their complete generation recipe is unknowable.

---

## 10. Content-addressed audio storage

Default directory:

```text
backend/data/shared_lesson_audio/
```

Suggested layout:

```text
shared_lesson_audio/<first-two-hash-characters>/<content_hash>.wav
```

Requirements:

- Store only a validated relative path in SQLite.
- Derive the destination from a strict lowercase hexadecimal hash; never accept a client file path.
- Write to a temporary file in the destination directory, flush, and atomically rename only after provider success and WAV validation.
- Insert/update metadata transactionally after the final file exists.
- If the database transaction fails, remove the newly written unreferenced file during cleanup.
- If a file is missing for an otherwise-ready metadata row, treat audio as missing and safely enqueue repair.
- Add the directory to operational backup/restore documentation and keep it out of Git.
- Report file count, total bytes, missing files, and orphan files in diagnostics.

The present production average is approximately 2.9 MB per cached WAV. At that size, one version for all 224 curriculum lessons is roughly 0.65 GB, which fits the VM's current free disk space but still requires monitoring and garbage collection.

---

## 11. API contracts

Use a new artifact-resolution contract rather than changing legacy `/lessons/generate` in place. This makes the trust boundary explicit and preserves old TestFlight behavior.

### 11.1 Resolve or create the shared lesson

```http
POST /lessons/artifacts/resolve
Authorization: Bearer <app JWT>
Content-Type: application/json

{
  "lesson_id": "b1_stage_1_week_1_day_1",
  "mode": "shared"
}
```

Rules:

1. Authenticate the user.
2. Resolve the canonical payload by lesson ID from the backend curriculum.
3. Compute the current recipe fingerprint from backend-owned inputs.
4. Return the non-invalidated shared artifact on an exact hit.
5. Otherwise idempotently create/resume the shared generation job.
6. Return `202` with job status while generation is pending/running.
7. Return the artifact after publication.

Suggested ready response:

```json
{
  "resolution": "cache_hit",
  "artifact": {
    "id": "...",
    "lesson_id": "b1_stage_1_week_1_day_1",
    "scope": "shared",
    "recipe_fingerprint": "...",
    "generated_lesson": {}
  },
  "audio": {
    "status": "ready",
    "content_hash": "..."
  }
}
```

`resolution` may be `cache_hit` or `generated`; it is diagnostic and must not produce different visible UI copy.

Suggested queued response:

```json
{
  "resolution": "queued",
  "job_id": 123,
  "status": "pending",
  "retry_after_seconds": 1
}
```

### 11.2 Poll lesson generation

```http
GET /lessons/artifacts/jobs/{job_id}
```

Authorization rules:

- Any authenticated user waiting for the same shared recipe may observe its bounded public status.
- A private job is visible only to its owner.
- Error responses expose stable error codes and retryability, not provider bodies or prompt content.

### 11.3 Private regeneration

Use the same resolve endpoint with:

```json
{
  "lesson_id": "b1_stage_1_week_1_day_1",
  "mode": "private"
}
```

Rules:

- Always create a fresh private generation job using the current backend recipe.
- Do not reuse or replace the shared lesson artifact.
- Do not return the artifact to any other user.
- Once ready, replacing the session pin uses the existing destructive regeneration semantics: reset lesson chat/progress and detach old audio.

### 11.4 Bind a lesson artifact to a user session

Extend the lesson-session upsert request with:

```json
{
  "lesson_artifact_id": "..."
}
```

Validation:

- Artifact `lesson_id` must match the path.
- Shared artifacts may be adopted by any authenticated user.
- Private artifacts require `owner_user_id == current_user.user_id`.
- An invalidated shared artifact may remain attached to an existing pinned session but cannot be newly adopted.
- Once an artifact ID is supplied, ignore/reject conflicting client-generated lesson JSON.
- Preserve current `server_updated_at` concurrency behavior.

The backend response continues including a `generated_lesson` projection for the app and existing interactor contracts.

### 11.5 Audio endpoints

Keep the current authenticated per-session URL shape:

```text
POST /me/lesson-sessions/{lesson_id}/audio/generate
GET  /me/lesson-sessions/{lesson_id}/audio/status
GET  /me/lesson-sessions/{lesson_id}/audio
```

Change their new-flow implementation to:

1. load the user's pinned artifact;
2. compute the current audio recipe;
3. resolve shared/private audio according to artifact scope;
4. enqueue/resume one artifact-scoped durable job if missing;
5. serve bytes from the content-addressed file;
6. return `ETag` and `X-Lesson-Audio-Content-Hash` as today.

Legacy inline-lesson sessions continue through the old per-user cache/job path during the compatibility window.

---

## 12. Canonical curriculum trust boundary

Extend `LearningCatalog` or introduce a dedicated canonical curriculum repository that retains the complete `LessonPayload` for each lesson ID.

For artifact generation:

- accept only `lesson_id` from iOS;
- reject unknown lesson IDs;
- load the complete payload server-side;
- serialize it with the same stable snake-case transformation used for the current generator input;
- hash that exact normalized payload for the recipe;
- pass that exact payload to the model;
- validate the returned lesson ID against it.

This avoids shared-cache poisoning by altered payloads from modified or outdated clients.

Do not change Interactor input ordering while implementing this work. Continue sending:

1. course context;
2. canonical lesson payload;
3. pinned generated dialogue;
4. immutable prior history chunks;
5. active comprehension question;
6. active translation sentence;
7. lesson state;
8. latest user message.

---

## 13. Generation and publication workflow

### Shared lesson miss

1. Resolve current lesson recipe.
2. In a short `BEGIN IMMEDIATE` transaction, find/create the unique shared job.
3. Return the existing job when another request already owns it.
4. Worker claims the job with a bounded lease.
5. Read prompts and canonical curriculum inputs for the job's stored recipe.
6. Call OpenAI with existing prompt-cache breakpoints/options preserved.
7. Record OpenAI usage against `requested_by_user_id` because that request caused the actual provider cost.
8. Capture provider-reported model and request ID.
9. Run schema and semantic validation.
10. Recompute/verify the job recipe inputs before publication.
11. Insert the immutable artifact and mark the job succeeded transactionally.
12. If the backend's current recipe changed during the job, do not expose the result as a current shared hit; the next resolve creates/resumes the new current job.

### Shared lesson hit

1. Load artifact by `lesson_id + current_recipe_fingerprint`.
2. Confirm it is non-invalidated.
3. Return it without an OpenAI request or OpenAI usage event.
4. Log an application-level cache-hit event.

### Private regeneration

1. Resolve the current recipe.
2. Always create a new owner-scoped job; do not look up the shared artifact as the lesson result.
3. Generate and validate the lesson.
4. Store it as an immutable private artifact.
5. Replace that user's session pin only after generation succeeds.
6. Preserve the user's existing lesson if private generation fails.

---

## 14. Validation before immediate shared publication

Immediate publishing makes validation more important because one bad artifact affects every subsequent new user.

Preserve all existing checks and strengthen them with bounded canonical validation:

- returned `lesson_id` exactly matches the canonical requested ID;
- exactly 20 dialogue lines;
- speakers alternate/obey the supported Anna/Erik contract expected by the app;
- non-empty bounded line text;
- no stage directions;
- exactly three unique comprehension questions;
- non-empty bounded question text;
- no disallowed “what did Anna/Erik say” patterns;
- no extra generated fields accepted outside the structured schema;
- total generated JSON size limit;
- generated content is valid UTF-8;
- Swift `LessonValidator` and backend validation remain contract-aligned.

Assign a named `validator_contract_version` and include it in the lesson recipe. Any behavioral validation change that changes which outputs are publishable must bump that version.

Do not send a failed candidate to another user. Failed jobs retain only bounded error metadata, never raw provider output in logs.

---

## 15. Session pinning and configuration changes

When generator configuration changes:

- The current lesson recipe fingerprint changes automatically.
- Old shared artifacts remain immutable but stop satisfying new shared resolves.
- Users already attached to an old artifact keep it with all existing progress/chat/audio.
- New users generate or receive the new current shared artifact.
- A user pressing **Regenerate Lesson** receives a new private artifact under the current recipe and their session resets only after success.

Do not compare a pinned session to current backend configuration on ordinary lesson open. That would create a silent upgrade path contrary to the approved behavior.

Speaking, Interactor, Evaluator, and session synchronization must always use the artifact pinned to that user's session, not “the newest” artifact for the lesson ID.

---

## 16. Audio workflow

### Shared artifact

1. Lesson becomes visible immediately after the shared text artifact is adopted.
2. iOS requests/reconciles audio as it does now.
3. Backend computes the current audio identity from the pinned artifact's canonical dialogue plus backend TTS recipe.
4. On hit, return ready status and serve the shared file.
5. On miss, create/resume the unique shared audio job and return pending/running.
6. One worker generates and validates the WAV.
7. Worker writes the content-addressed file atomically and records metadata.
8. Every waiting user's status becomes ready because they resolve the same artifact/audio identity.

### Private artifact

- Generate owner-scoped audio using the same durable machinery.
- Do not make private lesson/audio metadata visible to other users.
- Physical content-address deduplication is allowed, but it must not bypass metadata authorization.

### Audio configuration change

- Existing users remain pinned to their lesson artifact, but audio compatibility is checked against the current audio recipe when audio is requested.
- If their stored audio is from an old audio recipe, enqueue one replacement for that artifact and keep the lesson visible.
- This realizes “reuse only lesson” when the lesson recipe matches but audio configuration changed.
- A user missing audio can reuse a current matching audio artifact without changing their lesson, realizing “reuse only audio.”
- Never attach audio from a different dialogue hash.

### Worker behavior

Preserve current strengths:

- leased claims;
- bounded attempts;
- exponential retry/backoff;
- reclaim after restart;
- stale-result checks before attachment;
- structured status and retryability;
- foreground-only iOS polling.

Change stale-result validation to compare the job against the immutable artifact and audio recipe, rather than mutable user-session JSON.

---

## 17. iOS changes

### API models

Add Codable models for:

- lesson artifact envelope;
- artifact scope;
- cache resolution state;
- generation job status;
- backend-provided audio identity/status.

Extend `GeneratedLesson` only with optional provenance fields needed locally, or keep provenance in a separate artifact record. Preserve decoding of legacy generated lesson JSON.

### Generation store

Evolve `LessonGenerationStore` so each stored lesson can retain:

- generated lesson content;
- optional artifact ID;
- optional recipe fingerprint;
- artifact scope;
- content hash.

Continue reading legacy `generated_lessons.json`. A migration may wrap legacy values in the new local record shape, but must not publish them to the shared backend cache.

### Generate Lesson

1. Call the shared artifact resolve endpoint with only `payload.id`.
2. Poll a queued job using the server-provided retry interval.
3. Save the returned artifact locally.
4. Bind it to the user's session and mark the lesson generated.
5. Render the lesson immediately.
6. Start audio reconciliation without blocking lesson display.

The UI text remains **Generate Lesson** regardless of cache hit or miss.

### Regenerate Lesson

1. Keep the existing destructive confirmation.
2. Request `mode=private`.
3. Leave the current lesson/session untouched while the job is pending.
4. On success, save the private artifact and replace the session pin.
5. Reset chat/progress/audio exactly as current regeneration does.
6. Begin private audio generation asynchronously.
7. On failure, show the current generic error and preserve the old lesson.

### Audio identity

Remove `LessonAudioContentIdentity` as the authority for model/voice configuration.

- Persist the backend-returned content hash with the local audio filename.
- Use that hash for local-file matching, downloads, ETag verification, and stale-file rejection.
- Do not compute TTS compatibility from hard-coded iOS constants.

### Session synchronization

Extend upload/download records with artifact ID while keeping legacy decoding.

Update `LessonGenerationIdentity` so:

- new artifacts use artifact ID + immutable content hash;
- legacy lessons retain the current fallback identity calculation.

This preserves Speaking synchronization guarantees and prevents a session from accidentally switching artifacts during upload conflict recovery.

---

## 18. Legacy compatibility and trust

### Backend-first compatibility period

Keep existing endpoints operational:

- legacy `/lessons/generate` remains authenticated and user-scoped;
- its model/payload fields do not populate shared artifact tables;
- legacy session uploads continue storing inline generated JSON;
- legacy audio continues using the existing user-scoped BLOB/job path.

The new app uses only the artifact APIs for lesson generation.

After the minimum supported app version uses artifacts:

1. stop accepting model/reasoning selection from iOS;
2. remove the legacy generate path;
3. stop accepting arbitrary generated lesson JSON in session upserts;
4. retire per-user audio upload/cache compatibility code;
5. remove duplicated iOS generator/TTS constants.

Do this as a separate cleanup issue after rollout, not in the first migration.

---

## 19. Concurrency, limits, and failure behavior

### Single-flight guarantees

- Concurrent shared resolves for the same lesson recipe return one artifact/job identity.
- Database uniqueness, not an in-memory lock, enforces this guarantee.
- No database transaction remains open during an OpenAI or Gemini request.
- Workers use leases so a process restart does not permanently block the recipe.
- Late stale results cannot replace a newer recipe or attach to a different artifact.

### Abuse and capacity controls

- Require authentication for every resolve/status/download endpoint.
- Validate lesson IDs against the canonical 224-lesson catalog.
- Keep bounded per-user request cooldowns even though jobs are shared.
- Add a global active lesson-job limit and a global active audio-job limit.
- Count a cache hit separately from a provider-generating miss.
- Do not let repeated taps create extra shared jobs.
- Private regeneration remains subject to stricter per-user rate and queue limits because it always causes new provider work.

### Failure UX

- Shared lesson generation failure: retain retryable status; Generate can retry after cooldown.
- Audio generation failure: lesson remains visible; existing Generate/Retry audio affordance remains available.
- File missing/corrupt: mark audio missing and enqueue repair rather than returning corrupt bytes.
- Config changes mid-job: supersede old job for current resolution without deleting its diagnostic record.
- Private regeneration failure: keep the existing lesson and progress untouched.

---

## 20. Invalidation and garbage collection

Add an operator script, for example:

```text
backend/scripts/invalidate_lesson_artifact.py
```

Required behavior:

- accept exact lesson ID and optional artifact ID;
- default to preview/dry-run;
- require `--apply` to mutate;
- record a bounded reason and timestamp;
- prevent the artifact from satisfying future shared resolves;
- leave existing pinned sessions usable;
- never delete a referenced artifact/audio synchronously.

Initial retention policy:

- Current shared artifacts: retain indefinitely.
- Any artifact referenced by a session: retain.
- Shared artifacts superseded by recipe changes but still referenced: retain.
- Unreferenced private artifacts/audio: eligible for GC after 30 days.
- Unreferenced invalidated or superseded shared artifacts/audio: eligible after 90 days.
- Failed/superseded job metadata: retain 30 days.

Implement GC as a dry-run-first script before automating it. Deletion order must be metadata-aware and recoverable:

1. identify unreferenced eligible metadata;
2. move WAV to a quarantine/trash directory;
3. delete metadata transactionally;
4. purge quarantine only after a further retention window.

---

## 21. Observability

Add structured logs without lesson text, prompts, or user messages:

```text
lesson_artifact_resolve
lesson_artifact_cache_hit
lesson_artifact_cache_miss
lesson_artifact_job_claimed
lesson_artifact_provider_succeeded
lesson_artifact_published
lesson_artifact_job_failed
lesson_artifact_invalidated
artifact_audio_cache_hit
artifact_audio_cache_miss
artifact_audio_job_claimed
artifact_audio_published
artifact_audio_job_failed
```

Include bounded metadata:

- user ID for requester/cost attribution;
- lesson ID;
- artifact scope;
- fingerprint/hash prefixes;
- job/artifact IDs;
- requested and provider-reported models;
- reasoning effort or voice-config version;
- cache hit/miss;
- elapsed time;
- bytes for audio;
- stable error code;
- retryability.

Extend `/admin/audio/metrics` or add a shared-artifact metrics endpoint containing:

- current shared lesson coverage out of 224;
- shared resolve hit/miss counts;
- pending/running/failed lesson jobs;
- pending/running/failed audio jobs;
- shared/private artifact counts;
- audio file count and total bytes;
- missing metadata files;
- orphan files;
- invalidated artifacts;
- unreferenced GC candidates.

OpenAI token/cost usage remains attributed to the user whose miss caused the provider request. Cache hits create no fake OpenAI usage event; application cache-hit logging provides reuse visibility.

---

## 22. Test plan

### Fingerprint unit tests

- Identical semantic recipe objects produce identical fingerprints regardless of dictionary insertion order.
- Changing model changes the lesson fingerprint.
- Changing reasoning effort changes it.
- Changing either prompt changes it.
- Changing generator schema/validator version changes it.
- Changing any curriculum payload field changes it.
- Prompt-cache TTL/key changes do not change it.
- Changing TTS model or voice config changes audio identity.
- Changing dialogue whitespace according to the canonical normalizer behaves intentionally.

### Database tests

- One shared artifact per lesson/recipe under concurrent inserts.
- Multiple private artifacts can exist for one user/lesson/recipe.
- Private artifact ownership is enforced.
- Session pins are not rewritten by a configuration change.
- Invalidated shared artifacts remain available to already-pinned sessions but cannot be newly adopted.
- Legacy null-artifact sessions still round-trip.
- No migration backfills existing generated lessons or audio.
- Job lease expiry permits reclaim.
- Late stale job completion cannot attach to a current recipe.

### Backend API tests

- First shared resolve queues/generates exactly one OpenAI request.
- Second user receives the exact same artifact without an OpenAI request.
- Two concurrent first requests converge on one job/artifact.
- Changed recipe causes a miss and leaves old sessions pinned.
- Client cannot influence shared payload/model/reasoning effort.
- Unknown lesson ID is rejected.
- Private regeneration always produces owner-scoped content and never replaces shared.
- Another user cannot read/adopt private content.
- Session upsert rejects conflicting artifact ID/generated JSON.
- Shared publication happens only after complete validation.
- Provider-reported model/request ID is stored when present.
- Prompt-cache breakpoints, cache key, and input ordering remain as documented in `RUNBOOK.md`.

### Audio tests

- Two users pinned to the same shared artifact create one audio job and one file.
- Ready shared audio is served to both with matching ETag/hash.
- Current lesson + stale TTS recipe reuses lesson and creates one new audio.
- Matching current audio can be downloaded without regenerating the lesson.
- Different dialogue hashes never share audio metadata.
- Private audio cannot be resolved by another user.
- Interrupted worker is reclaimed after lease expiry.
- Late completion for the wrong artifact/recipe is rejected.
- Atomic file write does not expose a partial WAV.
- Missing file metadata triggers repair.
- GC never removes referenced audio.

### iOS tests

- Cached shared lesson renders through the existing Generate button.
- Uncached lesson polls and renders after publication.
- Lesson renders before pending audio completes.
- Ready audio downloads and plays.
- Private regeneration resets only after successful replacement.
- Failed private regeneration preserves current content/progress/audio.
- Existing old session is not automatically upgraded.
- Session conflict recovery preserves artifact identity.
- Legacy generated lesson files still decode.
- Backend-returned audio hash replaces local model/voice hash computation.

### Integration and live verification

1. Run full backend tests.
2. Run the iOS simulator test suite.
3. Exercise two authenticated test users against the VM:
   - user A generates one never-shared lesson;
   - confirm one OpenAI generation usage event;
   - user B presses Generate for the same lesson;
   - confirm exact artifact ID/content and no second OpenAI request;
   - confirm one shared audio job/file;
   - regenerate privately as user B;
   - confirm user A and the shared artifact are unchanged.
4. Change only the lesson manual recipe version in a controlled test and confirm a shared miss without modifying existing sessions.
5. Change only the audio recipe version and confirm lesson reuse plus audio regeneration.
6. Verify physical-device playback and background audio behavior on `iPhone_D`.

---

## 23. Implementation sequence

### Phase 0 — Tracking and baseline

- Create and claim one Beads issue for this medium/large feature.
- Record baseline backend/iOS test results.
- Record current VM DB/audio metrics without reading runtime secrets.
- Confirm local, origin, and VM are synchronized through Git.

### Phase 1 — Canonical configuration and fingerprint library

- Move lesson generator and TTS authority into backend settings.
- Extend the backend catalog to expose complete canonical lesson payloads.
- Implement versioned canonical JSON and fingerprint helpers.
- Capture provider-reported OpenAI model/request ID.
- Add fingerprint/config tests.
- Preserve prompt-cache construction and order exactly.

Deliverable: the backend can state the current lesson and audio recipes deterministically without changing user behavior.

### Phase 2 — Artifact persistence and workers

- Add artifact/job/session-reference schema.
- Implement artifact repository methods and authorization rules.
- Implement durable shared/private lesson generation jobs.
- Add immediate publication after validation.
- Implement invalidation primitives.

Deliverable: backend tests can create, reuse, privately regenerate, pin, and invalidate text artifacts.

### Phase 3 — Artifact APIs and legacy compatibility

- Add resolve/status contracts.
- Add session artifact binding.
- Project artifact JSON into existing session responses and downstream Interactor/Speaking/Evaluator inputs.
- Keep legacy generation/session behavior isolated from the shared cache.
- Add API and concurrency tests.

Deliverable: two API users converge on one shared lesson while private regeneration remains isolated.

### Phase 4 — Shared audio files and jobs

- Add content-addressed filesystem storage.
- Add artifact-scoped audio metadata/jobs.
- Route current audio endpoints by pinned session artifact.
- Preserve legacy per-user audio paths.
- Add file integrity, worker recovery, and metrics tests.

Deliverable: two users reuse one WAV, and audio recipe changes do not force lesson regeneration.

### Phase 5 — iOS adoption

- Add artifact API models and polling.
- Update Generate and Regenerate flows.
- Persist artifact provenance locally.
- Update session sync and generation identity.
- Make server-returned audio hash authoritative.
- Preserve existing UI text and immediate lesson rendering.
- Add iOS unit/UI coverage.

Deliverable: TestFlight-capable app with invisible shared hits and private regeneration.

### Phase 6 — Operations and rollout

- Add dry-run invalidation and GC scripts.
- Add metrics/dashboard fields and structured logs.
- Update `RUNBOOK.md`, backend README, and backup instructions.
- Deploy backend first with sharing enabled only for artifact-capable clients.
- Run two-user VM smoke test.
- Release the iOS build through the documented TestFlight workflow.
- Monitor hit rate, provider request counts, failed jobs, disk growth, and session conflicts.

### Phase 7 — Post-minimum-version cleanup

- Remove client-selected generator configuration.
- Remove legacy client-payload generation.
- Stop accepting arbitrary generated lesson JSON in new session writes.
- Retire legacy per-user audio upload/BLOB paths when safe.
- Create a separate Beads issue for this cleanup; do not mix it into initial rollout acceptance.

---

## 24. Likely files and components

### Backend

- `backend/app/config.py`
- `backend/app/models.py`
- `backend/app/main.py`
- `backend/app/db.py`
- `backend/app/openai_client.py`
- `backend/app/learning_catalog.py`
- `backend/app/lesson_audio.py`
- `backend/app/lesson_audio_worker.py`
- new artifact repository/fingerprint/worker modules as needed
- `backend/scripts/`
- `backend/tests/`

Prefer focused modules over continuing to expand `db.py` and `main.py` with all artifact logic.

### iOS

- `SWE_Dialogs/SWE_Dialogs/BackendClient.swift`
- `SWE_Dialogs/SWE_Dialogs/LessonModels.swift`
- `SWE_Dialogs/SWE_Dialogs/LessonGenerationStore.swift`
- `SWE_Dialogs/SWE_Dialogs/LessonSessionStore.swift`
- `SWE_Dialogs/SWE_Dialogs/LessonView.swift`
- `SWE_Dialogs/SWE_Dialogs/OpenAIModelDefaults.swift`
- corresponding test targets/files

### Documentation/configuration

- `docs/RUNBOOK.md`
- `backend/README.md`
- `docs/BILLING.md` only if active model/pricing configuration changes
- `.gitignore` for content-addressed runtime audio files
- service environment example/documentation without secret values

---

## 25. Deployment and rollback

### Deployment order

1. Additive backend migration and legacy-compatible code.
2. Restart `svenska-api.service` after backend runtime changes.
3. Confirm health, migrations, workers, logs, and metrics.
4. Deploy the artifact-capable iOS build.
5. Perform two-user shared/private smoke tests.
6. Monitor before enabling any cleanup automation.

Use the documented Git workflow:

```bash
scripts/git-commit-push.sh "Add shared lesson artifact cache"
scripts/vm-sync.sh --backend-tests --restart-backend
```

Run iOS validation locally before TestFlight according to `docs/RUNBOOK.md`.

### Rollback

- Keep migrations additive; do not drop legacy columns/tables in the initial release.
- Add a backend feature flag that makes new artifact resolves unavailable while leaving legacy clients operational.
- If disabled after users have artifact-pinned sessions, continue read access to pinned artifacts/audio even if no new shared generation is allowed.
- Do not delete artifact metadata or WAV files during rollback.
- Roll back application code through Git and leave additive tables dormant.

---

## 26. Acceptance criteria

The feature is complete when all of the following are true:

1. User A presses **Generate Lesson** for a canonical lesson with no current shared artifact and causes exactly one lesson generation.
2. User B presses the same button for the same lesson/current recipe and receives byte-equivalent generated lesson content without a second OpenAI call.
3. Both users keep independent lesson progress, messages, translation state, completion, and learning evidence.
4. Both users reuse one current matching shared WAV.
5. If the TTS recipe changes, the existing lesson is reused and one new matching WAV is generated.
6. If any semantic lesson recipe input changes, old shared content is not propagated to new users.
7. Users already working on an old artifact remain pinned and unaffected.
8. **Regenerate Lesson** creates a private artifact and never changes what another user receives from Generate.
9. A lesson renders while missing audio continues through a durable background job.
10. Client-supplied payload/model values cannot enter the shared cache.
11. Simultaneous first requests converge on one durable job and one artifact.
12. Existing pre-artifact sessions and old TestFlight clients continue functioning during rollout.
13. No existing generated lessons/audio are backfilled as shared.
14. Shared audio files survive service restarts/deployments and are covered by operational backup guidance.
15. Prompt-cache breakpoints, stable input ordering, usage recording, and price mapping remain correct.

---

## 27. Final implementation rule

At every boundary, resolve content in this order:

```text
authenticated user's pinned artifact
    -> artifact's immutable generated lesson
    -> current compatible audio identity for that exact dialogue
    -> shared/private authorization based on artifact scope
```

Never resolve downstream lesson content by “latest lesson ID” alone once a user session is pinned. The shared cache decides what a new Generate request receives; the session pin decides what an existing learner continues using.
