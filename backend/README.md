# Svenska Backend

Small FastAPI backend for the trusted-friend TestFlight build.

## Runtime

- Bind locally: `127.0.0.1:8100`
- Public v0 route: `https://svenska-api.dima-ib.xyz:8443`
- Secrets: `/home/dima/secure-secrets/llm.env`

Required secrets:

```sh
OPENAI_API_KEY=...
GEMINI_API_KEY=...
APP_JWT_SECRET=...
APPLE_CLIENT_ID=dima.SWE-Dialogs
```

Optional vocabulary-practice overrides:

```sh
OPENAI_EVALUATOR_MODEL=gpt-5.6-sol
OPENAI_EVALUATOR_REASONING_EFFORT=medium
OPENAI_VOCABULARY_QUIZ_MODEL=gpt-5.6-terra
OPENAI_VOCABULARY_QUIZ_REASONING_EFFORT=medium
OPENAI_VOCABULARY_INTERACTOR_MODEL=gpt-5.6-terra
OPENAI_VOCABULARY_INTERACTOR_REASONING_EFFORT=low
SVENSKA_EVALUATION_WORKER_ENABLED=1
SVENSKA_LESSON_AUDIO_WORKER_ENABLED=1
SVENSKA_LESSON_AUDIO_WORKER_INTERVAL_SECONDS=1
SVENSKA_LESSON_AUDIO_MAX_ATTEMPTS=4
SVENSKA_LESSON_AUDIO_LEASE_SECONDS=360
SVENSKA_LESSON_AUDIO_MAX_QUEUED_PER_USER=5
SVENSKA_LESSON_AUDIO_RETRY_COOLDOWN_SECONDS=10
```

## Local Run

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

## Endpoints

- `GET /health`
- `POST /auth/apple`
- `POST /lessons/generate`
- `POST /lessons/message`
- `GET|PUT /me/lesson-sessions[...]`
- `POST /me/lesson-sessions/{id}/audio/generate`
- `GET /me/lesson-sessions/{id}/audio/status`
- `GET /me/lesson-sessions/{id}/audio`
- `GET|POST /me/vocabulary-practices`
- `GET /me/vocabulary-practices/{id}`
- `POST /me/vocabulary-practices/{id}/messages`
- `POST /me/vocabulary-practices/{id}/next`
- `POST /me/vocabulary-practices/{id}/abandon`
- `POST /tts/dialogue`

`PUT /me/lesson-sessions/{id}/audio` and lesson use of `/tts/dialogue` are compatibility paths for older app builds. New lesson clients use durable audio jobs. `/tts/dialogue` remains the synchronous custom-TTS endpoint.

Protected endpoints require:

```text
Authorization: Bearer <session-token>
```
