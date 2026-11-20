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
- Codex was used to assist implementation and verification.

## Bonus features (if any)

- Optional per-session system prompt field
- Inline request metadata cards in the UI
- Deterministic failure simulation that does not consume real key quota
- Focused automated tests for the critical resilience behavior
- Responsive workspace with light/dark themes and a message composer that stays visible
- Searchable history shortcuts (up to 30 conversations in this browser), backed by SQLite history retrieval
- Markdown replies with tables and code blocks; raw HTML and remote images are not rendered
- Copy replies and export the current conversation as a Markdown download
- Prompt starter cards, assistant-instruction presets, and editable retry drafts
- Actual backend readiness indicator (polled every 30 seconds; it does not claim provider availability)
- One-request failure simulation with a visible warning that resets after sending

### Frontend feature checks

`cd frontend` then `npm run test:e2e` runs browser tests against mocked API responses, without using your real keys or credits. Local tests use installed Chrome; CI installs Chromium. The tests cover Markdown and required metadata, copy/export, saved conversation retrieval, theme persistence, one-request simulation, retry drafts, and the mobile composer/navigation. Run `npm run build` for the TypeScript and production bundle checks.

Every page load still starts a new session. Explicitly selecting a sidebar conversation resumes its stored session. The browser stores session IDs and titles, while full message history remains in SQLite. Old sessions created before these shortcuts were added are not automatically listed. There is no authentication in this assignment: use your own device for chat history and do not expose a production deployment with sensitive conversations.

## Learning walkthrough: follow one message

Read the project in this order and trace the example “My name is Dishant”.

1. `frontend/src/App.tsx`: React state holds the text you type and the messages on screen. The submit handler clears the input, disables duplicate sends, and calls `sendChat`. State updates cause React to render the new conversation.
2. `frontend/src/api.ts`: `fetch` turns your message into a JSON HTTP request. Only the new message and session ID travel to the backend. Keys stay on the backend because anything bundled into browser JavaScript can be read by visitors.
3. `backend/app/schemas.py`: Pydantic checks the JSON before the endpoint runs. A blank message receives 422. Validating at the server matters even when the browser already checks input, because other clients can call the API directly.
4. `backend/app/main.py`: the endpoint reads prior history and places a system instruction before it. On “What is my name?” the model receives the earlier user message and assistant answer too. An LLM call has no memory unless we supply it.
5. `backend/app/llm.py`: LiteLLM translates the common message format into the provider's API. Its Router owns ordered fallback: each key has a named route, and a failed primary route falls back to the backups. An adapter around one attempt injects simulated errors and records metadata. A `ContextVar` keeps that state separate for simultaneous requests, so one user's simulation cannot affect another user.
6. `backend/app/database.py`: after success, a transaction saves both messages. If an insert fails, rollback prevents half a turn being stored. SQL placeholders keep user text separate from SQL commands. The session index lets SQLite find a chat's messages efficiently.
7. The JSON response returns to React, which shows the answer and that request's metadata. Input tokens include system + history + new text; output tokens describe only the new answer. Longer conversations therefore increase input tokens even though the UI sends just one new message.

Each session has an asynchronous lock around reading history, calling the model, and saving the turn. Without it, two overlapping requests could both answer using the same old history. This protection assumes one backend worker: run one Uvicorn worker with this SQLite/local-cache deployment.

### Run on your Windows machine without Docker

From the repository root, copy `.env.example` to `.env` and edit your keys locally. Set `DATABASE_URL=sqlite:///./data/app.db` in `.env` for local use; `/data/app.db` is the Linux container path.

```powershell
Copy-Item .env.example .env
uv sync --project backend --frozen --all-groups
uv run --project backend uvicorn app.main:app --app-dir backend --env-file .env --reload --port 8000
```

Open a second terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Visit `http://localhost:3000`. `npm.cmd` avoids PowerShell's restriction on npm's `.ps1` wrapper. `/docs` on port 8000 provides an interactive API explorer, including the failure header.

### Deployment preparation

The backend host must run the backend Dockerfile, expose port 8000, and provide a persistent disk mounted at `/data`. Set the variables from `.env.example` in the host's secrets/settings UI. Set `ALLOWED_ORIGINS` to the exact public frontend origin (scheme + hostname, no path). Keep one worker and one backend instance for consistent local caching and session locking.

Build the frontend from its Dockerfile or publish `frontend/dist`. Supply `VITE_API_BASE_URL` with the backend's public HTTPS URL at build time. A value starting with `VITE_` is public; never use that prefix for a secret key. Once URLs exist, enter them in the Live URLs section and run the verification sequence above against those public URLs.

GitHub Actions now runs backend tests, a frontend production build, and both Docker builds on pushes and pull requests. A green build checks packaging; it does not prove that real provider credentials or a cloud disk are configured correctly. Compose uses `.env` by default; `ENV_FILE` can select another backend environment file.

### Two-to-three minute demo script

1. Show the public app and `/health` (20 seconds).
2. Send your name, then ask the bot to recall it; point out per-reply metadata (35 seconds).
3. Reload the page and repeat an identical opening question. Show `LLM_CACHE`, preserved token counts, and latency (30 seconds).
4. In `/docs`, send a request with `key_1=429`, then one with `*=429`; explain the winning key and clean 503 (40 seconds).
5. Show the history endpoint and explain why failed turns are absent (20 seconds).

Record your own narration explaining these choices. Remaining submission steps are live credential verification, public deployment, and your demo recording.

### Native fallback and the demo controls

The key pool configures LiteLLM Router with one route per key (`key_1`, `key_2`, ...), zero retries on the same key, and an ordered fallback list. Router invokes a small attempt adapter that calls the LiteLLM gateway. Retryable failures move to the next route; request errors such as HTTP 400 do not send more provider requests. The Router attempt hook is version-specific, so the LiteLLM version is pinned and tested.

The UI's expandable **Test failover** control sends the required header. It shows which key answered and how many keys failed beside every response. Choose “Normal request” before checking cache behavior. The dropdown does not create mock answers: successful failover needs a valid provider key. Local Docker persistence and HTTP checks have passed; real-provider verification still requires your `.env` keys.

The default model is `gemini/gemini-3.1-flash-lite`. Live inference with key_1, an identical cross-session cache hit, and simulated primary failure followed by a real key_2 response have been verified locally. Provider timeouts (408) are retryable, alongside 429 and 5xx errors. Credentials remain solely in the ignored local `.env` file or deployment secrets.
