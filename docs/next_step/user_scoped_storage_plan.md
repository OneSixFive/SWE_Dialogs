# User-Scoped Storage Implementation Plan

## Goal

Move from device-local lesson state to backend user-scoped persistence so each signed-in Apple user has isolated app data and can resume lessons across devices.

V1 should support full lesson resumption, not only a completed/in-progress progress marker. Later phases add vocabulary mastery, grammar proficiency, and optional dialog history.

Identity remains Apple Sign-In, but application data is keyed by internal `users.id` rather than directly by `apple_sub`.

## Scope

- Backend: additive SQLite migrations, auth context, user-scoped CRUD endpoints, validation, and isolation tests.
- iOS app: backend sync for full lesson session state, backend-backed progress display, and user-scoped local cache fallback.
- Rollout: start hybrid/local-cache-first, then converge to backend as source of truth when retry/conflict behavior is stable.

Out of scope for v1:
- multi-provider account linking
- advanced analytics dashboards
- heavy media/object storage migration
- raw custom-dialog history persistence unless explicitly enabled after privacy/retention rules are defined

## Current Baseline (as of 2026-05-26)

- Auth endpoint: `POST /auth/apple`.
- Apple token is verified, user is upserted by `apple_sub`.
- Backend session JWT currently uses `sub=apple_sub`.
- Protected endpoints use backend JWT bearer token.
- SQLite database currently has a `users` table only.
- Lesson generation, lesson message, and TTS calls are backend-authenticated.
- Lesson generated content, lesson state/chat, and audio files are still stored in app documents on device:
  - `generated_lessons.json`
  - `lesson_sessions.json`
  - `lesson_audio/*.wav`
- Current local lesson state includes more than progress: phase, current question, translation quiz, translation attempts, mistake notes, audio file name, completion flag, `updated_at`, and lesson chat messages.

## Design Principles

- Never accept `user_id` from client payloads.
- Derive user scope only from the backend session token.
- Use internal `users.id` for all application data joins and constraints.
- Keep `apple_sub` internal to auth/account mapping. Do not expose it in normal API responses or logs.
- Treat backend state as user data. Add deletion/export hooks later before collecting larger history.
- Keep local storage available as an offline cache, but namespace it per signed-in backend user.
- Prefer append/event records for learning evidence, but keep denormalized summary tables for fast app reads.
- Make v1 full-state storage boring and robust before adding higher-level learning analytics.

## Backend Data Model

Keep `users` as identity anchor:

- `users(id PK, apple_sub UNIQUE, email, created_at, last_seen_at)`

Add schema infrastructure:

1. `schema_migrations`
- `version INTEGER PRIMARY KEY`
- `applied_at TEXT NOT NULL`

Runtime SQLite settings:
- Enable `PRAGMA foreign_keys = ON` for every connection.
- Set `PRAGMA busy_timeout = 5000`.
- Consider WAL mode on the VM (`PRAGMA journal_mode = WAL`) after verifying service/user permissions.
- Back up `backend/data/svenska.db` before applying migrations on the VM.

Add app-state tables:

1. `lesson_sessions`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `lesson_id TEXT NOT NULL`
- `state_json TEXT NOT NULL`
- `generated_lesson_json TEXT NULL`
- `messages_json TEXT NOT NULL DEFAULT '[]'`
- `chat_summary_json TEXT NULL`
- `state_schema_version INTEGER NOT NULL DEFAULT 1`
- `content_schema_version INTEGER NOT NULL DEFAULT 1`
- `status TEXT NOT NULL`
  - allowed: `not_started|generated|listening|comprehension|discussion|translation|completed`
- `is_completed INTEGER NOT NULL DEFAULT 0`
- `completed_at TEXT NULL`
- `client_updated_at TEXT NOT NULL`
- `server_updated_at TEXT NOT NULL`
- `deleted_at TEXT NULL`
- Unique: (`user_id`, `lesson_id`)

