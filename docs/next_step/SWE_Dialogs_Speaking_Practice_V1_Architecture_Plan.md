# SWE_Dialogs — Speaking Practice V1 Architectural Implementation Plan

**Repository:** `OneSixFive/SWE_Dialogs`  
**Companion product/behavior brief:** `SWE_Dialogs_Speaking_Practice_V1_Brief.md`  
**Architecture status:** proposed implementation path for V1  
**Date:** 2026-08-21

---

## 1. Goal

Implement the already-defined Speaking Practice V1 as a **contained extension of the existing lesson experience**, using OpenAI Realtime speech-to-speech.

This document is deliberately architectural and implementation-oriented. The companion product brief remains the behavioral source of truth for:

- lesson grounding;
- natural roleplay;
- AI-owned dialogue progression;
- learner answer-only behavior;
- selective inline correction;
- correction -> repetition -> roleplay resume;
- patient automatic turn-taking;
- pure speaking with no visible script;
- V1 non-goals.

The implementation should preserve those behaviors without creating a parallel learning subsystem.

The key architectural principle is:

> **Speaking Practice V1 is an ephemeral realtime activity attached to an existing generated lesson, not a new lesson phase or persisted learning object.**

---

# 2. Executive architecture decisions

| Area | V1 decision |
|---|---|
| Product entry point | Existing **Lesson > Menu > Speaking Practice** |
| Realtime transport | **WebRTC**, not WebSocket |
| OpenAI connection bootstrap | **Unified WebRTC interface** through the existing backend |
| Realtime model | Backend-configured `gpt-realtime-2.1` initially |
| Session prompt ownership | **Backend-owned** |
| Lesson context source | Backend curriculum catalog + authenticated user's current stored generated lesson |
| Client OpenAI credentials | **None** |
| Media path after handshake | iPhone <-> OpenAI directly over WebRTC |
| Turn detection | `semantic_vad`, `eagerness: low` |
| Input transcription | **Off** in V1 |
| Visible transcript | **None** |
| Speaking persistence | **None** |
| New DB entity/migration | **None for core V1** |
| Lesson phase | **Do not add `.speaking`** |
| Evaluator integration | **None** |
| Speaking score/history | **None** |
| ROLE/TEACHER switching | Prompt/model-owned, not app state-machine-owned |
| Intended exercise length | Model-owned count of exactly **10 substantive learner replies**; requested correction repetitions do not count |
| Session ending | After reply 10 the model closes naturally and creates no new response opportunity; user can always End; hard technical timeout is 10 minutes on iOS and in the backend/provider call |
| Prompt source | New canonical `Materials/Speaking_prompt.md` |
| WebRTC dependency | Add one maintained iOS WebRTC distribution, pinned and isolated behind an internal transport wrapper |

---

# 3. Why this fits the current repository

The current app already has almost all the lesson-side state Speaking needs:

- `LessonPayload` contains the lesson goal, context, communicative function, scenario, grammar target, vocabulary target, useful chunks, dialogue shape, and complexity guidance.
- `GeneratedLesson` contains the current generated Anna/Erik dialogue.
- `LessonSessionStore` already synchronizes generated lesson/session state to the backend.
- The backend already has the canonical lesson curriculum in `LearningCatalog`.
- The backend already stores each authenticated user's generated lesson in `lesson_sessions`.
- `LessonDetailView` already has the exact menu surface where Speaking should launch.
- Provider API keys are already server-only.

Therefore V1 should **reuse the existing lesson/session boundary instead of inventing a `SpeakingPractice` persistence model**.

Relevant current files:

- `SWE_Dialogs/SWE_Dialogs/LessonModels.swift`
- `SWE_Dialogs/SWE_Dialogs/LessonView.swift`
- `SWE_Dialogs/SWE_Dialogs/LessonSessionStore.swift`
- `SWE_Dialogs/SWE_Dialogs/BackendClient.swift`
- `backend/app/main.py`
- `backend/app/db.py`
- `backend/app/config.py`
- `backend/app/learning_catalog.py`
- `backend/app/openai_client.py`
- `SWE_Dialogs/Info.plist`
- `Materials/`

---

# 4. Explicitly do not extend the existing lesson state machine

Do **not** add:

```swift
case speaking
```

to `LessonPhase`.

Do not modify `LessonState` for Speaking.

Do not append speaking turns to `LessonChatMessage`.

Do not add speaking corrections to `mistakeNotes`.

Do not mark a lesson completed because a Speaking session ended.

Do not enqueue an evaluator job because Speaking was used.

Speaking must remain repeatable regardless of whether the lesson is:

- generated;
- currently in comprehension;
- in discussion;
- in translation;
- already completed.

The existing lesson progression remains exactly what it is.

This avoids coupling an optional repeatable speaking exercise to the linear lesson workflow.

---

# 5. Proposed end-to-end topology

```text
┌───────────────────────────────────────────────────────────────┐
│                         iOS app                               │
│                                                               │
│  LessonDetailView                                             │
│       │                                                       │
│       ├── Lesson menu -> "Speaking Practice"                  │
│       │                                                       │
│       ▼                                                       │
│  SpeakingPracticeView / ViewModel                             │
│       │                                                       │
│       ├── ensure current lesson session is synced             │
│       ├── configure microphone/full-duplex audio              │
│       ├── create WebRTC peer connection                       │
│       ├── create SDP offer                                    │
│       │                                                       │
│       └──── authenticated POST application/sdp ───────────┐   │
└────────────────────────────────────────────────────────────┼───┘
                                                             │
                                                             ▼
┌───────────────────────────────────────────────────────────────┐
│                   existing FastAPI backend                    │
│                                                               │
│  /me/lesson-sessions/{lesson_id}/speaking/realtime-call       │
│       │                                                       │
│       ├── require_user                                        │
│       ├── load canonical LessonPayload from LearningCatalog   │
│       ├── load user's current GeneratedLesson from DB         │
│       ├── build Speaking V1 prompt                            │
│       ├── build server-owned Realtime session config          │
│       │                                                       │
│       └── POST multipart to OpenAI /v1/realtime/calls ────┐   │
└────────────────────────────────────────────────────────────┼───┘
                                                             │
                                                             ▼
┌───────────────────────────────────────────────────────────────┐
│                     OpenAI Realtime API                       │
│                                                               │
│  returns SDP answer to backend -> backend -> iOS              │
│                                                               │
│  After negotiation:                                           │
│                                                               │
│        iPhone  <──── direct WebRTC audio ────> OpenAI          │
│        iPhone  <──── WebRTC data channel ────> OpenAI          │
└───────────────────────────────────────────────────────────────┘
```

