# Friend TestFlight Backend Implementation Plan

## Goal

Make the Swedish lesson app safe and simple to install on a trusted friend's phone through TestFlight.

The friend should be able to install the app, sign in with Apple, and use lessons without entering OpenAI or Gemini API keys. Provider keys must stay on the VM backend only.

## Chosen v0 Shape

Use the existing VM, but keep IB_Trading and Svenska separated by DNS name, port, listener binding, firewall rules, and Caddy routes.

- Public hostname: `svenska-api.dima-ib.xyz`.
- iOS backend base URL for v0: `https://svenska-api.dima-ib.xyz:8443`.
- Svenska backend bind target: `127.0.0.1:8100`.
- Public Caddy entrypoint: `10.142.0.2:8443`, proxying only to `127.0.0.1:8100`.
- Public certificate: normal trusted ACME certificate, not `tls internal`.
- Existing IB_Trading routes remain VPN-only on `10.0.0.1`.
- Existing Xray remains on public `10.142.0.2:443`.
- Existing AmneziaWG remains on public UDP `443`.
- Existing IB Gateway public exposure must remain blocked, especially `5000/tcp`.

The `svenska-api` DNS A-record has been created. A VM machine image has also been created as a rollback point before network changes.

## Current State

- The iOS app still stores provider keys in local settings via `@AppStorage`.
- Lesson generation uses OpenAI directly from the app.
- Lesson and custom dialogue audio use Gemini TTS directly from the app.
- Sign in with Apple capability has been added to the iOS app.
- The VM repo is available at `/home/dima/Svenska_new`.
- The VM remote is `git@github.com:OneSixFive/SWE_Dialogs.git`.
- The VM has `/home/dima/secure-secrets`.
- `/home/dima/secure-secrets/llm.env` currently has:
  - `OPENAI_API_KEY`
  - `GEMINI_API_KEY`
- SSH as `dima` to the VM works through the configured GCE host.
- `iPhone_D` is paired and available for real-device validation.
- The Xcode project currently has `IPHONEOS_DEPLOYMENT_TARGET = 26.2`.
- Friend's phone is on iOS `26.2`, so the current deployment target is acceptable for v0.

## VM Network Settings Guardrails

The VM network setup is documented and backed up under:

```text
/Users/dima/Downloads/computing/VM_management
```

Before changing Caddy, UFW, GCP firewall rules, systemd services, or listener bindings, read the relevant VM management docs and current backups there, especially:

- `VM_NETWORK_ACCESS_RUNBOOK.md`
- `VM_SETUP_BASELINE.md`
- `VM_OPERATIONS_MAINTENANCE.md`
- `Network/BACKUP_TO_RUNBOOK_MAP_2026-05-19.md`
- latest `Network/vm-config-backup-*` snapshot

The Svenska implementation must preserve the existing IB_Trading network model:

- VPN client DNS is served by `dnsmasq-wg0` on `10.0.0.1:53`.
- `api.dima-ib.xyz`, `ib2.dima-ib.xyz`, and `chart.dima-ib.xyz` remain split-DNS/VPN-only names resolving to `10.0.0.1` for VPN clients.
- Caddy's IB_Trading routes remain bound to `10.0.0.1`, not the public interface.
- IB_Trading Caddy routes continue to use `tls internal`.
- IB Gateway login remains reachable only through the intended VPN/internal path.
- IB Gateway `5000/tcp` remains blocked from the public external interface.
- Public TCP `443` remains owned by Xray on `10.142.0.2:443`.
- Public UDP `443` remains owned by AmneziaWG.
- AmneziaWG/WireGuard routing and NAT rules remain unchanged.
- No existing IB_Trading service, DNS route, tunnel, or firewall rule should be loosened to support Svenska.

For Svenska, add only the narrow new public surface:

- public DNS name: `svenska-api.dima-ib.xyz`
- public port: `8443/tcp`
- Caddy bind: `10.142.0.2:8443`
- backend bind: `127.0.0.1:8100`
- optional public `80/tcp` only for ACME HTTP-01 challenge/redirect