Notes:
- `state_json` stores the app's full `LessonState` payload so the user can resume exactly where they left off.
- `generated_lesson_json` stores the generated dialogue/questions for cross-device resume. Without this, a second device may know the state but not have the generated lesson content needed to continue.
- `messages_json` stores the lesson chat messages needed to render the lesson transcript and preserve Interactor context across devices.
- `chat_summary_json` can later hold bounded summaries or selected context, but it is not enough by itself for exact v1 resume.
- Do not store local audio files in v1. A resumed device can regenerate audio or fetch it separately later.
- Treat `audio_file_name` inside `state_json` as a device-local cache hint. The iOS sync layer should either strip it before upload or clear it after download if the file does not exist on the current device.
- Keep `status` and `is_completed` denormalized for fast curriculum/progress screens.

2. `lesson_progress`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `lesson_id TEXT NOT NULL`
- `status TEXT NOT NULL`
- `is_completed INTEGER NOT NULL DEFAULT 0`
- `completed_at TEXT NULL`
- `score REAL NULL`
- `client_updated_at TEXT NOT NULL`
- `server_updated_at TEXT NOT NULL`
- Unique: (`user_id`, `lesson_id`)

Notes:
- This table is optional if progress can always be derived from `lesson_sessions`.
- Keep it only if the app needs a small, fast progress response without transferring full state.
- If kept, update it in the same transaction as `lesson_sessions`.

3. `vocabulary_items`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `lemma TEXT NOT NULL`
- `surface_form TEXT NULL`
- `part_of_speech TEXT NULL`
- `sense_key TEXT NULL`
- `translation TEXT NULL`
- `source_lesson_id TEXT NULL`
- `first_seen_at TEXT NOT NULL`
- `last_seen_at TEXT NOT NULL`
- `mastery_score REAL NOT NULL DEFAULT 0`
- `evidence_count INTEGER NOT NULL DEFAULT 0`
- Unique normalized key: (`user_id`, normalized `lemma`, `COALESCE(part_of_speech, '')`, `COALESCE(sense_key, '')`)

Notes:
- `UNIQUE(user_id, lemma)` is too coarse for Swedish once multiple senses or parts of speech matter.
- A plain SQLite unique constraint over nullable `part_of_speech` or `sense_key` is not sufficient because nulls are treated as distinct. Use generated normalized columns or a unique expression index.
- `sense_key` can remain null initially, but the schema should not block later disambiguation.

4. `vocabulary_events`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `vocabulary_item_id INTEGER NULL REFERENCES vocabulary_items(id) ON DELETE SET NULL`
- `lesson_id TEXT NULL`
- `event_type TEXT NOT NULL`
  - allowed examples: `seen|answered_correctly|answered_incorrectly|asked_about|reviewed`
- `event_json TEXT NULL`
- `created_at TEXT NOT NULL`

5. `grammar_skills`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `code TEXT NOT NULL UNIQUE`
- `name TEXT NOT NULL`
- `description TEXT NULL`
- `created_at TEXT NOT NULL`

6. `grammar_events`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `grammar_skill_id INTEGER NULL REFERENCES grammar_skills(id) ON DELETE SET NULL`
- `lesson_id TEXT NULL`
- `event_type TEXT NOT NULL`
  - allowed examples: `targeted|used_correctly|used_incorrectly|asked_about|reviewed`
- `event_json TEXT NULL`
- `created_at TEXT NOT NULL`

7. `user_grammar_stats`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `grammar_skill_id INTEGER NOT NULL REFERENCES grammar_skills(id) ON DELETE CASCADE`
- `strength_score REAL NOT NULL DEFAULT 0`
- `evidence_count INTEGER NOT NULL DEFAULT 0`
- `last_updated_at TEXT NOT NULL`
- Unique: (`user_id`, `grammar_skill_id`)

8. `dialog_sessions` (later, privacy-gated)
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `lesson_id TEXT NULL`
- `started_at TEXT NOT NULL`
- `ended_at TEXT NULL`
- `summary_json TEXT NULL`
- `retention_policy TEXT NOT NULL DEFAULT 'summary_only'`

9. `dialog_messages` (later, only if raw history is needed)
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `session_id INTEGER NOT NULL REFERENCES dialog_sessions(id) ON DELETE CASCADE`
- `role TEXT NOT NULL`
  - allowed: `user|assistant|system`
- `text TEXT NOT NULL`
- `created_at TEXT NOT NULL`