The FastAPI backend participates in **session initialization**, not the ongoing audio media path.

---

# 6. Why WebRTC should be the primary V1 transport

OpenAI currently recommends WebRTC over WebSockets when connecting from a client such as a browser or mobile device because it provides more consistent realtime performance.

For SWE_Dialogs this matters more than avoiding a dependency because the feature's core value is:

- natural conversational latency;
- clean full-duplex audio;
- interruption/barge-in;
- reliable playback under variable network conditions;
- natural VAD-driven turns.

A WebSocket implementation would force SWE_Dialogs to own substantially more low-level audio machinery:

- microphone capture;
- PCM conversion;
- audio chunk streaming;
- base64 event transport;
- response audio buffering;
- playback scheduling;
- jitter handling;
- interruption/cancellation;
- output buffer cleanup.

With WebRTC, the peer connection owns the realtime audio transport and the app uses the data channel for Realtime control/events.

### Dependency implication

The Xcode project currently has no package product dependencies. Native Apple frameworks do not provide the same `RTCPeerConnection` API used by OpenAI's WebRTC examples, so V1 will introduce a WebRTC dependency.

Codex should:

1. identify a maintained iOS WebRTC distribution compatible with the project's current Xcode/iOS deployment targets;
2. verify license and maintenance status;
3. verify arm64 physical-device and simulator builds;
4. pin an exact version/revision;
5. isolate the dependency behind SWE_Dialogs-owned code so it does not spread across the app.

Do **not** build both WebRTC and WebSocket transports in V1.

If a stable WebRTC distribution genuinely cannot be integrated, WebSocket + native audio is the fallback, not a parallel implementation.

---

# 7. Use the unified WebRTC bootstrap, not an ephemeral client token

OpenAI currently supports two WebRTC initialization patterns:

1. ephemeral client secrets;
2. unified `/v1/realtime/calls`.

For this app, use the **unified interface**.

The iOS app creates the WebRTC SDP offer and sends it to the SWE_Dialogs backend.

The backend combines:

- the SDP offer;
- the Speaking prompt;
- model;
- voice;
- turn detection;
- other Realtime session configuration;

and calls OpenAI using the server's normal `OPENAI_API_KEY`.

The backend returns the SDP answer to iOS.

### Why this is preferable here

- no OpenAI credential of any kind needs to reach the iPhone;
- the Realtime model is server-controlled;
- the prompt is server-controlled;
- lesson context is server-derived;
- the client cannot accidentally launch a generic or malformed Realtime session;
- it fits the repository's existing "providers are backend-only" security principle;
- the backend already exists and is already required for authenticated lesson operation;
- after initialization, media still flows directly between iPhone and OpenAI.

The backend being in the initialization path is acceptable for SWE_Dialogs.

---

# 8. New backend endpoint

Recommended route:

```http
POST /me/lesson-sessions/{lesson_id}/speaking/realtime-call
Authorization: Bearer <SWE_Dialogs app session JWT>
Content-Type: application/sdp
Accept: application/sdp
```

Request body:

```text
<raw WebRTC SDP offer>
```

Successful response:

```http
HTTP/1.1 201 Created
Content-Type: application/sdp
X-Realtime-Call-ID: <optional OpenAI call id>
X-Speaking-Session-ID: <server lease token>
X-Speaking-Session-Timeout-Seconds: 600
```

Response body:

```text
<raw OpenAI SDP answer>
```

The endpoint returns `201`. The lease retains the OpenAI `call_id` from the bootstrap `Location` header. iOS sends an authenticated `DELETE` with `X-Speaking-Session-ID`; the backend releases the local guard and calls `POST /v1/realtime/calls/{call_id}/hangup`. A server expiry task does the same at 10 minutes, and graceful backend shutdown drains/hangs up retained leases. Client-side WebRTC close remains mandatory.

### Endpoint responsibilities

The route must:

1. authenticate with existing `require_user`;
2. validate `lesson_id`;
3. bound the SDP request body size;
4. load the canonical lesson from `get_learning_catalog().lesson(lesson_id)`;
5. load the authenticated user's current `lesson_session`;
6. require a current `generated_lesson`;
7. project and validate only the Speaking reference dialogue: matching lesson ID, exactly 20 lines, Anna/Erik speakers only, bounded non-empty single-line text, bounded total size, and no unrelated generated-lesson fields forwarded;
8. build the Speaking prompt on the server;
9. build the Realtime session configuration on the server;
10. call `POST https://api.openai.com/v1/realtime/calls`;
11. enforce one active session per user, a 10-second start cooldown, and at most 6 starts per 10-minute window in the current single-worker deployment;
12. return only the SDP answer and safe metadata to iOS;
13. never return the OpenAI standard API key;
14. never log the raw SDP, prompt contents, microphone content, or transcript.

### Error behavior

Use explicit, recoverable errors.

Examples:

- `404`: curriculum lesson does not exist;
- `409`: lesson has not been generated/synced yet;
- `413`: unreasonable SDP size;
- `502`: OpenAI rejected session creation;
- `503`: temporary Realtime/session initialization failure.

Do not expose raw OpenAI error bodies if they may contain implementation details.

---

# 9. The backend must be the source of Speaking lesson context

Do **not** let the iOS client send arbitrary:

- system instructions;
- model IDs;
- voice configuration;
- lesson payload;
- Realtime tools.

The backend should derive the context from existing trusted sources.

## Canonical lesson payload

Use:

```python
catalog = get_learning_catalog()
lesson = catalog.lesson(lesson_id)
payload = lesson.payload
```

`LearningCatalog` already loads the lesson JSON under `Materials/Lessons`.

## Current generated dialogue

Use the authenticated user's current `lesson_sessions.generated_lesson_json`.

This gives Speaking the **actual current generated dialogue**, including after lesson regeneration.

## Sync requirement

Before opening a Speaking session, the app must prove that its current generated lesson has finished syncing to the backend.

