# SWE_Dialogs — Speaking Expense Tracking Implementation Plan

## Goal

Add **Speaking / `gpt-realtime-2.1` usage and estimated cost** to the existing OpenAI usage/expenses dashboard in the same user/model/role/event structure already used for Generator, Interactor, Vocabulary, and Evaluator requests.

The implementation should preserve the current dashboard architecture. Speaking should become another usage role rather than introducing a separate dashboard or parallel accounting system.

## Current Architecture

Relevant backend files:

- `backend/app/main.py`
  - Speaking Realtime call bootstrap and teardown endpoints.
  - Admin usage dashboard endpoints and HTML.
  - Existing `available_roles` list.
- `backend/app/realtime_client.py`
  - Creates and hangs up OpenAI Realtime calls.
  - Backend sees SDP bootstrap and provider `call_id`, but not the ongoing Realtime responses.
- `backend/app/speaking_service.py`
  - Builds Realtime session configuration.
  - Owns the process-local Speaking session lease/registry.
- `backend/app/openai_client.py`
  - Existing Responses API usage extraction and cost estimation.
  - Produces usage-event payloads for `Database.record_openai_usage`.
- `backend/app/db.py`
  - `openai_usage_events` storage.
  - `record_openai_usage`.
  - `usage_dashboard_summary`.
- `backend/app/config.py`
  - `OPENAI_USAGE_PRICE_OVERRIDES_JSON`.
  - Speaking model configuration.
- `SWE_Dialogs/SWE_Dialogs/RealtimeSpeakingClient.swift`
  - Receives Realtime server events over the WebRTC data channel.
  - Already handles `response.done`.
- `SWE_Dialogs/SWE_Dialogs/BackendClient.swift`
  - Speaking bootstrap/hangup backend calls.
- `backend/tests/test_speaking.py`
  - Speaking backend contract tests.
- Existing usage/cost tests, primarily around `backend/app/openai_client.py` and DB/dashboard behavior.

### Existing accounting path

Normal OpenAI Responses API calls:

1. Backend sends request.
2. Backend receives provider response including `usage`.
3. `openai_client.py` normalizes usage and estimates cost.
4. Backend calls `database.record_openai_usage(...)`.
5. `openai_usage_events` feeds all dashboard aggregates.

### Speaking difference

Speaking uses WebRTC:

1. Backend creates the Realtime call.
2. iOS connects directly to the OpenAI Realtime session.
3. Ongoing Realtime events, including `response.done`, arrive on the iOS data channel.
4. Backend currently does not see those per-response usage payloads.

Therefore Speaking cannot be accounted for solely at bootstrap/hangup time.

---

# Proposed Design

## High-level flow

For every Realtime `response.done` event received by iOS:

1. Extract the provider response ID and its `usage` object.
2. POST a compact usage report to the backend.
3. Backend authenticates the app user.
4. Backend validates that the reported Speaking session belongs to that user.
5. Backend normalizes Realtime usage.
6. Backend calculates estimated cost using modality-aware Realtime pricing.
7. Backend inserts an idempotent `openai_usage_events` row.
8. Existing dashboard aggregation automatically includes the event.
9. Add `Speaking` to the dashboard role filter.

Use **one usage event per provider `response.done`**, not one event per complete Speaking session. This matches the provider's usage boundary and makes retries/idempotency simple.

---

# 1. Add Realtime Usage Ingestion Endpoint

## File

`backend/app/main.py`

## Endpoint

Add an authenticated endpoint under the existing Speaking resource, for example:

```text
POST /me/lesson-sessions/{lesson_id}/speaking/realtime-usage
```

Suggested request shape:

```json
{
  "speaking_session_id": "uuid",
  "provider_response_id": "resp_...",
  "usage": {
    "...": "provider usage payload"
  }
}
```

Do not accept from the client:

- user ID
- request role
- model used for billing
- estimated cost

These must be assigned server-side.

## Backend validation

The endpoint must validate:

- authenticated user exists
- curriculum lesson exists
- `speaking_session_id` belongs to the current user
- the session corresponds to an active/recent Speaking lease
- `provider_response_id` is non-empty and bounded
- `usage` is a JSON object
- payload size is bounded
- only expected usage fields are persisted/calculated