Indexes:
- `lesson_sessions(user_id, server_updated_at)`
- `lesson_sessions(user_id, lesson_id)`
- `lesson_sessions(user_id, is_completed)`
- `lesson_progress(user_id, server_updated_at)`
- `vocabulary_items(user_id, last_seen_at)`
- `vocabulary_items(user_id, mastery_score)`
- `vocabulary_events(user_id, created_at)`
- `grammar_events(user_id, created_at)`
- `user_grammar_stats(user_id, strength_score)`
- `dialog_sessions(user_id, started_at)`

## Auth and User Context Strategy

Use Apple `sub` only for authentication and identity mapping.

V1 compatibility path:

1. Keep JWT `sub=apple_sub` initially so existing app sessions remain compatible.
2. Update `require_user` to resolve `apple_sub -> users.id`.
3. Return a typed current-user context object to endpoints:
   - `apple_sub`
   - `user_id`
4. All app-state queries and writes must use `user_id`.

Near-term cleanup:

- Stop returning `apple_sub` from `/auth/apple` responses. The client should only need internal backend user ID and optional account display fields.
- Avoid logging raw Apple identifiers.
- Later session tokens can move to `sub=users.id` plus a separate `apple_sub` lookup during token issue, but that migration is not required for v1.

## API Plan

### Account/Auth

- `POST /auth/apple`
  - Existing endpoint.
  - Response should include `session_token` and `user.id`.
  - Do not include `apple_sub` in new clients.

Optional:
- `GET /me`
  - Returns the current user summary and app sync metadata.

### Lesson State

1. `GET /me/lesson-sessions`

Query parameters:
- `summary_only=true|false`, default `true`
- `updated_after=<server_updated_at cursor>`, optional
- `limit=<n>`, optional

Response, summary mode:
- List of lesson summaries:
  - `lesson_id`
  - `status`
  - `is_completed`
  - `completed_at`
  - `client_updated_at`
  - `server_updated_at`

Response, full mode:
- Same fields plus:
  - `state`
  - `generated_lesson`
  - `messages`
  - `chat_summary`
  - schema versions

2. `GET /me/lesson-sessions/{lesson_id}`

Returns the full resumable session for one lesson:
- `lesson_id`
- `state`
- `generated_lesson`
- `messages`
- `chat_summary`
- `status`
- `is_completed`
- `completed_at`
- `client_updated_at`
- `server_updated_at`
- schema versions

3. `PUT /me/lesson-sessions/{lesson_id}`

Upserts full session state.

Payload:
- `state`
- `generated_lesson`, nullable but required once the lesson has generated content
- `messages`, default `[]`
- `chat_summary`, nullable
- `client_updated_at`
- `base_server_updated_at`, nullable
- `reset_generation`, boolean default `false`

Server-derived fields:
- `status` from `state.phase`
- `is_completed` from `state.is_completed`
- `completed_at` set when transitioning to completed, unless supplied by a trusted server-side path later
- `server_updated_at` current server timestamp

Conflict behavior:
- If no existing row, insert.
- If `base_server_updated_at` matches the current stored row, update.
- If the stored row is newer and the incoming state is not completed, return `409 Conflict` with the current server row.
- If incoming state is completed and stored state is not completed, accept the completed state unless the stored row has a newer explicit reset.
- If `reset_generation=true`, allow a downgrade from completed/in-progress to generated/listening only when the client has the current `base_server_updated_at`.
- Do not silently overwrite a newer server row with older client state.

4. `DELETE /me/lesson-sessions/{lesson_id}` or reset endpoint

Prefer a reset endpoint over hard delete:
- `POST /me/lesson-sessions/{lesson_id}/reset`

Behavior:
- Clears generated lesson, lesson messages, chat summary, and progress state for that lesson.
- Writes a new `server_updated_at`.
- Keeps an audit-friendly tombstone or reset marker if needed for conflict handling.

### Progress

If `lesson_progress` is kept separately:

- `GET /me/progress`
- `PUT /me/progress/{lesson_id}`

Use these only for small progress summaries. Full resume should use `lesson_sessions`.

### Vocabulary

1. `GET /me/vocabulary?limit=&cursor=`
2. `POST /me/vocabulary/events`