The existing `LessonSessionStore.uploadDirtySessions()` already provides the underlying sync behavior and is already used before server-dependent lesson-audio work.

For Speaking, avoid a silent race in which:

1. user regenerates a lesson locally;
2. old server generation is still stored;
3. user immediately launches Speaking;
4. backend starts roleplay against the stale dialogue.

Provide a lesson-specific, throwing/observable `ensureLessonSynced(...)` path for Speaking startup.

It may reuse/refine the existing sync machinery, but Speaking should not proceed until either:

- the current generation is confirmed server-side; or
- startup fails visibly and offers retry.

Do not solve this by creating a duplicate Speaking copy of the lesson in a new table.

---

# 10. No new Speaking database model in V1

Core V1 should require **no DB migration**.

Do not create:

- `speaking_practices`;
- `speaking_turns`;
- `speaking_scores`;
- speaking transcript tables;
- speaking mistake tables;
- speaking evaluation jobs.

The existing legacy/general `dialog_sessions` tables should also **not** be repurposed merely because their names look relevant.

The realtime conversation exists in the OpenAI Realtime session and in temporary iOS memory only.

When the practice ends, that ephemeral conversation state is discarded.

This is intentional.

---

# 11. Backend module separation

Do not overload the current Responses API code path with WebRTC session creation.

Recommended ownership:

```text
backend/app/
    main.py
    config.py
    models.py
    openai_client.py           # keep existing Responses API responsibilities
    realtime_client.py         # NEW: OpenAI Realtime call/bootstrap HTTP
    speaking_service.py        # NEW or equivalent: context + prompt/session config
```

Exact names are flexible, but responsibilities should stay separated.

## `realtime_client.py`

Own low-level OpenAI Realtime REST initialization:

- `/v1/realtime/calls`;
- multipart `sdp` + `session`;
- auth header;
- safety identifier;
- timeout/error mapping;
- response SDP;
- optional call ID extraction from `Location`.

It should not know SWE_Dialogs pedagogy.

## `speaking_service.py`

Own SWE_Dialogs-specific assembly:

- load `Materials/Speaking_prompt.md`;
- select compact lesson context;
- assign the AI role;
- serialize the reference dialogue;
- build final instructions;
- build Realtime session configuration.

It should be pure/testable wherever possible.

## `main.py`

Own HTTP/auth boundary only.

---

# 12. New prompt source: `Materials/Speaking_prompt.md`

Repository rules say prompt source files live in `Materials/`.

Create:

```text
Materials/Speaking_prompt.md
```

This must be the **single canonical source** of the Speaking role instructions.

Do not add a second bundled copy to the iOS project.

Do not hard-code a divergent copy inside `SpeakingPracticeView`.

Do not duplicate the same full prompt in backend tests.

Tests may assert excerpts/invariants.

---

# 13. Speaking prompt composition

The runtime instructions should be composed as:

```text
[stable Speaking_prompt.md]

[dynamic lesson context]

[reference dialogue]

[role assignment]
```

Keep the stable behavioral instructions at the top and the lesson-specific data after them.

A conceptual shape:

```text
<stable Speaking V1 instructions>

=== LESSON CONTEXT ===
<compact canonical JSON>

=== REFERENCE DIALOGUE ===
<Anna/Erik lines>

=== ROLE ASSIGNMENT ===
AI role: ...
Learner role: ...
```

The model should get enough context to make the practice purposeful without receiving unrelated lesson machinery.

---

# 14. Dynamic lesson context to include

Send the normal **full canonical lesson payload** exactly as loaded from `LearningCatalog`. Do not rewrite it, derive mandatory learner speech acts, or maintain a Speaking-specific curriculum projection. The prompt hierarchy—not preprocessing—makes guided/passive mode override incompatible lesson objectives.

The generated lesson is handled differently: only its validated 20-line reference-dialogue projection is forwarded, never the raw stored dictionary.

---

# 15. Reference dialogue serialization

Pass the current generated dialogue as data:

```json
[
  {"speaker": "Anna", "text": "..."},
  {"speaker": "Erik", "text": "..."}
]
```

The prompt must repeatedly make clear at the behavioral level that:

> The generated dialogue is a reference realization of the lesson, not a script.

Do not programmatically derive a list of mandatory line-by-line beats.

Do not create a 20-step state machine from the reference dialogue.

Do not compare learner speech against Anna/Erik's exact line text.

The model should own local adaptation.

---

# 16. Model-owned V1 counterpart assignment

The learner is always themselves in the real-life situation. The model chooses and keeps the active counterpart role that makes an AI-driven answer-only interaction natural. Do not derive that role from the first Anna/Erik line and do not make the learner inherit either fictional speaker's biographical facts.

The invariant is behavioral: the AI always initiates and owns progression, while each normal turn gives the learner a clear response opportunity. The learner may initiate spontaneously, but must never be required to do so.

---

# 17. The ROLE <-> TEACHER loop should remain model-owned

Do not create an application state machine such as:

```swift
enum TutorMode {
    case roleplay
    case correcting
    case awaitingRepetition
}
```

for V1 unless actual testing demonstrates the model cannot maintain the contract itself.

The Realtime conversation already contains:

- the model's prior role turn;
- learner audio;
- correction;
- requested repetition;
- learner repetition.

The session prompt should govern the transition.

The app only needs transport/session UI states such as:

```swift
enum SpeakingConnectionState {
    case idle
    case preparing
    case connecting
    case active
    case ending
    case failed(String)
}
```

Optional ephemeral indicators like `userSpeaking` or `assistantSpeaking` can be driven from Realtime/WebRTC events, but they are not pedagogical state.

This keeps the code aligned with the V1 hypothesis:

> Good Realtime prompting should be responsible for teacher-like conversational behavior.

---

# 18. Realtime session configuration

Initial server-owned configuration should be approximately:

```json
{
  "type": "realtime",
  "model": "gpt-realtime-2.1",
  "instructions": "<assembled speaking instructions>",
  "output_modalities": ["audio"],
  "max_output_tokens": 256,
  "audio": {
    "input": {
      "noise_reduction": {
        "type": "near_field"
      },
      "turn_detection": {
        "type": "semantic_vad",
        "eagerness": "low",
        "create_response": true,
        "interrupt_response": true
      }
    },
    "output": {
      "voice": "marin"
    }
  }
}
```