If any implementation step appears to require changing public `443`, exposing `5000`, removing `bind 10.0.0.1`, changing split DNS, or altering Xray/AmneziaWG behavior, stop and reassess the plan before proceeding.

## Non-Negotiable IB_Trading Isolation Rules

Do not weaken the existing IB_Trading access model while adding Svenska.

- Do not expose IB Gateway `5000/tcp` publicly.
- Do not proxy any public Svenska route to `127.0.0.1:5000` or `0.0.0.0:5000`.
- Do not change `ib2.dima-ib.xyz`, `api.dima-ib.xyz`, or `chart.dima-ib.xyz` from VPN-only split DNS.
- Do not remove `bind 10.0.0.1` or `tls internal` from existing IB_Trading Caddy routes.
- Do not disturb Xray on public TCP `443`.
- Do not disturb AmneziaWG on public UDP `443`.
- Do not use public TCP `443` for Svenska in v0.

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
3. Issue app session JWTs.
4. Expose typed product endpoints rather than a generic LLM proxy.
5. Load provider secrets only from `/home/dima/secure-secrets/llm.env`.

## Backend Stack

Use Python + FastAPI + Uvicorn for v0.

Rationale:

- The VM already runs Python/FastAPI-style backend services.
- Uvicorn can bind cleanly to `127.0.0.1:8100`.
- FastAPI gives typed request/response models and simple OpenAPI docs for local debugging.
- The service can be run under `systemd` with the existing VM operational model.

Suggested repo layout:

```text
backend/
  app/
    main.py
    auth.py
    config.py
    db.py
    models.py
    openai_client.py
    gemini_client.py
  requirements.txt
  README.md
```

Use SQLite for minimal v0 user persistence:

- `backend/data/svenska.db`
- `users` table keyed by Apple `sub`
- optional `sessions` or audit table only if useful during implementation

## Backend Endpoints

Use product-level endpoints:

- `GET /health`
  - Unauthenticated.
  - Output: service health only, no secret or provider state.

- `POST /auth/apple`
  - Input: Apple `id_token` and nonce value if used by the client.
  - Backend verifies Apple token signature and claims.
  - Backend creates or finds user by Apple `sub`.
  - Output: backend session token and user summary.

- `POST /lessons/generate`
  - Protected.
  - Input: one lesson payload plus any model options the app currently controls.
  - Backend calls OpenAI Responses API.
  - Output: generated lesson JSON matching the app's `GeneratedLesson` shape.

- `POST /lessons/message`
  - Protected.
  - Input: course context, lesson payload, generated lesson, full lesson chat history, lesson state, latest user message.
  - Backend calls OpenAI Responses API.
  - Output: interactor response JSON matching the app's `InteractorResponse` shape.

- `POST /tts/dialogue`
  - Protected.
  - Input: dialogue text and selected Gemini TTS model/voice option.
  - Backend calls Gemini TTS.
  - Output: WAV bytes for the app to store using its existing local audio persistence.
  - This endpoint is used by both lesson audio and the older `More` custom TTS flow.

Avoid a generic `/llm/*` pass-through for the app. It would turn the backend session token into broad provider access instead of limiting users to app-supported actions.

## Backend Configuration

Add these values to `/home/dima/secure-secrets/llm.env` before starting the service:

```sh
OPENAI_API_KEY=...
GEMINI_API_KEY=...
APP_JWT_SECRET=...
APPLE_CLIENT_ID=dima.SWE-Dialogs
```

Notes:

- `APPLE_CLIENT_ID` should match the iOS app bundle identifier/audience expected in Apple `id_token`.
- Generate `APP_JWT_SECRET` as a strong random value.
- Keep `.env` files and real secrets out of git.
- Add only placeholder/sample env documentation to the repo.

## Backend Security Requirements for v0