Event payload:
- `lesson_id`, nullable
- `lemma`
- `surface_form`, nullable
- `part_of_speech`, nullable
- `sense_key`, nullable
- `translation`, nullable
- `event_type`
- `event_json`, nullable
- `client_created_at`

Server behavior:
- Upsert `vocabulary_items`.
- Insert `vocabulary_events`.
- Update `last_seen_at`, `mastery_score`, and `evidence_count` transactionally.

Avoid direct arbitrary `mastery_score` writes from the client unless there is a clear reason. Prefer evidence events.

### Grammar

1. `GET /me/grammar-stats`
2. `POST /me/grammar/events`

Event payload:
- `lesson_id`, nullable
- `grammar_skill_code`
- `event_type`
- `event_json`, nullable
- `client_created_at`

Server behavior:
- Resolve `grammar_skill_code`.
- Insert `grammar_events`.
- Update `user_grammar_stats` transactionally.

### Dialogs

Do not include raw dialog message persistence in initial v1 unless needed for product behavior.

Later options:
- `POST /me/dialog-sessions`
- `POST /me/dialog-sessions/{id}/messages`
- `GET /me/dialog-sessions/{id}`

Before enabling raw messages:
- Define retention period.
- Define account deletion behavior.
- Decide whether summaries are enough for learning personalization.
- Avoid storing full TTS audio or generated WAV blobs in SQLite.

## iOS App Integration Plan

### Phase 1: Full-State Hybrid Sync

- Keep local persistence so the app remains usable offline and low-risk during rollout.
- Namespace local files by signed-in backend `user.id`, for example:
  - `users/<user_id>/lesson_sessions.json`
  - `users/<user_id>/generated_lessons.json`
  - `users/<user_id>/lesson_audio/*.wav`
- On sign-in:
  - Exchange Apple token.
  - Store session token.
  - Store current backend `user.id`.
  - Switch local stores to that user's cache namespace.
  - Fetch lesson session summaries from backend.
  - Merge into local cache using conflict rules.
- On sign-out:
  - Delete session token.
  - Detach in-memory stores from the prior user's cache.
  - Do not show prior user's cached state on the sign-in screen or under a different account.
- After every successful local state write, enqueue or send a backend `PUT /me/lesson-sessions/{lesson_id}`.
- Store `base_server_updated_at` with each locally cached lesson row so the client can detect conflicts.
- If backend sync fails, keep local changes and retry later.

### Phase 2: Backend-First Reads

- Use backend summaries for curriculum progress display after sign-in.
- Fetch full lesson session only when opening a lesson or when local cache is stale.
- Keep local JSON as offline cache.
- Add a durable retry queue for failed writes.
- Add a lightweight sync status for developer debugging, not necessarily visible to users.

### Phase 3: Learning Evidence

- Emit vocabulary events when words/chunks are introduced, practiced, answered, or explicitly asked about.
- Emit grammar events from lesson targets, mistake notes, and translation attempts.
- Keep event upload best-effort at first. Do not block lesson flow on analytics/proficiency sync.

### Phase 4: Dialog History Or Summaries

- If needed, upload bounded lesson chat summaries rather than raw chat.
- Only store raw messages after privacy/retention behavior is explicit.

## Merge and Conflict Rules

For local/backend sync, each lesson cache entry should store:
- full `LessonState`
- optional `GeneratedLesson`
- lesson messages
- optional chat summary
- `client_updated_at`
- last known `server_updated_at`
- dirty flag

Default merge:
- If only local exists, upload it.
- If only server exists, download it.
- If both exist and local is clean, use server if server is newer.
- If both exist and local is dirty:
  - Try PUT with `base_server_updated_at`.
  - If server returns 409, keep both versions in memory and prefer the one with greater learning progress unless it is a reset conflict.

Progress ordering, from lowest to highest:
1. `not_started`
2. `generated`
3. `listening`
4. `comprehension`
5. `discussion`
6. `translation`
7. `completed`

Completion should be monotonic except explicit reset/regenerate actions. Reset/regenerate must carry the latest `base_server_updated_at` so an old device cannot accidentally erase newer progress.

## Migration and Backfill

No per-user pre-provisioning required.

