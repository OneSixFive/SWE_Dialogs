# OpenAI Chat Setup (iOS + backend)

## 1) Paste your OpenAI API key

Create a local env file from the example:

```bash
cd backend
cp .env.example .env
```

Open `backend/.env` and paste your key here:

```env
OPENAI_API_KEY=PASTE_REAL_KEY_HERE
```

You can keep the rest as-is:

```env
OPENAI_CHAT_MODEL=gpt-5.4-nano
PORT=3001
```

`backend/.env` is ignored by git, so your key is not committed.

## 2) Install and run backend

```bash
cd backend
npm install
npm run dev
```

Health check:

```bash
curl http://localhost:3001/health
```

Expected: JSON with `ok: true` and current `model`.

## 3) Call from iOS app (no OpenAI key in app)

- Start a chat:

```bash
curl -X POST http://localhost:3001/chat/new
```

- Send message:

```bash
curl -X POST http://localhost:3001/chat/<conversationId>/message \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hej!"}'
```

In iOS, call these backend endpoints only. Never embed `OPENAI_API_KEY` in the app bundle.

## 4) Swap model later

Edit one line in `backend/.env`:

```env
OPENAI_CHAT_MODEL=gpt-5.4-mini
```

Restart backend.