Do not trust the client to specify the model. Use:

```python
settings.speaking_realtime_model
```

Server-created usage event metadata:

```text
request_role = "Speaking"
request_name = "speaking_turn"
source_id = lesson_id
model = settings.speaking_realtime_model
prompt_version = "speaking_realtime_v1"
```

Return:

- `204 No Content` for newly recorded events
- also succeed idempotently for already-recorded `provider_response_id`

A duplicate client retry must never create duplicate spend.

---

# 2. Make Speaking Session Validation Suitable for Usage Uploads

## File

`backend/app/speaking_service.py`

The current `SpeakingSessionRegistry` removes a lease from `_leases` when `finish()` is called.

A final `response.done` usage POST may race with session cleanup. Do not make valid usage dependent on a very narrow timing window.

Implement one of the following, preferring the simpler robust option:

### Preferred: short-lived completed-session retention

Keep minimal completed session metadata for a bounded grace period after `finish()`:

```text
session_id
user_id
call_id
expires/finished timestamp
```

The usage endpoint should accept reports for:

- active Speaking sessions, or
- recently completed Speaking sessions within the grace period

Suggested grace period: a few minutes, configurable or a small constant.

Do not retain conversation content.

### Alternative

Have the client ensure the final usage upload completes before issuing the backend hangup call.

This is less robust because app suspension/network timing can still race cleanup, so server-side grace retention is preferred.

---

# 3. Add an Explicit Provider Response ID for Idempotency

## File

`backend/app/db.py`

Add a migration adding a nullable provider response identifier to `openai_usage_events`.

Suggested column:

```sql
provider_response_id TEXT NULL
```

Add a unique partial index:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_openai_usage_provider_response_id
ON openai_usage_events(provider_response_id)
WHERE provider_response_id IS NOT NULL;
```

Do not overload `openai_request_id`.

Reason:

- Responses API `x-request-id` and Realtime `response.id` are different concepts.
- Keeping them separate avoids ambiguous semantics.
- Existing Responses API accounting remains unchanged.

Update `record_openai_usage()` to include the column.

`INSERT OR IGNORE` may continue to provide idempotent behavior.

---

# 4. Realtime Usage Normalization

## Recommended file

Either:

- add Realtime-specific helpers to `backend/app/openai_client.py`, or
- create a small `backend/app/openai_usage.py` module if moving shared accounting helpers improves separation.

Avoid a large refactor solely for this feature.

## Requirement

Normalize the provider's Realtime usage payload into:

### Existing aggregate fields

Populate as far as meaningful:

```text
input_tokens
cached_tokens
cache_write_tokens
ordinary_input_tokens
output_tokens
reasoning_tokens
total_tokens
estimated_cost_usd
effective_input_cost_usd
uncached_input_cost_usd
net_cache_savings_usd
raw_usage_json
```

Fields that do not apply to Realtime may be `0` or `NULL` according to the conventions already used by the table.

### Modality breakdown

Realtime accounting must preserve enough information to distinguish:

- text input tokens
- cached text input tokens
- audio input tokens
- cached audio input tokens
- text output tokens
- audio output tokens

The exact parsing logic must follow the actual `gpt-realtime-2.1` `response.done.response.usage` schema currently returned by OpenAI.

Before coding the parser, Codex should inspect the current official Realtime API documentation or captured development payloads rather than assuming the field layout.

Always retain the bounded normalized/original provider usage payload in `raw_usage_json` for diagnostics.

---

# 5. Add Modality-aware Realtime Cost Estimation

## Problem

The existing estimator is designed for text-style models:

```text
ordinary input
cached input
cache write
output
```

with one price per token category.

Realtime audio and text have distinct pricing. Therefore do **not** feed aggregate Realtime token totals into the existing estimator unchanged.

## Implementation

Add a dedicated helper, e.g.:

```python
def estimated_realtime_cost_metrics(
    settings: Settings,
    model: str,
    usage: dict[str, Any],
) -> dict[str, float | int | None]:
    ...