- Verify Apple `id_token` with Apple's JWKS.
- Check `iss`, `aud`, `exp`, token signature, and Apple `sub`.
- Use nonce verification if the iOS sign-in flow sends a nonce.
- Store users by Apple `sub`; do not rely on mutable email.
- Issue short-lived backend JWTs.
- Require `Authorization: Bearer <session-token>` on protected endpoints.
- Return app-friendly error codes without exposing upstream secrets or raw provider error bodies.

For v0 trusted-friend beta, keep this minimal: authentication, secret isolation, typed backend endpoints, and IB isolation are required. More detailed abuse controls and operational hardening are intentionally pushed to a later pass.

## VM Deployment Plan

1. Preflight the VM before network changes:
   - capture `sudo ss -lntup`
   - capture `sudo ufw status verbose`
   - capture `/etc/caddy/Caddyfile`
   - confirm Xray is active on `10.142.0.2:443`
   - confirm Caddy is active on `10.0.0.1:80/443`
   - confirm IB Gateway public `5000/tcp` is blocked
2. Add backend service code under `/home/dima/Svenska_new/backend`.
3. Create a backend virtualenv and install FastAPI/Uvicorn dependencies.
4. Add a `systemd` unit for the Svenska API service.
5. Run the API as `dima` for v0 so `/home/dima/secure-secrets/llm.env` can remain private to `dima`.
6. Bind Uvicorn to `127.0.0.1:8100` only.
7. Add a public Caddy route for `svenska-api.dima-ib.xyz:8443` that proxies only to `127.0.0.1:8100`.
8. Use a normal public ACME certificate for Svenska, not `tls internal`.
9. Open only the required public ports for Svenska:
   - GCP firewall: `tcp:8443` to the VM, preferably through a dedicated `svenska-api` network tag.
   - UFW: `8443/tcp` on `ens4`.
   - GCP/UFW `80/tcp` on `ens4` for ACME HTTP-01 certificate challenge/redirect only.
10. Do not open `5000/tcp`.
11. Restart/reload only the services required for Svenska.
12. Validate that the backend can reach OpenAI and Gemini from the VM.

## Caddy v0 Shape

Keep existing IB_Trading Caddy server blocks unchanged.

Add a separate public Svenska block shaped like:

```caddyfile
https://svenska-api.dima-ib.xyz:8443 {
    bind 10.142.0.2
    encode zstd gzip
    reverse_proxy 127.0.0.1:8100
}
```

Certificate note:

- A trusted certificate is required for TestFlight/iOS.
- Since public TCP `443` is already Xray, use ACME HTTP-01 via public TCP `80` for v0.
- DNS-01 remains a later alternative if public TCP `80` should be removed.
- Do not use Caddy `tls internal` for Svenska.
- Do not add any public route for `ib2.dima-ib.xyz`.

## iOS Implementation Plan

1. Add an app configuration point for the backend base URL:
   - v0 value: `https://svenska-api.dima-ib.xyz:8443`
2. Add an auth/session layer:
   - Apple sign-in coordinator.
   - Nonce generation and verification flow if practical.
   - Backend token exchange client.
   - Keychain storage for backend session token.
   - Sign-out path that clears Keychain session state.
3. Remove provider key entry from Settings.
4. Replace direct OpenAI calls in `OpenAITutorService` with backend lesson endpoints.
5. Replace direct Gemini TTS calls in `GeminiTTSService` with backend TTS endpoint.
6. Reroute the older `More` custom TTS flow through the backend instead of hiding it.
7. Keep local lesson/session/audio persistence behavior unchanged unless the backend contract requires a minimal adjustment.
8. Add clear unauthenticated states:
   - show Sign in with Apple before protected lesson actions.
   - preserve existing local content where reasonable.

## TestFlight Readiness Checklist