Treat this as the intended V1 configuration, while validating exact current API field names against the live OpenAI schema during implementation.

## Model

Start with:

```text
gpt-realtime-2.1
```

Use the full model first because V1 depends heavily on:

- instruction following;
- role persistence;
- selective correction;
- clean role -> teacher -> role switching;
- natural Swedish interaction.

Do not optimize to `gpt-realtime-2.1-mini` before the full-model behavior is accepted.

Make the model environment-configurable.

## Voice

Start with `marin`, which OpenAI currently recommends alongside `cedar` for best quality.

Make voice backend-configurable so Swedish quality can be A/B tested without app changes.

## Turn detection

Use:

```json
{
  "type": "semantic_vad",
  "eagerness": "low"
}
```

This maps directly to the agreed product behavior:

> automatic, but deliberately patient.

OpenAI documents `low` semantic VAD as waiting longer when the user may not be finished; its maximum semantic wait is currently longer than medium/high settings.

This should be tested specifically with Swedish learner hesitation.

## Interruption

Keep:

```json
"interrupt_response": true
```

If the learner starts speaking while the AI is still talking, the AI response should be interruptible.

This is important for natural voice behavior.

## Input transcription

Leave **off** in production V1.

Reasons:

- Realtime consumes the audio natively;
- no evaluator needs a transcript;
- no visible transcript is allowed;
- ASR transcription is a separate process and extra cost;
- it introduces another representation that can disagree with what the voice model actually heard.

## Output transcript

Realtime audio responses include text transcripts in events.

The app may parse enough event metadata to drive debugging/status, but should not display or persist the transcript in V1.

## Tools

No tools are required for core V1.

Do not introduce a tool merely to model ROLE/TEACHER switching.

## Reasoning effort

`gpt-realtime-2.1` supports configurable reasoning, but do not make reasoning tuning a dependency of the first implementation.

Start with the API/model default unless the current Realtime session schema exposes a stable field that Codex can verify.

Only tune this after measuring latency and role/correction quality.

---

# 19. Trigger the first AI turn explicitly

Because the AI owns progression, it must also **start** the interaction.

After:

1. WebRTC connection is established;
2. the Realtime data channel is open;

the client should send one minimal `response.create` event to cause the model to produce its opening roleplay turn based on the session instructions.

Conceptually:

```json
{
  "type": "response.create"
}
```

The session prompt should contain the rule that the first model response must:

- enter the assigned role immediately;
- establish the scenario naturally;
- create the first clear response opportunity;
- not explain the exercise unless necessary.

Do not require the learner to say "start".

---

# 20. Ongoing event handling on iOS

The WebRTC audio track handles speech media.

The data channel should be used only for the event layer needed by the UX.

At minimum handle:

- session created/ready;
- errors;
- user speech started/stopped;
- response created;
- assistant audio playback started/stopped where available;
- response done;
- connection/disconnection state.

Use these to drive simple UI states such as:

- Connecting…
- Listening…
- Speaking…
- Reconnecting/Failed…

After SDP negotiation, require the data channel to reach `.open` within 25 seconds. If it does not, close the transport, invoke the normal backend DELETE/provider-hangup path, and show retry instead of remaining in Connecting until the 10-minute cap.

Do not render a conversational transcript.

Do not expose raw JSON event logs in production UI.

Do not store audio event payloads.

---

# 21. iOS architecture

Recommended new app-side pieces:

```text
SWE_Dialogs/SWE_Dialogs/
    SpeakingPracticeView.swift
    SpeakingPracticeViewModel.swift
    RealtimeSpeakingClient.swift
```

Exact file splitting is flexible, but keep concerns separated.

## `SpeakingPracticeView`

Owns presentation only:

- minimal lesson situation/goal;
- connection/status UI;
- microphone state;
- end button;
- retry on startup failure;
- no reference dialogue;
- no response suggestions;
- no transcript.

## `SpeakingPracticeViewModel`

Owns session lifecycle:

- prepare/sync;
- permission flow;
- create/start realtime client;
- update observable connection/speaking state;
- end/cleanup;
- react to app scene changes;
- convert transport errors into user-facing errors.

It should not parse pedagogy or implement correction logic.

## `RealtimeSpeakingClient`

Owns transport:

- WebRTC factory/peer connection;
- local microphone track;
- remote audio track;
- data channel;
- SDP offer creation;
- backend SDP exchange;
- remote SDP answer;
- Realtime event send/receive;
- peer close/cleanup.

Hide the third-party WebRTC API behind this type.

Prefer a small protocol around it so unit tests can use a fake transport.

---

# 22. `BackendClient` addition

Add one dedicated non-JSON helper such as:

```swift
func createSpeakingRealtimeCall(
    lessonID: String,
    sdpOffer: String
) async throws -> SpeakingRealtimeCallAnswer
```

Possible result:

```swift
struct SpeakingRealtimeCallAnswer {
    let sdp: String
    let callID: String?
}
```

This method should:

- call the SWE_Dialogs backend, not OpenAI;
- authenticate with the existing app JWT from Keychain;
- send `Content-Type: application/sdp`;
- read an `application/sdp` response;
- optionally read an `X-Realtime-Call-ID` response header;
- use short session-init network timeouts;
- map backend failures into existing `BackendError` style.

Do not force raw SDP into the generic JSON helpers.

---

# 23. Lesson menu integration

The current insertion point is `LessonExpandedPanel.menuContent`.

Add:

```text
Speaking Practice
```

with an appropriate microphone/waveform icon.

The action should propagate from:

```text
LessonExpandedPanel
    -> LessonDetailView
    -> presentation state
    -> SpeakingPracticeView
```

A `fullScreenCover` is a good fit because:

- Speaking is intentionally immersive;
- the lesson dialogue must not remain visible behind/alongside it;
- audio session lifetime maps cleanly to presentation lifetime;
- dismissal provides a clear cleanup boundary.

A sheet is acceptable if testing produces better UX, but avoid showing the reference dialogue simultaneously.

---

# 24. Do not require lesson audio readiness

Speaking depends on:

- `LessonPayload`;
- `GeneratedLesson`;
- backend sync;

not on the pre-generated listening WAV.

Therefore:

- the Speaking menu item should be available once a generated lesson exists;
- it should not need the lesson TTS file to be ready;
- it should not call the lesson audio generation pipeline.