```

It should calculate:

```text
text input cost
cached text input cost
audio input cost
cached audio input cost
text output cost
audio output cost
--------------------------------
estimated total cost
```

Also derive aggregate token columns for the existing dashboard.

## Pricing configuration

Extend `OPENAI_USAGE_PRICE_OVERRIDES_JSON` rather than scattering pricing constants through application logic.

Example configuration shape:

```json
{
  "gpt-realtime-2.1": {
    "text_input_per_million": 0,
    "text_cached_input_per_million": 0,
    "text_output_per_million": 0,
    "audio_input_per_million": 0,
    "audio_cached_input_per_million": 0,
    "audio_output_per_million": 0
  }
}
```

Use current production prices when configuring the deployment.

Do not embed price values from this plan; pricing changes over time.

### Compatibility

Existing model price configuration must remain valid.

The existing text estimator must continue to work unchanged for Generator, Interactor, Vocabulary, and Evaluator calls.

---

# 6. Capture `response.done` Usage on iOS

## File

`SWE_Dialogs/SWE_Dialogs/RealtimeSpeakingClient.swift`

Current behavior already parses `response.done`.

Extend handling so every `response.done`:

1. reads the `response` object
2. extracts:
   - `response.id`
   - `response.usage`
3. sends the usage report to the backend asynchronously
4. independently continues existing end-of-practice function-call handling

Usage reporting must not block or break audio interaction.

Conceptually:

```swift
case "response.done":
    reportUsageIfPresent(object)
    if containsPracticeEndCall(object) {
        requestPracticeEnd()
    }
