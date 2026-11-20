# Lyftr LLM Chatbot

An end-to-end React + FastAPI chat application built for the Lyftr full-stack assignment. It persists conversations in SQLite, uses a pool of provider keys, falls over from failed keys, and labels responses served by LiteLLM's exact-match cache.

## Live URLs

Frontend: **not deployed yet**

Backend: **not deployed yet**

Before submitting, replace those two placeholders with public URLs that do not require a login.

## Run locally

### With Docker

1. Copy `.env.example` to `.env`.
2. Put at least two valid keys in `LLM_API_KEYS`, separated by commas.
3. Choose a LiteLLM-supported chat model in `LLM_MODEL` that accepts those keys.
4. Run `make up`.
5. Open `http://localhost:3000`; the API is available at `http://localhost:8000`.

`make down` stops the stack. The named `chat_data` volume preserves `/data/app.db`, so conversation history survives backend container recreation.

### Without Docker

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, and npm.

```bash
# terminal 1 — backend
cp .env.example .env
# export/load the values in .env in your shell, then:
uv sync --project backend --all-groups
uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8000

# terminal 2 — frontend
cd frontend
npm install
npm run dev
```

For a production frontend build, set `VITE_API_BASE_URL` to the public backend URL *before* running `npm run build`. Vite replaces this environment value at build time.

### Tests

```bash
uv run --project backend pytest backend/tests -q
```

The test gateway never sends traffic to a real model provider. It proves the API contract, SQLite history, cross-session cache semantics, and simulated failover without consuming API credits.

## Design decisions

### Request lifecycle

```text
Browser sends new message + session_id
             |
             v
FastAPI validates input
             |
             +--> SQLite reads prior user/assistant history
             |
             v
Build [system prompt, history, new message]
             |
             v
KeyPool tries key_1 -> key_2 -> ... through LiteLLM
             |
      +------+------+
      |             |
 cache hit      live provider reply
      |             |
      +------> save successful user + assistant turn atomically
                         |
                         v
                     JSON response
```

This separation is intentional:

- `database.py` owns only persistence. It uses a short SQLite connection per action and stores a session's optional system prompt in a separate `sessions` table. The public history endpoint therefore never leaks the system prompt.
- `llm.py` gives each secret a non-secret public identifier (`key_1`, `key_2`, …). It catches only retryable statuses—429 and 5xx, plus quota errors—and records how many keys failed before a response succeeded.
- LiteLLM makes the actual `acompletion` call and owns the built-in exact-match cache. The cache sees the model plus the full message list, so the same opening message in a different session can hit the cache, but changing history or the system prompt cannot.
- The API saves a turn only after an LLM reply succeeds. A 422 or 503 therefore leaves no partial history behind.

### Key fallback

`LLM_API_KEYS` is a comma-separated ordered pool. The first secret is exposed only as `key_1`, the next as `key_2`, and so on. A real provider 429, quota error, or 5xx moves to the next key. If all keys fail, `/chat` returns:

```json
{ "detail": "all providers unavailable" }
```

`X-Simulate-Failure` is deterministic and safe for the demo:

```http
X-Simulate-Failure: key_1=429
X-Simulate-Failure: key_1=429,key_2=500
X-Simulate-Failure: *=429
```

It is active only when `ENABLE_FAILURE_SIMULATION=true`. Simulated requests bypass the cache so they always exercise the fallback path instead of returning a previously cached response.

### Caching

LiteLLM's local exact-match cache is enabled during application startup. On a cache hit the API returns `LLM_CACHE`, preserves the token values from the cached provider response, and sets `key_id` to `null` because no provider key was used. Local caching is appropriate for this single-container assignment. For multiple backend replicas, switch to LiteLLM's Redis cache so cache state is shared.

### SQLite session storage

`messages` follows the required core model: `id`, `session_id`, `role`, `content`, `metadata`, and `created_at`. The project adds a small `sessions` table solely to preserve the optional system prompt per session. Metadata is JSON so the exact values displayed in the UI are preserved with each assistant reply.

## Verification

Run these checks during your demo.

1. **Health:** `GET /health` returns `status: ok`, two or more keys, and `cache_enabled: true`.
2. **Multi-turn context:** ask “My name is Ana”, then “What is my name?” in the same browser page. The backend sends the earlier turn to the model.
3. **Cache:** send the same first message from a freshly reloaded page. The second response should display `LLM_CACHE`, have `key_id: null`, and usually have lower latency.
4. **Single-key fallback:** call `/chat` with `X-Simulate-Failure: key_1=429`. It should return 200 with `key_id: "key_2"` and `fallback_attempts: 1`.
5. **All keys unavailable:** send `X-Simulate-Failure: *=429`. It should return a JSON 503 and must not add a message to that session.
6. **History:** call `GET /sessions/{session_id}/messages`. It returns user and assistant messages oldest first, with assistant metadata but no system prompt.

Example request:

```bash
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-1","message":"Explain HTTP 429 in one sentence."}'
```

## Setup Used

- React, TypeScript, and Vite for the client
- Python, FastAPI, and Uvicorn for the API
- SQLite from Python's standard library for durable local storage
- LiteLLM for provider-agnostic asynchronous model calls and response caching
- Docker Compose, multi-stage images, and an Nginx static frontend runtime
- pytest plus a fake LiteLLM gateway for deterministic backend tests

## Bonus features (if any)

- Optional per-session system prompt field
- Inline request metadata cards in the UI
- Deterministic failure simulation that does not consume real key quota
- Focused automated tests for the critical resilience behavior