- No OpenAI or Gemini key fields remain in the app UI.
- No provider key names are present in app-side persistent storage paths.
- Backend session token is stored in Keychain only.
- Apple sign-in works on `iPhone_D`.
- Lesson generation works on `iPhone_D`.
- Lesson chat works on `iPhone_D`.
- Lesson audio generation and playback work on `iPhone_D`.
- Older `More` custom TTS flow works through the backend.
- Background audio still works.
- App handles expired backend sessions by asking the user to sign in again.
- App handles backend/provider failures without losing local lesson state.
- Deployment target is compatible with the friend's phone.
- TestFlight build uploads successfully.
- Friend can install, sign in, generate a lesson, play audio, use `More` custom TTS, and send at least one lesson chat message.

## Network Safety Validation

Run these checks before and after enabling the Svenska public route.

From outside the VPN:

```sh
curl -i --max-time 10 https://svenska-api.dima-ib.xyz:8443/health
curl -i --max-time 10 http://svenska-api.dima-ib.xyz:5000/
curl -i --max-time 10 https://ib2.dima-ib.xyz/
```

Expected:

- Svenska health returns an app health response over trusted HTTPS.
- Public `:5000` is blocked or unreachable.
- Public `ib2.dima-ib.xyz` does not expose the IBKR login page.

From the VM:

```sh
sudo ss -lntup | rg '(:80\b|:443\b|:8443\b|:5000\b|:8100\b)'
sudo ufw status verbose
curl -ksS http://127.0.0.1:8100/health
```

Expected:

- Svenska backend listens on `127.0.0.1:8100`.
- Svenska Caddy listens on `10.142.0.2:8443`.
- Xray still listens on `10.142.0.2:443`.
- IB Caddy still listens on `10.0.0.1:80/443`.
- IB Gateway `5000` is not publicly allowed.

From VPN:

```sh
curl -ksS https://api.dima-ib.xyz/health
curl -sk https://ib2.dima-ib.xyz/
```

Expected:

- Existing IB_Trading API route still works.
- Existing IBKR login route still works through VPN.

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

Backend local health check on VM:

```sh
curl -ksS http://127.0.0.1:8100/health
```

Public Svenska health check:

```sh
curl -i https://svenska-api.dima-ib.xyz:8443/health
```

## Release Confirmations

- Friend's iOS version is `26.2`; current `IPHONEOS_DEPLOYMENT_TARGET = 26.2` is acceptable for v0.
- Return generated TTS audio as inline WAV bytes for v0 to preserve current app storage behavior.

## Recommended Implementation Order

1. Preflight and save current VM network/service state.
2. Add `APP_JWT_SECRET` and `APPLE_CLIENT_ID` to `/home/dima/secure-secrets/llm.env`.
3. Scaffold FastAPI backend under `/home/dima/Svenska_new/backend`.
4. Add `GET /health` and local Uvicorn run path on `127.0.0.1:8100`.
5. Add `systemd` service for Svenska API.
6. Add Apple auth verification and backend session token issuance.
7. Add protected lesson generation endpoint.
8. Add protected lesson message endpoint.
9. Add protected TTS endpoint for both Lessons and `More`.
10. Add public Caddy route and firewall rules for `svenska-api.dima-ib.xyz:8443`.
11. Run network safety validation, especially public `5000` and public `ib2` checks.
12. Add iOS backend base URL config and Keychain session storage.
13. Add iOS Sign in with Apple token exchange.
14. Migrate lesson generation/chat/TTS calls to backend.
15. Reroute `More` custom TTS to backend.
16. Build and test locally.
17. Validate on `iPhone_D`.
18. Upload TestFlight build and validate on friend's device.
19. Post-v0 hardening: quotas, request limits, redacted logs, timeout behavior, and monitoring.

## Post-v0 Hardening

Do not block the first trusted-friend beta on these, but keep them on the near-term roadmap before broader distribution:

- Add request size limits for lesson payloads, chat history, and TTS input.
- Add per-user quotas and rate limits.
- Add redacted structured logs for request metadata, status, latency, and provider cost signals where available.
- Ensure logs never contain prompts, provider keys, Apple tokens, backend JWTs, or audio payloads.
- Define clear timeout behavior for OpenAI and Gemini calls, including user-facing retry/error states.
- Add alerts or simple monitoring for repeated provider failures and abnormal usage.
