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
OPENAI_EVALUATOR_MODEL=gpt-5.5
OPENAI_EVALUATOR_REASONING_EFFORT=medium
OPENAI_VOCABULARY_QUIZ_MODEL=gpt-5.5
OPENAI_VOCABULARY_QUIZ_REASONING_EFFORT=medium
OPENAI_VOCABULARY_INTERACTOR_MODEL=gpt-5.5
OPENAI_VOCABULARY_INTERACTOR_REASONING_EFFORT=low
SVENSKA_EVALUATION_WORKER_ENABLED=1
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
- `GET|POST /me/vocabulary-practices`
- `GET /me/vocabulary-practices/{id}`
- `POST /me/vocabulary-practices/{id}/messages`
- `POST /me/vocabulary-practices/{id}/next`
- `POST /me/vocabulary-practices/{id}/abandon`
- `POST /tts/dialogue`

Protected endpoints require:

```text
Authorization: Bearer <session-token>
```
