# Lyftr LLM Chatbot

A React and FastAPI chatbot with multi-turn conversation memory, ordered API-key fallback, LiteLLM response caching, and SQLite storage.

## 1. Live URLs

- **Frontend:** [Open Lyftr Chat](https://llm-chatbot-production-9dce5b1b.up.railway.app)
- **Backend:** [API base URL](https://ample-empathy-production-7cb2ef33.up.railway.app)
- **Health:** [GET /health](https://ample-empathy-production-7cb2ef33.up.railway.app/health)
- **API explorer:** [Swagger UI](https://ample-empathy-production-7cb2ef33.up.railway.app/docs)
- **Source:** [DishantSaini55/LLM-Chatbot-](https://github.com/DishantSaini55/LLM-Chatbot-)

The backend base URL is an API, not a separate webpage; use `/health` or `/docs` to inspect it.

Both services are deployed on Railway's Free plan. Idle services may sleep, delaying the first request, and services stop if their monthly usage allowance is exhausted. See [Railway's Free plan limits](https://docs.railway.com/pricing/free-plan). Model-provider quotas are separate from hosting limits.

Public checks passed on November 21, 2026: frontend availability, backend health, CORS, input validation, real AI replies, multi-turn memory, cross-session caching, backup-key failover, and all-key failure handling. Hosted storage persistence across a backend restart remains to be verified.

## 2. Run locally: with Docker and without

### Environment configuration

On first setup, copy `.env.example` to `.env` and edit it locally. Keep an existing `.env` rather than overwriting working credentials. The file is ignored by Git.

| Variable | Purpose |
| --- | --- |
| `LLM_API_KEYS` | At least two real, comma-separated provider keys; replace the example placeholders. |
| `LLM_MODEL` | LiteLLM model name; the current default is `gemini/gemini-3.1-flash-lite`. |
| `DEFAULT_SYSTEM_PROMPT` | Default assistant instructions. |
| `ENABLE_FAILURE_SIMULATION` | Set to `true` to enable the demo failure header. |
| `LITELLM_CACHE_TYPE` | `local` for this single-instance deployment. |
| `DATABASE_URL` | `sqlite:////data/app.db` in Docker; `sqlite:///./data/app.db` when running locally from the repository root. |
| `ALLOWED_ORIGINS` | Exact frontend origins, separated by commas, such as `http://localhost:3000,http://127.0.0.1:3000`. |
| `VITE_API_BASE_URL` | Publicly visible backend URL used by the frontend at build time; never put secrets in a `VITE_` variable. |

### With Docker

Install Docker Desktop and start its engine. From the repository root:

```powershell
# First setup only; then edit .env with your real keys.
Copy-Item .env.example .env
docker compose up --build
```

Set `VITE_API_BASE_URL=http://127.0.0.1:8000` and allow `http://127.0.0.1:3000` in `ALLOWED_ORIGINS` before building. Open [the local frontend](http://127.0.0.1:3000) and [backend health](http://127.0.0.1:8000/health). `localhost` also works where configured; `127.0.0.1` avoids the IPv6 localhost issue encountered on the development machine.

`make up` is an equivalent shortcut if Make is installed. Stop with `docker compose down` or `make down`. The named `chat_data` volume preserves `/data/app.db` across container recreation. Do not use `down -v` if you want to retain conversations.

### Without Docker

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, and npm. These commands use Windows PowerShell.

Create `.env` as described above. Set `DATABASE_URL=sqlite:///./data/app.db` and allow `http://127.0.0.1:3000` in `ALLOWED_ORIGINS`.

Terminal 1, from the repository root:

```powershell
uv sync --project backend --frozen --all-groups
uv run --project backend uvicorn app.main:app --app-dir backend --env-file .env --reload --host 127.0.0.1 --port 8000
```

Terminal 2, from the repository root:

```powershell
cd frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:3000`. `npm.cmd` avoids PowerShell restrictions on npm's `.ps1` wrapper. On other shells, use `npm` and the shell's environment-variable syntax.

### Hosted configuration

| Setting | Backend | Frontend |
| --- | --- | --- |
| Repository root directory | `/backend` | `/frontend` |
| Builder | Backend Dockerfile | Frontend Dockerfile |
| Public target port | `8000` | `80` |
| Health endpoint | `/health` | `/` |
| Persistent volume | Mount at `/data` | None |
| Instances/workers | One instance, one Uvicorn worker | One instance |

Keep real `LLM_API_KEYS` in backend secrets. Set backend `ALLOWED_ORIGINS` to `https://llm-chatbot-production-9dce5b1b.up.railway.app`, without a trailing slash. Set frontend build variables `CLOUD_BUILD=true` and `VITE_API_BASE_URL=https://ample-empathy-production-7cb2ef33.up.railway.app`, with `PORT=80`. Rebuild the frontend after changing its API URL because Vite embeds that value into the bundle. The cloud build rejects missing, local, and non-HTTPS API URLs.

## 3. Design decisions: key fallback, caching, SQLite session storage

### Key fallback

`LLM_API_KEYS` defines an ordered pool. Only non-secret identifiers such as `key_1` and `key_2` appear in responses. LiteLLM Router configures a route per key, zero retries on the same key, and ordered fallback to the next key.

HTTP 408/timeouts, 429, quota errors, and 5xx errors are retryable. Non-retryable request errors do not cause more provider calls. When all retryable routes fail, `/chat` returns HTTP 503 with `{"detail":"all providers unavailable"}`. Failed requests are not saved as conversation turns.

A small Router attempt adapter records the winning key and failure count and injects demo failures. Request state uses a `ContextVar` so simultaneous requests cannot share simulation state. The Router hook is version-specific, so `litellm==1.80.0` is pinned and tested.

### Caching

LiteLLM owns the exact-match response cache. The model and complete message list, including system instructions and prior turns, determine a match. Session ID is not part of that conversation content, allowing identical opening requests in separate sessions to share a cached response.

Cache hits return `resolution_source: "LLM_CACHE"`, `key_id: null`, and zero fallback attempts. Input/output token values are preserved from the original response; they do not represent a new provider call. Changing instructions or history changes the cache input. Simulated-failure requests bypass the cache.

The local cache is in memory and resets on restart. It suits one backend instance; multiple replicas would need shared caching such as Redis.

### SQLite session storage

The `messages` table stores `id`, `session_id`, `role`, `content`, JSON `metadata`, and `created_at`. A separate `sessions` table retains system instructions and timestamps. The history endpoint returns messages oldest first without exposing the system prompt.

Successful user and assistant messages are saved in one transaction. Rollback prevents partial turns. Parameterized SQL keeps message text separate from SQL commands, and a session index supports history retrieval. A per-session asynchronous lock serializes the read/call/save sequence. This design assumes one worker and one backend instance.

Docker stores the database on a named volume; the hosted backend needs a persistent `/data` volume. An ephemeral container filesystem alone does not provide durable history.

### Follow one message through the code

1. `frontend/src/App.tsx` handles input and conversation state.
2. `frontend/src/api.ts` sends the new message, session ID, and optional instructions to FastAPI.
3. `backend/app/schemas.py` validates the request, rejecting blank or oversized messages with HTTP 422.
4. `backend/app/main.py` loads SQLite history and builds system instructions + prior turns + the new message.
5. `backend/app/llm.py` calls LiteLLM with caching and ordered fallback.
6. `backend/app/database.py` saves a successful turn atomically.
7. React displays the reply and its own metadata. The model remembers earlier turns because the backend supplies them on each request.

## 4. Verification: how to see failover, cache hits and per-message token usage

### Manual checks

1. **Health:** open `/health`. Expect `status: "ok"`, at least two configured keys, and `cache_enabled: true`. This checks configuration and readiness, not whether the provider accepts the keys.
2. **Conversation memory:** send `My name is Dishant`, then `What is my name?` in the same conversation. The reply should recall the name.
3. **Per-message tokens:** each assistant reply shows source, model, latency, input tokens, and output tokens. Input tokens include system instructions, history, and the new question; output tokens belong to that reply. These are per-response values, not session totals. Expand **Routing details** to see the answering key and fallback count.
4. **Cache hit:** choose **New conversation**, send a distinctive opening question, then start another new conversation and send exactly the same question with the same instructions. Keep failure simulation off. The second reply should show `LLM_CACHE`, no answering key, and the original token counts. Cache must still be warm on the same backend instance.
5. **Failover:** open **Customize → Developer tools → Test provider failover**, select **First key rate-limited (429)**, close settings, and send a message. Expect a real reply from `key_2` and one fallback attempt. The simulation applies once and resets automatically; success still needs a valid backup key and available quota.
6. **All keys fail:** select **All keys rate-limited** and send a message. Expect a clear error; the failed turn must not appear in stored history.
7. **History:** use `/docs` to call `GET /sessions/{session_id}/messages` for a successful session. Expect ordered user/assistant messages and assistant metadata.

The equivalent simulation header is `X-Simulate-Failure: key_1=429`; use `*=429` for all keys. It is enabled only when `ENABLE_FAILURE_SIMULATION=true`. Injecting an error skips that provider attempt, but a successful fallback makes a real model request.

### Automated deployment checks

From the repository root:

```powershell
# Health, frontend, CORS, and validation; no model requests.
python scripts/verify_deployment.py --backend https://ample-empathy-production-7cb2ef33.up.railway.app --frontend https://llm-chatbot-production-9dce5b1b.up.railway.app

# Adds real chat, memory, caching, and failover; uses provider quota.
python scripts/verify_deployment.py --backend https://ample-empathy-production-7cb2ef33.up.railway.app --frontend https://llm-chatbot-production-9dce5b1b.up.railway.app --live
```

The live check prints a session ID. Restart the backend, then run the same infrastructure command with `--verify-session SESSION_ID` to verify stored history survives. This hosted restart check is still pending.

### Local tests and builds

Backend, from the repository root:

```powershell
cd backend
uv run pytest -q
```

Frontend, in another terminal from the repository root:

```powershell
cd frontend
npm.cmd run build
npm.cmd run test:e2e
```

Backend tests use fake/mocked model responses and temporary SQLite databases. Browser tests mock the API and use installed Chrome locally; CI uses Chromium. They do not consume real provider credits. Tests cover the API contract, history, cache metadata, fallback, and UI interactions. Packaging checks alone do not validate live credentials or persistent storage.

For a short demo, show health, a two-turn memory example, per-message metadata, a cross-session cache hit, single-key failover, and all-key failure. A narrated demo recording remains a separate submission artifact.

## 5. Setup Used: your editor and AI tools

- **Editor:** Visual Studio Code on Windows, with PowerShell terminals.
- **AI assistance:** OpenAI Codex assisted with implementation, debugging, interface refinement, documentation, and verification.
- **Frontend:** React, TypeScript, Vite, React Markdown, and remark-gfm.
- **Backend:** Python, FastAPI, Uvicorn, LiteLLM, and Python's built-in SQLite library.
- **Development and deployment:** uv, npm, Git/GitHub, Docker Desktop, Docker Compose, Nginx, and Railway.
- **Verification tools:** pytest, Playwright, TypeScript checks, production builds, and the deployment verification script.

Provider keys stay in the ignored `.env` file or backend deployment secrets. They are not bundled into browser code or committed to the repository.

## 6. Bonus features (if any): what you added beyond the requirements and why

| Feature | Why it was added |
| --- | --- |
| Responsive workspace, light/dark themes, and a fixed composer | Keep the chat usable on desktop and mobile and make writing follow-up messages easier. |
| New answers scroll to their beginning | Let readers start with the first line rather than landing at the end of a long reply. |
| Searchable browser conversation shortcuts | Help users reopen recent sessions; full messages are retrieved from SQLite. |
| Safe Markdown, code blocks, and tables | Make technical answers easier to read while disabling raw HTML and remote image rendering. |
| Copy replies and Markdown export | Let users reuse answers and save a conversation outside the app. |
| Starter prompts and instruction presets | Reduce the effort needed to begin a useful conversation or choose a response style. |
| App creator attribution | Credit Dishant for building and customizing Lyftr Chat, while distinguishing the underlying model provider's training work. Applies to new and resumed conversations. |
| Editable retry drafts and one-use failure controls | Help recover from failed requests and avoid accidentally leaving demo failures enabled. |
| Backend health indicator | Show readiness without claiming that the model provider is available. |
| Automated browser tests and cloud-build URL checks | Catch interaction regressions and prevent deployment with a localhost API URL. |

Each page load starts a new session; selecting a saved sidebar conversation explicitly resumes it. The browser keeps up to 30 session shortcuts with IDs and titles, while full messages stay on the backend. Earlier sessions without a browser shortcut are not automatically listed.

There is no admin dashboard or user authentication. Anyone who knows a session ID can access its history endpoint. This assignment demo should not be used for confidential conversations.