However, if lesson audio is currently playing, pause/stop it before Speaking starts.

---

# 25. Audio-session ownership on iOS

Speaking requires full-duplex microphone + speaker audio.

Configure an audio session appropriate for voice chat / play-and-record.

Requirements:

- microphone input;
- speaker output;
- Bluetooth headset support where practical;
- echo/call-style processing appropriate for realtime conversation;
- no simultaneous playback from `LessonInlineAudioPlayer`;
- clean deactivation/restoration on exit.

The exact WebRTC audio-session API depends on the selected iOS WebRTC package; keep that implementation inside the Speaking transport layer as much as possible.

Do not build a second `AVAudioEngine` pipeline if WebRTC already owns capture/playback.

---

# 26. Microphone permission

Add to `SWE_Dialogs/Info.plist`:

```xml
<key>NSMicrophoneUsageDescription</key>
<string>...</string>
```

Use a user-facing explanation specific to speaking practice.

Before connection startup:

1. determine microphone authorization;
2. request it if not determined;
3. if denied, do not attempt a Realtime call;
4. show a clear state that lets the learner open iOS Settings or cancel.

The existing `UIBackgroundModes` audio entry does not replace microphone permission.

---

# 27. Backgrounding and lifecycle

Despite the app already enabling background audio, **do not keep Speaking Practice running in the background in V1**.

On:

- full-screen view dismissal;
- app moving out of active foreground;
- unrecoverable WebRTC disconnect;

end the Speaking session and release the microphone.

Reasons:

- avoids surprise microphone use;
- avoids accidental Realtime cost;
- avoids a large background-call lifecycle feature;
- V1 sessions are short and repeatable.

Returning to the app can start a new Speaking session.

No cross-session resume is required.

---

# 28. Network failure/reconnect policy

Do not build conversation-state reconnection in V1.

If the peer connection fails irrecoverably:

1. close the current connection;
2. release audio resources;
3. show a retry action;
4. retry starts a **new** Realtime roleplay session from the lesson context.

Because V1 intentionally persists no speaking transcript/history, reconstructing a partially completed Realtime conversation is out of scope.

---

# 29. Ending the practice

The model should be prompted to bring the roleplay to a natural conclusion once the lesson's communicative purpose has been sufficiently exercised.

However, do **not** add a semantic completion detector, evaluator, or finish tool in V1 solely to decide when the UI should dismiss.

The UI should always provide an explicit:

```text
End practice
```

control.

When the model naturally reaches a closing:

- it should stop creating new conversational demands;
- the learner can end the session.

If the learner speaks again, the model can respond naturally, but it should not invent unrelated material merely to keep the call alive.

A future version can add an explicit model-side completion signal if product testing shows it is necessary.

---

# 30. Session cleanup

A single idempotent cleanup path should:

- stop local microphone capture;
- close data channel;
- close peer connection;
- detach remote track;
- deactivate/release realtime audio session;
- clear in-memory event state;
- cancel pending startup requests;
- stop UI timers/observers.
- call the authenticated backend DELETE so the retained provider `call_id` is hung up;

Call the same cleanup from:

- End button;
- dismiss;
- scene backgrounding;
- connection failure;
- startup cancellation.

Do not rely only on SwiftUI deallocation to stop microphone/audio.

---

# 31. Backend configuration

Extend `Settings` with backend-owned Speaking configuration.

Recommended environment keys:

```text
OPENAI_SPEAKING_REALTIME_MODEL=gpt-realtime-2.1
OPENAI_SPEAKING_REALTIME_VOICE=marin
OPENAI_SPEAKING_REALTIME_MAX_OUTPUT_TOKENS=256
OPENAI_SPEAKING_REALTIME_TIMEOUT_SECONDS=20
SVENSKA_SPEAKING_SESSION_TIMEOUT_SECONDS=600
SVENSKA_SPEAKING_START_COOLDOWN_SECONDS=10
SVENSKA_SPEAKING_START_WINDOW_SECONDS=600
SVENSKA_SPEAKING_MAX_STARTS_PER_WINDOW=6
```

Optional later tuning keys can be added only if needed.

Defaults can live in `Settings`:

```python
speaking_realtime_model: str = "gpt-realtime-2.1"
speaking_realtime_voice: str = "marin"
speaking_realtime_max_output_tokens: int = 256
speaking_session_timeout_seconds: int = 600
```

Do not expose these as iOS settings in V1.

Prompt version should also be explicit in code/logs, e.g.:

```text
speaking_v1
```

---

# 32. OpenAI safety identifier

When the backend calls `/v1/realtime/calls`, include `OpenAI-Safety-Identifier`.

Derive a stable privacy-preserving identifier from the authenticated SWE_Dialogs user ID.

Do not send the raw numeric user ID.

A deterministic HMAC/hash using a server secret and namespaced user ID is sufficient.

Example concept:

```text
HMAC_SHA256(server_secret, "speaking:<internal_user_id>")
```

This header is server-generated.

The iOS client should never choose it.

---

# 33. Logging and privacy

Production logging may include:

- internal user ID;
- lesson ID;
- prompt version;
- configured model;
- configured voice;
- session initialization success/failure;
- truncated/hashed OpenAI call ID;
- elapsed session-bootstrap time.

Do **not** log:

- raw SDP;
- raw prompt;
- learner audio;
- learner transcript;
- assistant transcript;
- full dialogue context;
- API keys.

A prompt hash may be logged if useful for diagnostics.

---

# 34. Realtime usage/cost telemetry

Do not let billing telemetry bloat or block the core V1.

The current `openai_usage_events` schema is designed around Responses API-style aggregate token fields. Realtime `response.done` usage separates:

- text input tokens;
- audio input tokens;
- cached token details;
- text output tokens;
- audio output tokens.

Those token classes have different prices.

Therefore:

> **Do not stuff mixed Realtime usage into the current cost estimator in a way that produces misleading per-user dollars.**

For initial V1:

- rely on OpenAI organization-level actual cost for authoritative billing;
- optionally log/count successful Speaking session starts;
- leave the current per-user token-cost dashboard unchanged unless Codex intentionally extends it to represent Realtime audio/text token classes correctly.

If usage accounting is implemented in the same change, it should be a separate, explicit subtask with:

