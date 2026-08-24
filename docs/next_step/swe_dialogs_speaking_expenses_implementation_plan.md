# SWE_Dialogs — Speaking Expense Tracking Implementation Plan

## Goal

Add Speaking / `gpt-realtime-2.1` usage and estimated cost to the existing OpenAI usage dashboard in the same user/model/role/event structure already used for Generator, Interactor, Vocabulary, and Evaluator requests.

Speaking should become another usage role. Do not introduce a separate dashboard or parallel accounting system.

Usage must be observed authoritatively by the backend through an OpenAI Realtime sideband connection. The iOS client must not report provider usage.

## Provider design basis

OpenAI documents that a WebRTC call's `Location` header contains a call ID and that an application server can connect a second WebSocket to the same Realtime session using:

```text
wss://api.openai.com/v1/realtime?call_id={call_id}
```

That sideband connection receives server events and can monitor the session:

- [OpenAI Realtime server-side controls](https://developers.openai.com/api/docs/guides/realtime-server-controls)

OpenAI also documents that conversational Realtime usage is reported per Response in `response.done.response.usage`:

- [OpenAI Realtime cost and usage guide](https://developers.openai.com/api/docs/guides/realtime-costs)

`gpt-realtime-2.1` has distinct text, audio, and image-input pricing:

- [OpenAI `gpt-realtime-2.1` model page](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)

Production rates remain configuration-driven because pricing can change.

## Current architecture

Relevant files:

- `backend/app/main.py`
  - Speaking Realtime bootstrap and teardown endpoints.
  - Speaking expiry-task lifecycle.
  - Admin usage dashboard endpoints and HTML.
  - Existing `available_roles` list.
- `backend/app/realtime_client.py`
  - Creates and hangs up OpenAI Realtime calls.
  - Extracts the provider call ID from the `Location` header.
- `backend/app/speaking_service.py`
  - Builds the Realtime session configuration.
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
- `backend/tests/test_speaking.py`
  - Speaking backend contract and lifecycle tests.

Normal Responses API accounting is backend-authoritative because the backend receives the provider response and its usage. Speaking currently differs because the iPhone holds the WebRTC data channel and the backend does not open a sideband connection.

## Target architecture

```text
iPhone  <---- WebRTC ---->  OpenAI Realtime
                              ^
                              |
                         WebSocket sideband
                              |
                              v
                           Backend
                              |
                    openai_usage_events
                              |
                    Existing usage dashboard
```

For every provider `response.done` received by the backend sideband listener:

1. Validate and extract `response.id` and `response.usage`.
2. Normalize text, audio, image, and cached token details.
3. Calculate modality-aware estimated cost using server configuration.
4. Insert one idempotent `openai_usage_events` row.
5. Let the existing dashboard aggregation include the event.

Use one event per provider Response, not one event per complete Speaking session. This matches the provider billing boundary and gives a natural idempotency key.

# 1. Correct and validate provider call IDs

## File

`backend/app/realtime_client.py`

The current `CALL_ID_PATTERN` accepts only `call_...`. Current OpenAI documentation shows call IDs such as `rtc_123456` and `rtc_u1_...`.

Update the bounded validator to accept the provider forms actually returned by the API, including at least both existing `call_...` values and documented `rtc_...` values. Continue rejecting arbitrary URLs and unbounded identifiers.

Add tests for:

- valid `call_...`
- valid `rtc_...`
- valid documented `rtc_u1_...`
- malformed or oversized IDs
- a `Location` header containing a valid call ID

This correction is required independently of accounting because rejected call IDs also prevent provider hangup.

# 2. Bind Speaking leases to lessons

## File

`backend/app/speaking_service.py`

Extend `SpeakingLease` with:

```text
lesson_id
```

Change `SpeakingSessionRegistry.begin(...)` to receive the validated curriculum `lesson_id` and store it in the lease.

The authoritative identity for a Speaking session must be:

```text
(user_id, lesson_id, speaking_session_id, call_id)
```

Update lease reconstruction, attachment, expiry, finish, abort, drain, and tests so `lesson_id` is never lost.

Although no client usage endpoint remains, binding the lesson is still necessary for correct `source_id` attribution and for all lesson-scoped lifecycle operations.

# 3. Add provider Response idempotency

## File

`backend/app/db.py`

Add the next schema migration, currently expected to be version 13, with:

```sql
ALTER TABLE openai_usage_events
ADD COLUMN provider_response_id TEXT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_openai_usage_provider_response_id
ON openai_usage_events(provider_response_id)
WHERE provider_response_id IS NOT NULL;
```

Do not overload `openai_request_id`:

- Responses API `x-request-id` identifies a provider HTTP request.
- Realtime `response.id` identifies a conversational Response.

Update `record_openai_usage()` to persist `provider_response_id` and return whether a row was inserted. Preserve `INSERT OR IGNORE` idempotency and existing Responses API behavior.

The return value is needed to log `speaking_usage_recorded` versus `speaking_usage_duplicate` accurately.

# 4. Add the backend sideband listener

## Recommended files

- `backend/app/realtime_client.py` for the authenticated WebSocket transport.
- A small focused module such as `backend/app/realtime_usage.py` for event parsing/accounting, if that keeps transport concerns separate.
- `backend/app/main.py` and `backend/app/speaking_service.py` for lifecycle ownership.

Avoid a broad refactor of the existing Responses API client.

## Connection ordering

After the backend creates the OpenAI WebRTC call and receives its SDP answer:

```text
create OpenAI call
→ extract and validate call_id
→ attach call_id to the lesson-bound lease
→ start the sideband listener task
→ return the SDP answer to iOS
```

The listener task must be created before returning the SDP answer. The iPhone cannot produce a conversational Response until it receives the answer and completes its peer connection, which gives the backend a useful ordering advantage for observing the first `response.done`.

If practical, expose a short internal readiness signal from the listener so tests can verify that startup was initiated before the HTTP response returns. Do not make Speaking bootstrap fail solely because sideband accounting cannot connect.

## WebSocket behavior

Connect using the runtime OpenAI inference key:

```text
wss://api.openai.com/v1/realtime?call_id={validated_call_id}
Authorization: Bearer {OPENAI_API_KEY}
```

The listener must:

- receive bounded server event frames
- inspect only the event types required for accounting
- process every valid `response.done`
- ignore unknown future event types safely
- avoid logging full server events
- stop when the lease finishes, expires, aborts, drains during shutdown, or the provider closes the call
- use bounded reconnect attempts/backoff while the lease remains active
- never send conversation mutations or duplicate session configuration

If the sideband connection cannot be established or is disconnected long enough that events may have been missed, Speaking continues normally and the backend records a `speaking_accounting_gap` operational log/metric.

A successful WebRTC bootstrap that returns no valid provider call ID must follow the same non-critical path: return the SDP so Speaking can continue, but emit `speaking_accounting_gap` with a bounded reason such as `missing_call_id` because authoritative per-Response accounting cannot start.

Idempotent `provider_response_id` storage makes reconnect duplicates harmless. Reconnection cannot guarantee replay of events missed while disconnected, so gaps must remain visible rather than being presented as complete accounting.

## Lifecycle ownership

Track sideband tasks by Speaking session ID alongside the existing process-local lease lifecycle. Cancellation and cleanup must be race-safe and idempotent.

Do not allow a listener task to outlive its lease. Graceful backend shutdown should stop listeners and hang up active provider calls using the existing shutdown path.

The deployed one-worker invariant remains unchanged.

# 5. Normalize Realtime usage

## Recommended file

Use a focused helper in `backend/app/realtime_usage.py`, or small Realtime-specific helpers in `backend/app/openai_client.py` if that is simpler.

Parse the documented shape under:

```text
response.done.response.usage
```

Required token categories:

- total text input
- cached text input
- total audio input
- cached audio input
- total image input
- cached image input
- text output
- audio output

Derive uncached tokens per input modality as:

```text
uncached modality input = max(total modality input - cached modality input, 0)
```

Also populate the existing aggregate columns:

```text
input_tokens
cached_tokens
cache_write_tokens = 0
ordinary_input_tokens = max(input_tokens - cached_tokens, 0)
output_tokens
reasoning_tokens
total_tokens
estimated_cost_usd
effective_input_cost_usd
uncached_input_cost_usd
net_cache_savings_usd
raw_usage_json
```

Use `0` or `NULL` for non-applicable fields according to existing table conventions. Do not invent Realtime cache-write tokens.

Validation rules:

- `response.id` must be a non-empty bounded provider identifier.
- Usage and nested detail objects must have the expected types.
- Token counts must be non-negative bounded integers; reject booleans, negative values, NaN-like values, and unreasonable magnitudes.
- Aggregate/detail inconsistencies must be rejected or explicitly flagged; never silently create negative uncached tokens.
- Unknown future fields are ignored.
- Persist only a bounded, sanitized usage object in `raw_usage_json`.

No audio, transcript, output item, instructions, tool arguments, or complete Realtime event may be persisted in usage storage.

# 6. Add modality-aware cost estimation

The existing estimator assumes one text-style input/cached/output rate. Do not feed aggregate Realtime totals into it unchanged.

Add a dedicated helper such as:

```python
def estimated_realtime_cost_metrics(
    settings: Settings,
    model: str,
    usage: dict[str, Any],
) -> dict[str, float | int | None]:
    ...
```

Calculate independently:

```text
uncached text input cost
cached text input cost
uncached audio input cost
cached audio input cost
uncached image input cost
cached image input cost
text output cost
audio output cost
--------------------------------
estimated total cost
```

The official model currently has no image-output modality, so no image-output rate is required.

Derive the existing cost fields as follows:

- `effective_input_cost_usd`: actual uncached plus cached input cost across all modalities.
- `uncached_input_cost_usd`: hypothetical cost if all input tokens in each modality were charged at that modality's uncached rate.
- `net_cache_savings_usd`: `uncached_input_cost_usd - effective_input_cost_usd`.
- `estimated_cost_usd`: effective input cost plus text/audio output cost.

Round consistently with the existing estimator.

## Pricing configuration

Extend `OPENAI_USAGE_PRICE_OVERRIDES_JSON` without breaking existing model entries:

```json
{
  "gpt-realtime-2.1": {
    "text_input_per_million": 0,
    "text_cached_input_per_million": 0,
    "text_output_per_million": 0,
    "audio_input_per_million": 0,
    "audio_cached_input_per_million": 0,
    "audio_output_per_million": 0,
    "image_input_per_million": 0,
    "image_cached_input_per_million": 0
  }
}
```

The zeros illustrate the schema only. Configure current production rates from the official model page during deployment and keep them aligned with account pricing.

If a required rate is absent, usage tokens must still be recorded, but the accounting path must emit a concise missing-pricing warning and must not silently present a partial estimate as complete.

Existing price configuration and cost estimation for Generator, Interactor, Vocabulary, and Evaluator must remain unchanged.

# 7. Create Speaking usage events server-side

For each valid sideband `response.done`, create the event exclusively from trusted server state:

```text
user_id = lease.user_id
request_role = "Speaking"
request_name = "speaking_turn"
source_id = lease.lesson_id
model = settings.speaking_realtime_model
prompt_version = "speaking_realtime_v1"
provider_response_id = response.id
elapsed_ms = 0
```

Attach the normalized token and cost metrics from the provider usage object.

Never accept from iOS:

- usage tokens
- provider Response ID
- billed model
- request role/name
- estimated cost

There is no new iOS usage endpoint, no completed-session upload grace window, and no iOS accounting queue in this design.

# 8. Dashboard integration

## File

`backend/app/main.py`

Add `"Speaking"` to `available_roles`.

Once rows are stored in `openai_usage_events`, the existing dashboard should include them automatically in:

- total estimated cost
- total token usage
- per-user cost
- per-user/model pivot
- role/model totals
- event table
- role filtering

The recorded model must be the exact `settings.speaking_realtime_model` value used to create the session.

No separate Speaking dashboard is needed.

# 9. Actual OpenAI organization cost

Leave the existing organization cost query unchanged.

Speaking events provide local per-user/per-role estimated attribution. The OpenAI organization costs endpoint remains the source for provider-level actual total spend.

Do not allocate organization-wide actual cost back to users or Speaking turns without provider-supported attribution.

# 10. Transcription accounting boundary

The current Speaking session configuration does not enable input transcription, so this change does not add transcription accounting.

If input transcription is enabled later, treat it as a separate billed model/event path. OpenAI reports that usage through `conversation.item.input_audio_transcription.completed`, not the conversational `response.done` bill.

Do not accidentally treat transcription usage as part of `gpt-realtime-2.1` Speaking-turn cost.

# 11. Data integrity and security requirements

The implementation must satisfy all of these:

- Usage is observed from OpenAI on the authenticated server side, not reported by iOS.
- A lease binds user, lesson, Speaking session, and provider call.
- The client cannot choose the billed model, role, token counts, or estimated cost.
- Duplicate `response.done` events never double-count spend.
- Only the configured Speaking model is recorded.
- No audio bytes or transcript are persisted.
- No full Realtime event is logged or stored.
- WebSocket frames, provider identifiers, and numeric usage values are bounded.
- Sideband failure never makes Speaking practice unusable.
- Accounting gaps are observable.
- Existing Responses API accounting remains unchanged.

# 12. Tests

## Call ID and lease tests

Test:

- documented `rtc_...` call IDs are retained
- legacy/current `call_...` IDs remain valid
- invalid call IDs are rejected
- the lease retains `lesson_id` through attach, finish, expiry, and drain
- lifecycle operations cannot mix lessons

## Realtime usage parsing

Test:

- text-only usage
- audio-only usage
- image-only input usage
- mixed text/audio/image usage
- cached text input
- cached audio input
- cached image input
- missing optional details
- malformed, negative, boolean, fractional, or oversized values
- inconsistent aggregates/details
- absent usage
- unknown future fields ignored safely
- output items/transcripts are not retained

## Cost calculation

Use fake pricing and verify exact independent calculations for:

- uncached and cached text input
- uncached and cached audio input
- uncached and cached image input
- text output
- audio output
- effective input cost
- hypothetical uncached input cost
- cache savings
- combined total
- missing pricing behavior

Do not base assertions on production prices.

## Sideband lifecycle

Use a fake WebSocket transport and test:

- listener startup is initiated before the SDP response is returned
- valid `response.done` records one usage event
- multiple Responses record distinct events
- duplicate Response IDs remain idempotent
- unknown events are ignored
- malformed/oversized events are rejected safely
- disconnect/reconnect is bounded
- a possible missed-event interval emits `speaking_accounting_gap`
- listener failure does not fail or end Speaking
- finish, expiry, abort, drain, and shutdown stop the listener
- no listener outlives its lease

## Database/dashboard

Test:

- `provider_response_id` is stored
- `record_openai_usage()` reports inserted versus ignored
- duplicate Response ID is ignored
- different Responses from one session are retained
- Speaking rows appear in `usage_dashboard_summary`
- the exact configured model and lease lesson are recorded
- existing Responses API rows remain unaffected

No iOS accounting tests are required because iOS does not participate in expense telemetry.

# 13. Observability

Add concise structured logs/metrics:

```text
speaking_sideband_started
speaking_sideband_reconnecting
speaking_sideband_stopped
speaking_usage_recorded
speaking_usage_duplicate
speaking_usage_rejected
speaking_accounting_gap
speaking_usage_pricing_missing
```

Include only bounded operational identifiers where relevant:

```text
user_id
lesson_id
speaking_session_id
call_id
provider_response_id
model
reason
```

Never log the OpenAI key, access tokens, SDP, audio, transcripts, raw usage JSON, or full provider events.

The dashboard should continue to show the organization-level actual-cost figure even when a local Speaking accounting gap occurs.

# 14. Suggested implementation order

1. Fix and test `rtc_...`/`call_...` call ID validation.
2. Add `lesson_id` to `SpeakingLease` and update lifecycle tests.
3. Add migration 13 for `provider_response_id`.
4. Extend `record_openai_usage()` and return inserted/not-inserted.
5. Implement and test Realtime usage normalization.
6. Implement and test text/audio/image cost estimation.
7. Add the sideband WebSocket transport.
8. Bind sideband task lifecycle to Speaking leases.
9. Record `response.done` usage events from server-owned lease/settings state.
10. Add `Speaking` to dashboard roles.
11. Run the complete backend test suite.
12. Build the iOS app to confirm the unchanged client contract still compiles.
13. Deploy pricing configuration and backend dependency changes.
14. Run one manual Speaking practice and verify dashboard attribution.

# 15. Manual verification

After deployment/configuration:

1. Open the usage dashboard for a short known period.
2. Note current totals.
3. Start one Speaking practice.
4. Confirm `speaking_sideband_started` appears without sensitive payloads.
5. Complete several tutor Responses and end normally.
6. Refresh the dashboard.
7. Verify:
   - role `Speaking` exists
   - model is the configured Realtime model
   - the correct user and lesson are attributed
   - multiple `speaking_turn` events are visible
   - estimated cost is non-zero when pricing is configured
   - totals increased by the sum of the Speaking events
8. Exercise a duplicate event in a test environment and verify no double charge.
9. Verify normal Generator/Interactor usage remains unchanged.
10. Exercise a sideband connection failure in a test environment and verify Speaking continues while `speaking_accounting_gap` is emitted.
11. Confirm provider call hangup works with the actual returned call ID prefix.

# 16. Acceptance criteria

The feature is complete when:

- [ ] The backend initiates a sideband listener before returning the WebRTC SDP answer.
- [ ] Every observed billable conversational `response.done` produces one local usage event.
- [ ] Speaking usage is attributed to the authoritative lease user and lesson.
- [ ] Duplicate provider Response IDs cannot double-count expense.
- [ ] Text, audio, and image-input pricing is calculated correctly.
- [ ] Production prices are configuration-driven.
- [ ] `Speaking` appears in the existing dashboard views and filters.
- [ ] No client-reported usage endpoint or iOS accounting path exists.
- [ ] No transcript, audio, or full Realtime event is persisted or logged.
- [ ] Sideband failure does not interrupt Speaking and produces an observable accounting-gap signal.
- [ ] Existing non-Realtime accounting remains unchanged.
- [ ] Backend tests and the iOS build pass.
- [ ] One manual end-to-end Speaking session produces correct dashboard rows.

# Non-goals

Do not include unless required for correctness:

- a redesigned expense dashboard
- a separate Speaking dashboard
- per-second session billing approximations
- audio/transcript persistence
- Speaking conversation analytics
- allocation of organization-wide actual cost to individual turns
- input-transcription accounting while transcription remains disabled
- broad refactoring of Responses API accounting
- changes to Speaking pedagogy or session behavior
- iOS expense telemetry

The target is a small, reliable, server-authoritative accounting extension to the existing usage system.