New users:
1. First Apple login creates a `users` row.
2. Other tables get rows lazily on first write.

Existing users:
1. Existing `users` rows remain valid.
2. Tables are additive migrations.
3. On first app version with sync:
   - Determine signed-in `user.id`.
   - Move or copy old unscoped local files into that user's cache namespace only after sign-in.
   - Upload existing local lesson sessions as dirty local state.
   - Use backend conflict rules if server already has rows.

VM deployment:
1. Back up `backend/data/svenska.db`.
2. Deploy migration code.
3. Run backend tests.
4. Restart `svenska-api.service` because backend runtime code changed.
5. Check service status, logs, and `/health`.

## Security and Privacy

- Enforce per-request user scoping with `user_id`.
- Keep `apple_sub` internal.
- Remove `apple_sub` from client-visible account responses once the app no longer needs it.
- Minimize PII fields; Apple email is optional and may be absent.
- Add basic request logging with internal user ID only, or a masked identifier.
- Avoid logging full lesson state, chat text, generated lesson text, or raw Apple tokens.
- Lesson messages are stored for cross-device resume; treat them as sensitive learner data, not analytics exhaust.
- Add future account data deletion/export tasks before storing large histories.
- Do not store audio blobs in SQLite.

## Testing Plan

Backend tests:
- Auth mapping: valid token resolves to correct `user_id`.
- Protected endpoints receive a typed current-user context.
- Cross-user isolation: user A cannot read, write, reset, or list user B data.
- Lesson session upsert inserts full state and generated lesson.
- Lesson session upsert includes lesson messages needed for UI and Interactor context.
- Lesson session GET returns full resumable state, generated lesson, and messages.
- Progress summaries match stored lesson session state.
- Conflict handling:
  - matching `base_server_updated_at` updates
  - stale non-completed update returns 409
  - completed update can advance non-completed state
  - stale reset cannot erase newer progress
- Validation and error codes for malformed payloads, bad lesson IDs, bad enum values, and invalid JSON state.
- Migrations are idempotent on an existing DB.

iOS tests or integration checks:
- First sign-in creates user and switches to a user-scoped cache namespace.
- Sign-out/sign-in as another Apple account does not show prior account's local cached progress.
- Completing a lesson locally uploads full state and generated lesson.
- Fresh install on another device can fetch the lesson and resume with state, generated content, and prior lesson messages.
- Offline write then reconnect syncs later.
- Stale local write conflict does not silently overwrite newer server state.
- Regenerate/reset requires current server base and does not erase newer remote progress accidentally.

Manual verification commands:
- `cd backend && PYTHONPATH=. .venv/bin/pytest -q tests`
- `curl -fsS https://svenska-api.dima-ib.xyz:8443/health`

## Rollout Sequence

1. Add backend migration infrastructure and SQLite connection settings.
2. Add `lesson_sessions` schema and migration tests.
3. Refactor auth dependency to return typed `CurrentUser(user_id, apple_sub)`.
4. Stop exposing `apple_sub` in new auth response models.
5. Implement full lesson session endpoints and backend tests.
6. Wire iOS local storage namespacing by backend `user.id`.
7. Wire iOS full-state sync for lesson session writes.
8. Add launch/sign-in summary fetch and merge.
9. Add conflict handling and durable retry queue.
10. Move progress UI to backend-backed summaries after sign-in.
11. Implement vocabulary event/stat tables and endpoints.
12. Wire iOS vocabulary events.
13. Implement grammar event/stat tables and endpoints.
14. Wire iOS grammar events.
15. Decide whether dialog summaries/raw messages are needed, then implement privacy-gated dialog persistence if required.

## Acceptance Criteria

- Two different Apple accounts on the same app install do not share local or backend lesson state.
- A signed-in user can start a lesson on one device and resume the same generated lesson/state on another device.
- Backend rejects any attempt to access another user's lesson session, progress, vocabulary, grammar, or dialog records.
- Stale client writes cannot silently overwrite newer backend state.
- Explicit reset/regenerate behavior is preserved and cannot erase newer remote progress from an old device.
- Current lesson generation/message/TTS flows continue working.
- V1 remains compatible with current Apple Sign-In and existing JWT sessions during rollout.