- audio/text token columns or structured raw usage;
- correct pricing rules;
- deduplication by Realtime response ID;
- no assumption that generic `input_tokens * text_price` is correct.

This should **not block the feature**.

---

# 35. Prompt architecture is the main quality-critical layer

Most pedagogical behavior should come from `Speaking_prompt.md`, not code branches.

The stable prompt should express the following as hard behavioral invariants.

## A. Lesson grounding

- This is a speaking extension of one specific lesson.
- Preserve scenario, communicative goal, difficulty, target grammar, target vocabulary, and useful chunks.
- The lesson payload is the pedagogical source of truth.
- The reference dialogue is an example, not a script.

## B. Natural adaptation

Use the exact principle:

> **Follow the learner locally; follow the lesson globally.**

React naturally to the learner's actual answer.

Do not pull them back to fictional details or exact original lines.

## C. AI owns progression

- AI always initiates.
- Learner primarily answers.
- Never wait for learner to ask the next question.
- Never require learner to introduce the next topic.
- Every role turn creates a clear response opportunity.
- A response opportunity need not be a literal question.

## D. Selective correction

After each learner answer, implicitly decide:

```text
Is there a significant, high-confidence error worth interrupting for?
```

If no:

```text
stay in role -> react -> advance
```

If yes:

```text
leave role briefly
-> correct ONE issue
-> give correct Swedish form
-> ask learner to repeat
-> wait
-> accept sufficiently good repeat
-> return immediately to role
-> advance
```

Prioritize:

- main grammar target;
- active vocabulary/useful chunks;
- meaning-changing errors;
- clearly unnatural/comprehension-blocking language.

Usually ignore:

- minor unrelated imperfections;
- harmless style differences;
- natural alternatives to reference wording.

## E. Repetition

Once a correction is made, do not advance until the learner has attempted the corrected form.

Do not demand robotic exact copying if the learner gives a natural equivalent that fixes the issue.

Do not get stuck in perfection loops.

## F. Teacher mode must stay brief

No long grammar lecture unless learner explicitly asks.

Correction should be conversationally cheap.

ROLE mode should dominate the session.

## G. Learner asks a question

Answer it naturally and briefly, then reassert control by creating the next response opportunity.

## H. Hesitation

Learner pauses, fillers, word searching, and self-correction are normal.

Do not interpret ordinary hesitation as a request to seize the turn.

Semantic VAD helps at transport/session level; prompt behavior should reinforce patience.

## I. Stuck learner

Scaffold progressively:

1. repeat/simplify;
2. rephrase;
3. lexical cue;
4. starter phrase;
5. full model only if necessary.

Then get learner speaking again.

## J. No pronunciation grading

Do not systematically diagnose pronunciation or score accent.

If speech is not understood, ask for repetition naturally.

---

# 36. Keep prompt state simpler than app state

The model only needs one conceptual behavioral loop:

```text
AI role turn
    ↓
learner response
    ↓
significant correction needed?
    ├── no  -> AI role turn advances
    └── yes -> brief teacher correction
                 ↓
              learner repeats
                 ↓
              AI role turn advances
```

Do not add artificial hidden phase counters such as:

```text
opening_step = 2
middle_step = 5
correction_step = 1
```

unless actual prompt evaluation proves they are necessary.

The reference dialogue and `dialogue_shape` provide enough global trajectory.

---

# 37. UI design for the Speaking full-screen view

The screen should contain only what is needed for a live voice session.

Recommended:

```text
<back/end>

Speaking practice

Situation
<short real-life context/scenario>

Goal
<one-sentence communicative goal>

<large realtime status / subtle animation>
Listening...
or
Speaking...

[ End practice ]
```

Optional:

- mute button if easy;
- audio route indicator;
- retry state.

Do not show:

- Anna/Erik transcript;
- live learner transcription;
- live assistant transcription;
- suggested answer;
- grammar target list;
- target vocabulary list;
- chat history.

The prompt gets the pedagogical detail; the learner should experience the conversation.

---

# 38. Avoid coupling Speaking to the current text tutor

Do not route speech turns through:

```text
/lessons/message
```

Do not convert voice -> text -> current Lesson Interactor -> TTS.

That would:

- add latency;
- lose native speech-to-speech behavior;
- undermine natural interruption;
- create two competing conversational state machines;
- make correction/resume much harder.

Speaking V1 should be a separate Realtime session whose **context comes from the same lesson**, not a voice skin over the existing chat interactor.

---

# 39. Avoid coupling Speaking to generated lesson audio

Do not reuse:

- Gemini lesson TTS generation;
- WAV cache;
- `lesson_audio_jobs`;
- `AudioPlayerController` as the Realtime transport.

Listening audio and Speaking Realtime audio are distinct responsibilities.

The only interaction should be:

> pause/stop lesson playback before starting full-duplex Speaking.

---

# 40. Backend tests

Add focused tests for the new path.

## Prompt/context builder tests

Given a known lesson + generated dialogue, assert that the assembled context contains:

- correct lesson ID;
- level;
- scenario;
- communicative goal;
- main grammar target;
- active vocabulary;
- useful chunks;
- dialogue shape;
- exact current generated dialogue;
- full canonical lesson payload;
- model-owned active-counterpart guidance;
- guided/passive mode overriding incompatible targets;
- exactly 10 substantive learner replies, excluding requested correction repetitions.

Assert that it does **not** accidentally include:

- lesson chat history;
- evaluator state;
- learner mistake notes;
- translation attempts;
- unrelated learning targets.

## Endpoint tests

Mock the OpenAI Realtime REST call and cover:

1. auth required;
2. valid generated lesson -> OpenAI call created;
3. missing curriculum lesson -> 404;
4. missing generated lesson -> 409;
5. generated lesson ID mismatch -> reject;
6. oversized/malformed SDP -> reject;
7. OpenAI 4xx/5xx -> safe backend error;
8. session config uses server-owned model and prompt;
9. semantic VAD low is present;
10. active-session/cooldown/rate leases are enforced;
11. explicit DELETE and server expiry invoke provider hangup with the retained call ID;
12. no DB lesson state mutation occurs.

## Realtime client serialization tests

Test the multipart request builder separately from live OpenAI.

Do not make normal backend unit tests require a live Realtime session.

---

# 41. iOS tests