```

## Reliability rules

- Do not fail the Speaking session because expense telemetry failed.
- Retry transient upload failures a small bounded number of times if convenient.
- Server idempotency is mandatory, so retries are safe.
- Do not send transcript/audio content as part of usage telemetry.
- Do not log the entire Realtime event.

The usage upload can be fire-and-forget from the UX perspective, but the client should keep the task alive long enough to make a normal request.

---

# 7. Add Backend Client Method

## File

`SWE_Dialogs/SWE_Dialogs/BackendClient.swift`

Add:

```swift
func reportSpeakingRealtimeUsage(
    lessonID: String,
    speakingSessionID: String,
    providerResponseID: String,
    usage: [String: ...]
) async
```

Prefer a typed `Codable` representation for the subset of Realtime usage fields needed by the backend/client contract.

If the provider schema is too nested/unstable for a clean Swift structure, a bounded JSON-compatible wrapper is acceptable, but do not weaken unrelated backend API typing.

The call must:

- require normal app authentication
- use the current Speaking session ID
- tolerate duplicate submission
- not expose an error to the learner

---

# 8. Dashboard Integration

## File

`backend/app/main.py`

Add:

```text
"Speaking"
```

to:

```python
available_roles
```

No separate Speaking dashboard is needed.

## Existing dashboard behavior to preserve

Once Speaking rows are in `openai_usage_events`, they should automatically appear in:

- total estimated cost
- total token usage
- per-user cost
- per-user/model pivot
- role/model totals
- event table
- role filtering

The model should appear as:

```text
gpt-realtime-2.1
```

or whatever `settings.speaking_realtime_model` is configured to.

---

# 9. Actual OpenAI Organization Cost

The existing dashboard separately queries OpenAI's organization cost endpoint for the top-level actual-cost figure.

Leave that mechanism unchanged.

Speaking local events provide **attribution and estimated per-user/per-role spend**.

The organization cost endpoint remains the source for the dashboard's provider-level actual total.

Do not attempt to allocate the organization-wide actual-cost number back to individual Speaking turns unless a reliable provider-supported attribution mechanism already exists.

---

# 10. Data Integrity / Security Requirements

The implementation must satisfy all of these:

- Client cannot report usage for another user.
- Client cannot choose the billed model.
- Client cannot choose `request_role`.
- Duplicate `response.done` submissions do not double count.
- No audio bytes are persisted.
- No transcript is added to usage events.
- No full Realtime event payload is logged.
- Usage JSON is size bounded.
- Provider identifiers are length/format bounded.
- Speaking telemetry failure never makes Speaking practice unusable.
- Existing Responses API accounting behavior is unchanged.

---

# 11. Tests

## Backend unit tests

### Realtime usage parsing

Test:

- text-only usage
- audio-only usage
- mixed text/audio usage
- cached audio input
- cached text input
- missing optional details
- malformed values
- absent usage
- unknown future fields ignored safely

### Cost calculation

Use fake pricing.

Verify exact calculations independently for:

```text
text input
cached text
audio input
cached audio
text output
audio output
combined total
```

Do not base assertions on production OpenAI prices.

### DB

Test:

- Realtime event is inserted
- `provider_response_id` stored
- duplicate response ID is ignored
- different responses from same Speaking session are all retained
- Speaking rows appear in `usage_dashboard_summary`
- existing Responses API rows remain unaffected

## Endpoint tests

In `backend/tests/test_speaking.py` or a focused usage test file:

Test:

- authenticated valid upload -> success
- duplicate upload -> idempotent success
- wrong user/session -> rejected
- unknown session -> rejected
- recently finished session within grace period -> accepted
- expired grace session -> rejected
- malformed usage -> 4xx
- oversized payload -> rejected
- client-supplied model is impossible / ignored by schema
- server uses configured `speaking_realtime_model`

## iOS tests

Where practical, isolate parsing of `response.done` into a testable helper.

Test:

- response with `id` + `usage` triggers usage reporting
- response without usage does not report
- function-call completion still ends practice
- usage reporting failure does not emit `.failed`
- multiple `response.done` events produce distinct reports

---

# 12. Observability

Add concise structured server logs such as:

```text
speaking_usage_recorded
speaking_usage_duplicate
speaking_usage_rejected
```

Include only bounded operational identifiers:

```text
user_id
lesson_id
speaking_session_id
provider_response_id
model
```

Do not log raw usage JSON unless there is already an explicitly safe debug mechanism.

Avoid logging access tokens, SDP, audio, transcripts, or full provider events.

---

# 13. Suggested Implementation Order

1. Add DB migration for `provider_response_id`.
2. Extend `record_openai_usage`.
3. Implement Realtime usage normalization.
4. Implement modality-aware Realtime pricing.
5. Add backend Speaking usage endpoint.
6. Add completed-session grace validation.
7. Add `BackendClient.swift` telemetry method.
8. Extract/report usage from iOS `response.done`.
9. Add `Speaking` to dashboard roles.
10. Add backend tests.
11. Add iOS parsing/reporting tests.
12. Run existing full test suite and verify no regressions.
13. Manually run one Speaking practice and verify dashboard attribution.

---

# 14. Manual Verification

After deployment/configuration:

1. Open usage dashboard for a short known time range.
2. Note current totals.
3. Run one Speaking practice with several tutor responses.
4. End practice normally.
5. Refresh dashboard.
6. Verify:
   - role `Speaking` exists
   - model is the configured Realtime model
   - correct user is attributed
   - multiple `speaking_turn` events are visible
   - estimated cost is non-zero when pricing is configured
   - total estimated cost increased by the sum of the Speaking events
7. Re-submit one already-seen provider response in a test environment and verify no double charge.
8. Verify normal Generator/Interactor usage still appears unchanged.

---

# 15. Acceptance Criteria

The feature is complete when:

- [ ] Every billable Realtime `response.done` with usage can be represented as one local usage event.
- [ ] Speaking usage is attributed to the authenticated user and lesson.
- [ ] Duplicate telemetry cannot double-count expense.
- [ ] Realtime text/audio modality pricing is calculated correctly.
- [ ] Production prices are configuration-driven.
- [ ] `Speaking` appears in the existing dashboard role selector.
- [ ] Speaking appears in existing per-user, per-model, per-role, and event views.
- [ ] No separate dashboard architecture is introduced.
- [ ] Existing non-Realtime usage accounting remains unchanged.
- [ ] Telemetry failure does not interrupt Speaking practice.
- [ ] Backend and relevant iOS tests pass.
- [ ] One manual end-to-end Speaking session produces correct dashboard rows.

---

# Non-goals

Do not include in this change unless required for correctness:

- a redesigned expenses dashboard
- per-second session billing approximations
- audio/transcript persistence
- Speaking conversation analytics
- allocation of organization-wide actual cost to individual turns
- broad refactoring of the Responses API accounting code
- changes to Speaking pedagogy or session behavior

The target is a **small, reliable accounting extension** to the existing usage system.
