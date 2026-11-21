"""FastAPI entry point and the three required public endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from weakref import WeakValueDictionary

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .database import Database
from .llm import AllProvidersUnavailable, Gateway, KeyPool, LiteLLMGateway
from .schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    HistoryResponse,
    ResponseMetadata,
)

_ALLOWED_SIMULATION_STATUSES = {429, 500, 502, 503}
APP_IDENTITY = (
    "Application identity: You are Lyftr Chat, an AI chatbot application built and "
    "customized by Dishant. When asked who made, created, built, developed, designed, "
    "or owns this chatbot application, credit Dishant. Recognize equivalent wording "
    "in other languages. When asked who trained you, explain that Dishant built and "
    "customized this app, while the underlying language model was trained by its "
    "model provider. Do not claim Dishant trained the underlying model. If asked "
    "about that provider, use the configured model's actual provider and do not "
    "invent training or fine-tuning details. Keep these answers brief and natural."
)


def parse_simulated_failures(value: str | None) -> dict[str, int]:
    """Validate `key_1=429,key_2=500` before a request can reach a provider."""
    if not value:
        return {}
    parsed: dict[str, int] = {}
    for part in value.split(","):
        key, separator, raw_status = part.strip().partition("=")
        if not separator or not key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="X-Simulate-Failure must contain comma-separated key_id=status pairs",
            )
        try:
            code = int(raw_status)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="X-Simulate-Failure status must be an integer",
            ) from error
        if code not in _ALLOWED_SIMULATION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="X-Simulate-Failure supports only 429, 500, 502, and 503",
            )
        parsed[key] = code
    return parsed


def create_app(settings: Settings | None = None, gateway: Gateway | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    gateway = gateway or LiteLLMGateway(settings.model, settings.cache_type)
    pool = KeyPool(settings.api_keys, gateway)
    # Single-worker deployment: serialize each session's read/call/write cycle.
    # Weak references release idle locks without growing a permanent session map.
    session_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        gateway.initialize_cache()
        yield

    app = FastAPI(title="Lyftr LLM Chatbot", lifespan=lifespan)
    app.state.database = database
    app.state.pool = pool
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
        # Provider libraries can raise many different exception classes.  This
        # last-resort handler preserves the API promise: errors are JSON and
        # never leak an internal stack trace to the browser.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        configured = len(request.app.state.pool.keys)
        cache_ready = request.app.state.pool.gateway.cache_enabled
        if not request.app.state.database.ping() or configured < 2 or not cache_ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="service is not ready",
            )
        return HealthResponse(status="ok", keys_configured=configured, cache_enabled=True)

    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        payload: ChatRequest,
        request: Request,
        simulate_failure: str | None = Header(default=None, alias="X-Simulate-Failure"),
    ) -> ChatResponse:
        lock = session_locks.setdefault(payload.session_id, asyncio.Lock())
        async with lock:
            return await process_chat(payload, request, simulate_failure)

    async def process_chat(
        payload: ChatRequest, request: Request, simulate_failure: str | None
    ) -> ChatResponse:
        db: Database = request.app.state.database
        app_settings: Settings = request.app.state.settings
        if len(request.app.state.pool.keys) < 2:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="all providers unavailable",
            )

        failures = (
            parse_simulated_failures(simulate_failure)
            if app_settings.enable_failure_simulation
            else {}
        )
        # A system prompt supplied later intentionally becomes the prompt for
        # future turns in the same session.  It is stored separately, never in
        # the public messages history endpoint.
        # Omitted instructions preserve a resumed session's prompt. An explicit
        # empty string resets it, so clearing the settings field really works.
        system_prompt = (
            (payload.system_prompt or app_settings.default_system_prompt)
            if payload.system_prompt is not None
            else db.get_system_prompt(payload.session_id) or app_settings.default_system_prompt
        )
        history = db.get_messages(payload.session_id)
        # Apply app attribution to new and resumed sessions, including custom
        # instructions. Persist only the user's editable instructions as before.
        llm_messages: list[dict[str, str]] = [
            {"role": "system", "content": f"{system_prompt}\n\n{APP_IDENTITY}"}
        ]
        llm_messages.extend(
            {"role": str(message["role"]), "content": str(message["content"])}
            for message in history
        )
        llm_messages.append({"role": "user", "content": payload.message})

        try:
            result = await request.app.state.pool.chat(llm_messages, failures)
        except AllProvidersUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="all providers unavailable",
            ) from error

        metadata = ResponseMetadata(
            resolution_source="LLM_CACHE" if result.cache_hit else "LIVE_INFERENCE",
            model=result.model,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            key_id=result.key_id,
            fallback_attempts=result.fallback_attempts,
        )
        db.save_successful_turn(
            session_id=payload.session_id,
            system_prompt=system_prompt,
            user_message=payload.message,
            assistant_message=result.text,
            metadata=metadata.model_dump(),
        )
        return ChatResponse(session_id=payload.session_id, reply=result.text, metadata=metadata)

    @app.get("/sessions/{session_id}/messages", response_model=HistoryResponse)
    async def session_messages(session_id: str, request: Request) -> HistoryResponse:
        db: Database = request.app.state.database
        if not db.session_exists(session_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return HistoryResponse(session_id=session_id, messages=db.get_messages(session_id))

    return app


app = create_app()