## View-model tests with fake Realtime client

Test:

- preparation -> connecting -> active;
- startup failure -> retry;
- End -> cleanup;
- background -> cleanup;
- microphone denial -> no network call;
- data channel never opens -> fail and clean up after 25 seconds;
- speaking launch does not mutate `LessonState`;
- speaking launch does not append lesson chat messages.

## BackendClient tests

Test:

- authenticated SDP request;
- content type;
- response parsing;
- error mapping;
- optional call ID header.

## UI tests

At minimum:

- Speaking Practice menu item is present for generated lesson;
- tapping it opens the Speaking surface;
- dialogue text is not displayed in Speaking;
- End dismisses.

---

# 42. Physical-device manual QA is mandatory

A simulator/build test is not sufficient for this feature.

Run acceptance testing on the configured physical iPhone development device.

Test with:

- iPhone microphone + speaker;
- AirPods/Bluetooth if available;
- Wi-Fi;
- mobile network if practical.

Core scenario matrix:

### Natural roleplay

- ordinary answer;
- unexpected but valid answer;
- learner volunteers extra information;
- learner asks the AI a question.

### Correction

- obvious target-grammar error;
- target-vocabulary misuse;
- minor unrelated error that should pass;
- corrected repetition;
- imperfect but acceptable corrected repetition.

### Hesitation

- 1-2 second pause;
- 3-5 second word search;
- long "eh… jag…" unfinished phrase;
- self-correction before completing sentence.

Verify semantic VAD `low` does not constantly jump in too early.

### Interruption

- learner starts speaking while AI is speaking;
- verify assistant audio stops/handles barge-in naturally.

### Stuck learner

- explicit "I don't know how to say…";
- silence/hesitation;
- request slower speech;
- request repetition.

### Lifecycle

- deny microphone;
- disconnect network;
- background app;
- dismiss mid-response;
- start while lesson audio is playing;
- retry after failure.

---

# 43. Prompt acceptance tests are more important than code cleverness

Before expanding architecture, manually evaluate whether `gpt-realtime-2.1` reliably follows these four invariants:

1. **AI always drives.**
2. **Reference is not treated as a script.**
3. **Corrections are selective.**
4. **Correction -> repetition -> return to role works cleanly.**

If failures occur, first improve:

- prompt ordering;
- prompt wording;
- examples;
- context compactness;
- session VAD configuration.

Do not immediately respond by adding a large client-side pedagogical state machine.

The product hypothesis is specifically that current Realtime instruction following is strong enough to carry this behavior.

---

# 44. Suggested implementation sequence

## Phase 0 — create/claim repository work item

Per repository workflow, this is medium/large functionality.

Create or claim the appropriate `bd` issue before implementation and keep the working tree clean.

## Phase 1 — Realtime backend bootstrap in isolation

Implement:

- config;
- `Materials/Speaking_prompt.md`;
- prompt/context builder;
- `/realtime/calls` server client;
- authenticated SDP endpoint;
- backend tests.

Validate with a minimal SDP/WebRTC harness if useful before wiring UI.

## Phase 2 — iOS WebRTC transport spike

Before broader UI work:

- integrate/pin WebRTC dependency;
- establish one Realtime call from physical iPhone;
- send mic audio;
- receive model audio;
- open data channel;
- trigger initial response;
- close cleanly.

Do not build final UI before this transport path works.

## Phase 3 — lesson integration

Implement:

- Speaking menu action;
- current-lesson sync guarantee;
- full-screen Speaking view;
- lesson audio pause;
- microphone permission;
- lifecycle cleanup.

## Phase 4 — production Speaking prompt

Port the companion behavior brief into `Materials/Speaking_prompt.md`.

Iterate against several real lessons.

Focus most effort here.

## Phase 5 — QA/hardening

Run:

- backend tests;
- iOS unit tests;
- full Xcode build/tests;
- physical-device roleplay matrix;
- network/lifecycle tests.

Only after full-model behavior is stable should cost/model experiments begin.

---

# 45. Expected files to add

Likely additions:

```text
Materials/Speaking_prompt.md

backend/app/realtime_client.py
backend/app/speaking_service.py
backend/tests/test_speaking_service.py
backend/tests/test_realtime_speaking.py

SWE_Dialogs/SWE_Dialogs/SpeakingPracticeView.swift
SWE_Dialogs/SWE_Dialogs/SpeakingPracticeViewModel.swift
SWE_Dialogs/SWE_Dialogs/RealtimeSpeakingClient.swift
```

Exact test filenames may follow current repo conventions.

---

# 46. Expected files to modify

Likely:

```text
backend/app/config.py
backend/app/main.py

SWE_Dialogs/SWE_Dialogs/BackendClient.swift
SWE_Dialogs/SWE_Dialogs/LessonView.swift
SWE_Dialogs/Info.plist

SWE_Dialogs/SWE_Dialogs.xcodeproj/project.pbxproj
```

Potentially:

```text
SWE_Dialogs/SWE_Dialogs/LessonSessionStore.swift
```

only to expose a reliable "ensure current lesson is synced" operation for Speaking startup.

No `LessonModels.swift` change should be necessary for core V1 unless small transport-only DTOs are placed there; prefer dedicated Speaking types.

No `db.py` migration should be necessary.

---

# 47. Things Codex should actively avoid

Do not:

- add a Speaking tab;
- create `.speaking` in `LessonPhase`;
- create a persisted Speaking practice entity;
- run evaluator after Speaking;
- persist audio;
- persist transcripts;
- expose transcripts in UI;
- display the original dialogue during Speaking;
- require learner questions;
- build a fixed 20-turn script runner;
- compare user speech to exact reference lines;
- use current `/lessons/message` for speech;
- use Gemini lesson TTS for response speech;
- implement systematic pronunciation scoring;
- build both WebRTC and WebSocket versions;
- place the OpenAI API key on device;
- let the client supply arbitrary Realtime instructions/model;
- add a server-side sideband WebSocket unless a concrete V1 requirement emerges;
- add function tools just to implement correction state;
- build semantic speaking completion/evaluation in V1;
- silently report inaccurate Realtime cost through the existing text-token estimator.

---

# 48. Important deliberate simplifications

V1 deliberately accepts these limitations:

### A. No cross-session continuity

Every launch is a fresh roleplay.

