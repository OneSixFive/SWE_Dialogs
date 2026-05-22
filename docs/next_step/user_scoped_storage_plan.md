# User-Scoped Storage Implementation Plan

## Goal

Move from device-local lesson state to backend user-scoped persistence so each signed-in Apple user has isolated app data (progress, vocabulary, grammar strengths/weaknesses, optional dialog history).

Identity remains Apple Sign-In, but application data is keyed by internal `users.id` (not directly by `apple_sub`).

## Scope

- Backend: schema, auth context, user-scoped CRUD endpoints.
- iOS app: switch selected local state writes/reads to backend.
- Rollout: keep local fallback initially, then converge to backend source of truth.

Out of scope for v1:
- multi-provider account linking
- advanced analytics dashboards
- heavy media/object storage migration

## Current Baseline (as of 2026-05-22)

- Auth endpoint: `POST /auth/apple`.
- Apple token is verified, user upserted by `apple_sub`.
- Protected endpoints use backend JWT bearer token.
- SQLite database currently has `users` table only.
- Lesson progress/chat/audio are still stored in app documents on device.

## Data Model (v1)

Keep `users` as identity anchor:

- `users(id PK, apple_sub UNIQUE, email, created_at, last_seen_at)`

Add app-state tables:

1. `lesson_progress`
- `id PK`
- `user_id FK -> users.id`
- `lesson_id TEXT`
- `status TEXT` (`not_started|in_progress|completed`)
- `score REAL NULL`
- `completed_at TEXT NULL`
- `updated_at TEXT NOT NULL`
- Unique: (`user_id`, `lesson_id`)

2. `vocabulary_items`
- `id PK`
- `user_id FK`
- `lemma TEXT`
- `surface_form TEXT NULL`
- `translation TEXT NULL`
- `first_seen_at TEXT NOT NULL`
- `last_seen_at TEXT NOT NULL`
- `mastery_score REAL NOT NULL DEFAULT 0`
- Unique: (`user_id`, `lemma`)

3. `grammar_skills` (seed/static catalog)
- `id PK`
- `code TEXT UNIQUE` (example: `subordinate_clause_word_order`)
- `name TEXT`
- `description TEXT NULL`

4. `user_grammar_stats`
- `id PK`
- `user_id FK`
- `grammar_skill_id FK`
- `strength_score REAL NOT NULL DEFAULT 0`
- `evidence_count INTEGER NOT NULL DEFAULT 0`
- `last_updated_at TEXT NOT NULL`
- Unique: (`user_id`, `grammar_skill_id`)

5. `dialog_sessions` (optional in v1, recommended)
- `id PK`
- `user_id FK`
- `lesson_id TEXT NULL`
- `started_at TEXT NOT NULL`
- `ended_at TEXT NULL`
- `summary_json TEXT NULL`

6. `dialog_messages` (optional in v1, recommended)
- `id PK`
- `session_id FK -> dialog_sessions.id`
- `role TEXT` (`user|assistant|system`)
- `text TEXT NOT NULL`
- `created_at TEXT NOT NULL`

Indexes:
- `lesson_progress(user_id, updated_at)`
- `vocabulary_items(user_id, last_seen_at)`
- `user_grammar_stats(user_id, strength_score)`
- `dialog_sessions(user_id, started_at)`

## Auth and User Context Strategy

Use Apple `sub` only for authentication and identity mapping.

1. Keep JWT `sub=apple_sub` for compatibility.
2. Update auth dependency (`require_user`) to resolve `apple_sub -> users.id`.
3. Return a typed current-user context object to endpoints:
- `apple_sub`
- `user_id`

All app-state queries and writes must use `user_id`.

## API Plan (v1)

Add minimal endpoints first:

1. Lesson progress
- `GET /me/progress`
- `PUT /me/progress/{lesson_id}`

2. Vocabulary
- `GET /me/vocabulary?limit=&cursor=`
- `POST /me/vocabulary` (upsert)

3. Grammar stats
- `GET /me/grammar-stats`
- `POST /me/grammar-stats/events` (or direct upsert endpoint)

4. Dialogs (optional v1)
- `POST /me/dialog-sessions`
- `POST /me/dialog-sessions/{id}/messages`
- `GET /me/dialog-sessions/{id}`

Contract rules:
- Never accept `user_id` from client payload.
- User scope derived only from auth token context.
- Validate enums/IDs strictly.

## iOS App Integration Plan

Phase 1 (safe hybrid):
- Keep local persistence in place.
- Add backend sync calls after successful local writes.
- On app launch/sign-in, fetch backend progress and merge.

Phase 2 (backend-first):
- Read progress/vocab/stats from backend by default.
- Use local storage as offline cache.
- Add retry queue for failed writes.

Phase 3 (optional):
- Add dialog session upload and retrieval.
- Keep only transient chat buffer locally.

## Migration and Backfill

No per-user pre-provisioning required.

New users:
1. First Apple login creates `users` row.
2. Other tables get rows lazily on first write.

Existing users:
1. Existing `users` rows remain valid.
2. Tables are additive migrations (no destructive changes).
3. Optional one-time client sync can upload existing local progress into backend.

## Security and Privacy

- Enforce per-request user scoping with `user_id`.
- Keep `apple_sub` internal; do not expose raw values in logs.
- Minimize PII fields; email is optional and may be absent from Apple.
- Add basic request logging with user ID only (or masked identifier).

## Testing Plan

Backend tests:
- Auth mapping: valid token -> correct `user_id`.
- Cross-user isolation: user A cannot read/write user B data.
- Upsert semantics for progress/vocabulary.
- Validation and error codes for malformed payloads.

iOS tests (or integration checks):
- First sign-in creates user and can write/read progress.
- Sign-out/sign-in as another Apple account shows isolated data.
- Offline write then reconnect sync behavior (Phase 2+).

Manual verification commands:
- `cd backend && PYTHONPATH=. .venv/bin/pytest -q tests`
- `curl -fsS https://svenska-api.dima-ib.xyz:8443/health`

## Rollout Sequence

1. Add schema + migration helpers.
2. Refactor auth dependency to provide `current_user`.
3. Implement progress endpoints and tests.
4. Wire iOS lesson progress sync.
5. Implement vocabulary + grammar endpoints.
6. Wire iOS vocabulary/grammar writes.
7. Optional dialog persistence endpoints.
8. Move from hybrid to backend-first reads.

## Acceptance Criteria

- Two different Apple accounts on same app install do not share progress/vocabulary/grammar state.
- Backend rejects any attempt to access another user’s records.
- Current lesson generation/message/TTS flows continue working.
- v1 remains compatible with current Apple Sign-In and JWT approach.

