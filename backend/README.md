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
- `POST /tts/dialogue`

Protected endpoints require:

```text
Authorization: Bearer <session-token>
```