### B. No persisted evidence

The app does not "learn" from Speaking yet.

### C. No automatic mastery update

Corrections live only in the live session.

### D. No transcript review

The value is live speaking/correction.

### E. No phonetic scoring

Realtime speech understanding is used for conversation, not as a formal pronunciation evaluator.

### F. No automatic UI completion signal

The model should conclude naturally; the learner can end the practice.

### G. One model/voice globally

Backend config controls it. No learner-facing picker.

These are features of the V1 scope, not omissions to "fix" during implementation.

---

# 49. Future-compatible seams without overbuilding

The design should make these later changes possible without implementing them now:

- swap `gpt-realtime-2.1` for a newer Realtime/Live API model;
- test `gpt-realtime-2.1-mini`;
- add a dedicated Speaking tab;
- persist transcript/evidence;
- post-session structured evaluation;
- speaking history;
- stage-level roleplay;
- learner-led/free roleplay;
- explicit model-side completion signal;
- pronunciation-specific service.

The main seam that enables this is:

```text
Lesson context builder
        +
backend-owned Realtime session config
        +
isolated iOS Realtime transport
```

Do not create abstractions for features that do not yet exist.

---

# 50. Architectural acceptance criteria

Implementation is architecturally complete when all of the following are true.

## Security

- no standard OpenAI key is present in iOS;
- Realtime prompt/model are backend-owned;
- route requires existing user authentication;
- raw audio/transcript is not stored by SWE_Dialogs;
- microphone permission is explicit;
- session ends on background/dismiss.

## Repository fit

- prompt lives in `Materials/`;
- no duplicate prompt copy exists;
- current Lesson menu owns the entry point;
- existing lesson state/evaluator logic is unchanged;
- no unnecessary DB migration exists.

## Realtime transport

- physical iPhone establishes WebRTC successfully;
- microphone reaches Realtime model;
- model audio plays cleanly;
- barge-in works;
- data channel works;
- initial AI turn is triggered automatically;
- cleanup reliably releases mic/connection.
- explicit end and timeout terminate the provider call through the retained `call_id`.

## Context correctness

- backend uses canonical `LearningCatalog` payload;
- backend uses the user's current generated dialogue;
- stale generation is not silently used after regeneration;
- prompt includes the correct lesson targets;
- client cannot replace the lesson context with arbitrary prompt data.

## Pedagogical behavior

- AI owns progression;
- learner primarily answers;
- model adapts naturally to actual learner content;
- reference dialogue remains reference-only;
- selective correction works;
- learner repeats corrected form;
- model returns to role immediately;
- semantic VAD is patient enough for learner hesitation.

---

# 51. Short Codex implementation target

If a single paragraph is needed to keep the implementation oriented:

> Add an ephemeral, lesson-bound Speaking Practice launched from the existing lesson Menu. Present a dedicated full-screen SwiftUI speaking surface with no transcript or reference script. Use the exact-pinned `stasel/WebRTC` 151.0.0 package behind a `RealtimeSpeakingClient`. Before startup, throw unless the exact current generated lesson is confirmed server-side. The iOS client creates an SDP offer and sends it through a new authenticated FastAPI endpoint. The backend loads the full canonical `LessonPayload`, projects and validates only the current 20-line Anna/Erik reference dialogue, composes `Materials/Speaking_prompt.md`, and creates a backend-owned `gpt-realtime-2.1` session through OpenAI's unified `/v1/realtime/calls` interface. V1 is strictly guided/passive: the model chooses the active counterpart, always owns progression, and lets compatible lesson objectives emerge through learner responses. It counts exactly 10 substantive learner replies, excludes requested correction repetitions, then closes without another response opportunity. Configure semantic VAD with low eagerness, `max_output_tokens=256`, direct WebRTC audio, one active session per user, bounded start rate, a 25-second data-channel establishment timeout, and a hard 10-minute safety timeout. Retain the provider `call_id` in the lease and invoke Realtime hangup on explicit DELETE, server expiry, and graceful shutdown while also closing client WebRTC. Keep roleplay/correction/repetition logic in the Realtime prompt rather than a pedagogical app state machine. Do not persist speaking turns, alter `LessonPhase`, invoke the evaluator, show transcripts, or add a new database model.

---

# 52. References

## Repository

- `AGENTS.md`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/AGENTS.md

- `docs/RUNBOOK.md`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/docs/RUNBOOK.md

- `docs/BILLING.md`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/docs/BILLING.md

- `SWE_Dialogs/SWE_Dialogs/LessonModels.swift`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/SWE_Dialogs/SWE_Dialogs/LessonModels.swift

- `SWE_Dialogs/SWE_Dialogs/LessonView.swift`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/SWE_Dialogs/SWE_Dialogs/LessonView.swift

- `SWE_Dialogs/SWE_Dialogs/LessonSessionStore.swift`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/SWE_Dialogs/SWE_Dialogs/LessonSessionStore.swift

- `SWE_Dialogs/SWE_Dialogs/BackendClient.swift`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/SWE_Dialogs/SWE_Dialogs/BackendClient.swift

- `backend/app/main.py`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/backend/app/main.py

- `backend/app/config.py`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/backend/app/config.py

- `backend/app/learning_catalog.py`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/backend/app/learning_catalog.py

- `backend/app/openai_client.py`  
  https://github.com/OneSixFive/SWE_Dialogs/blob/main/backend/app/openai_client.py

## OpenAI

- GPT-Realtime-2.1 model  
  https://developers.openai.com/api/docs/models/gpt-realtime-2.1

- Realtime API with WebRTC  
  https://developers.openai.com/api/docs/guides/realtime-webrtc

- Realtime API reference / session configuration / VAD  
  https://platform.openai.com/docs/api-reference/realtime

---

## Final implementation stance

The most important architectural restraint is that V1 should **not become a second learning engine**.

It should be:

```text
existing lesson
    +
backend-built lesson-specific Realtime prompt
    +
one direct WebRTC speaking session
```

Everything pedagogically sophisticated about V1 — purposeful lesson grounding, natural adaptation, AI-owned progression, selective corrections, repetition, and returning to role — should first be solved in the Realtime prompt and tested on-device.

Only add more state, persistence, or orchestration if real V1 testing demonstrates that prompt + Realtime conversation state cannot reliably deliver the desired interaction.
