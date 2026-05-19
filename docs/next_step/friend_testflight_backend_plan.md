# Friend TestFlight Backend Implementation Plan

## Goal

Make the Swedish lesson app safe and simple to install on a trusted friend's phone through TestFlight.

The friend should be able to install the app, sign in with Apple, and use lessons without entering OpenAI or Gemini API keys. Provider keys must stay on the VM backend only.

## Current State

- The iOS app still stores provider keys in local settings via `@AppStorage`.
- Lesson generation uses OpenAI directly from the app.
- Lesson and custom dialogue audio use Gemini TTS directly from the app.
- The VM repo is available at `/home/dima/Svenska_new`.
- The VM remote is `git@github.com:OneSixFive/SWE_Dialogs.git`.
- The VM has `/home/dima/secure-secrets`.
- SSH as `dima` to the VM works through the configured GCE host.
- `iPhone_D` is paired and available for real-device validation.
- The Xcode project currently has `IPHONEOS_DEPLOYMENT_TARGET = 26.2`; confirm the friend's iOS version before release.

## Architecture Direction

Use the VM as the only holder of provider secrets.

The app should:

1. Start with Sign in with Apple.
2. Exchange the Apple `id_token` with the backend.
3. Store only the backend session token in iOS Keychain.
4. Send lesson generation, lesson chat, and TTS requests to the backend.
5. Never store or transmit OpenAI/Gemini keys from the device.

The backend should:

1. Verify Apple identity tokens server side.
2. Create or find a user by Apple `sub`.
3. Issue short-lived app session tokens.
4. Expose typed product endpoints rather than a generic LLM proxy.
5. Load provider secrets only from `/home/dima/secure-secrets/llm.env`.

## Backend Endpoints

Prefer product-level endpoints:

- `POST /auth/apple`
  - Input: Apple `id_token`, optional nonce value if used by the client.
  - Output: backend session token and user summary.

- `POST /lessons/generate`
  - Protected.
  - Input: one lesson payload.
  - Backend calls OpenAI Responses API.
  - Output: generated lesson JSON matching the app's `GeneratedLesson` shape.

- `POST /lessons/message`
  - Protected.
  - Input: course context, lesson payload, generated lesson, full lesson chat history, lesson state, latest user message.
  - Backend calls OpenAI Responses API.
  - Output: interactor response JSON matching the app's `InteractorResponse` shape.

- `POST /tts/dialogue`
  - Protected.
  - Input: dialogue text and selected voice/model option.
  - Backend calls Gemini TTS.
  - Output: WAV bytes or a short-lived download response.

- `GET /health`
  - Unauthenticated.
  - Output: service health only, no secret or provider state.

Avoid a generic `/llm/*` pass-through for the app. It would turn the backend session token into broad provider access instead of limiting users to app-supported actions.

## Backend Security Requirements

- Verify Apple `id_token` with Apple's JWKS.
- Check `iss`, `aud`, `exp`, token signature, and Apple `sub`.
- Use nonce verification if the iOS sign-in flow sends a nonce.
- Store users by Apple `sub`; do not rely on mutable email.
- Issue short-lived backend JWTs.
- Use a server-side JWT secret from the secure secrets directory.
- Return app-friendly error codes without exposing upstream secrets or raw provider error bodies.

For v0 trusted-friend beta, keep this minimal: authentication, secret isolation, and typed backend endpoints are required. More detailed abuse controls and operational hardening are intentionally pushed to a later pass.

## VM Deployment Plan

1. Add backend service code under the repo on the VM.
2. Keep `.env` files and secret material out of git.
3. Read secrets from `/home/dima/secure-secrets/llm.env`.
4. Add a sample env file with placeholder names only.
5. Add a `systemd` unit for the API service.
6. Run the API under a constrained runtime user if practical.
7. Put the API behind HTTPS with a valid certificate.
8. Add basic service operations docs:
   - start
   - stop
   - restart
   - logs
   - health check
9. Validate that the backend can reach OpenAI and Gemini from the VM.

## iOS Implementation Plan

1. Add Sign in with Apple capability and entitlements.
2. Add an auth/session layer:
   - Apple sign-in coordinator.
   - Backend token exchange client.
   - Keychain storage for backend session token.
   - Sign-out path that clears Keychain session state.
3. Remove provider key entry from Settings.
4. Replace direct OpenAI calls in `OpenAITutorService` with backend lesson endpoints.
5. Replace direct Gemini TTS calls in `GeminiTTSService` with backend TTS endpoint.
6. Keep local lesson/session/audio persistence behavior unchanged unless the backend contract requires a minimal adjustment.
7. Add clear unauthenticated states:
   - show Sign in with Apple before protected lesson actions.
   - preserve existing local content where reasonable.
8. Confirm whether the older `More` custom TTS flow should remain available through the backend or be hidden for this trusted beta.

## TestFlight Readiness Checklist

- No OpenAI or Gemini key fields remain in the app UI.
- No provider key names are present in app-side persistent storage paths.
- Backend session token is stored in Keychain only.
- Apple sign-in works on `iPhone_D`.
- Lesson generation works on `iPhone_D`.
- Lesson chat works on `iPhone_D`.
- Lesson audio generation and playback work on `iPhone_D`.
- Background audio still works.
- App handles expired backend sessions by asking the user to sign in again.
- App handles backend/provider failures without losing local lesson state.
- Deployment target is compatible with the friend's phone.
- TestFlight build uploads successfully.
- Friend can install, sign in, generate a lesson, play audio, and send at least one lesson chat message.

## Post-v0 Hardening

Do not block the first trusted-friend beta on these, but keep them on the near-term roadmap before broader distribution:

- Add request size limits for lesson payloads, chat history, and TTS input.
- Add per-user quotas and rate limits.
- Add redacted structured logs for request metadata, status, latency, and provider cost signals where available.
- Ensure logs never contain prompts, provider keys, Apple tokens, backend JWTs, or audio payloads.
- Define clear timeout behavior for OpenAI and Gemini calls, including user-facing retry/error states.
- Add alerts or simple monitoring for repeated provider failures and abnormal usage.

## Validation Commands

Local app build:

```sh
cd SWE_Dialogs
xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' build
```

Local app tests:

```sh
cd SWE_Dialogs
xcodebuild -scheme SWE_Dialogs -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' test
```

VM repo check:

```sh
ssh dima@dima.us-east1-c.ib-trading-481420 'cd /home/dima/Svenska_new && git status --short --branch'
```

## Open Decisions

- Backend language/framework.
- Public API domain name.
- Exact Apple bundle ID and Services ID configuration.
- Whether to support the old custom TTS flow in the first friend beta.
- Friend's iOS version and minimum supported deployment target.
- Whether generated TTS audio should be returned inline or through temporary file URLs.

## Recommended Implementation Order

1. Backend skeleton, health route, env loading, and deployment scaffold.
2. Apple auth verification and backend session token issuance.
3. Protected lesson generation endpoint.
4. Protected lesson message endpoint.
5. Protected TTS endpoint.
6. iOS Sign in with Apple and Keychain session storage.
7. iOS migration from direct provider calls to backend calls.
8. On-device validation on `iPhone_D`.
9. TestFlight upload and friend-device validation.
10. Post-v0 hardening: quotas, request limits, redacted logs, timeout behavior, and monitoring.
