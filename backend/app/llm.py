"""LiteLLM integration and deterministic key failover.

LiteLLM owns provider calls, caching, and fallback traversal. A request-scoped
adapter supplies stable key IDs, failure counts, and simulated provider errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ProviderKey:
    id: str
    secret: str


@dataclass(frozen=True, slots=True)
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    key_id: str | None
    fallback_attempts: int
    latency_ms: int


class AllProvidersUnavailable(Exception):
    """Raised only after every configured key had a retryable failure."""


class SimulatedProviderError(Exception):
    def __init__(self, status: int):
        super().__init__("simulated provider failure")
        self.status_code = status


class Gateway(Protocol):
    cache_enabled: bool

    def initialize_cache(self) -> None: ...

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        key: ProviderKey,
        bypass_cache: bool,
    ) -> LLMResult: ...


class LiteLLMGateway:
    """The production gateway.  Imports LiteLLM lazily for cheap test imports."""

    def __init__(self, model: str, cache_type: str) -> None:
        self.model = model
        self.cache_type = cache_type
        self.cache_enabled = False

    def initialize_cache(self) -> None:
        # LiteLLM's exact-match local cache keys the whole request.  Because
        # `messages` below contains system prompt + complete history + new user
        # message, a cache hit is safe across sessions and never crosses turns.
        import litellm
        from litellm import Cache

        litellm.cache = Cache(type=self.cache_type)
        self.cache_enabled = True

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        key: ProviderKey,
        bypass_cache: bool,
    ) -> LLMResult:
        import litellm

        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            api_key=key.secret,
            timeout=30,
            num_retries=0,
            # Failure simulation intentionally bypasses cached values: it is a
            # demonstration of provider failover, not a cache test.
            caching=not bypass_cache,
        )
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            raise RuntimeError("provider returned an empty assistant response")
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=text,
            model=self.model,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cache_hit=self._is_cache_hit(response),
        )

    @staticmethod
    def _is_cache_hit(response: object) -> bool:
        """Handle LiteLLM's public and older internal hidden-parameter names."""
        for attribute in ("hidden_params", "_hidden_params"):
            parameters = getattr(response, attribute, None)
            if isinstance(parameters, Mapping):
                return bool(parameters.get("cache_hit"))
            if parameters is not None:
                return bool(getattr(parameters, "cache_hit", False))
        return False


def provider_status(error: Exception) -> int | None:
    """LiteLLM providers expose status differently; normalize the common forms."""
    for attribute in ("status_code", "status"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_retryable_provider_error(error: Exception) -> bool:
    status = provider_status(error)
    if status in (408, 429) or isinstance(error, TimeoutError) or (status is not None and 500 <= status <= 599):
        return True
    # Some providers represent exhausted quota without a useful HTTP code.
    return "quota" in str(error).lower()


@dataclass
class RoutingState:
    simulated_failures: dict[str, int]
    failed_keys: int = 0
    key_id: str | None = None
    result: LLMResult | None = None
    fatal: Exception | None = None


_routing_state: ContextVar[RoutingState] = ContextVar("chat_routing_state")


class KeyPool:
    def __init__(self, keys: tuple[str, ...], gateway: Gateway) -> None:
        self.keys = tuple(
            ProviderKey(id=f"key_{index}", secret=secret)
            for index, secret in enumerate(keys, start=1)
        )
        self.gateway = gateway
        self._router = None

    def _build_router(self):
        """Bridge the gateway into LiteLLM's native async fallback machinery.

        The protected attempt hook is version-specific, so LiteLLM is pinned and
        integration-tested. The Router owns fallback traversal; the hook adds
        request-scoped simulation and observability around one provider attempt.
        """
        import litellm

        pool = self
        key_map = {key.id: key for key in self.keys}

        class ObservableRouter(litellm.Router):
            async def _acompletion(self, model, messages, **kwargs):
                state = _routing_state.get()
                if state.fatal is not None:
                    raise state.fatal
                key = key_map[model]
                code = state.simulated_failures.get(key.id, state.simulated_failures.get("*"))
                try:
                    if code is not None:
                        raise SimulatedProviderError(code)
                    result = await pool.gateway.complete(
                        messages=messages, key=key, bypass_cache=bool(state.simulated_failures)
                    )
                except Exception as error:
                    if not is_retryable_provider_error(error):
                        state.fatal = error
                        raise
                    state.failed_keys += 1
                    # Normalize quota/provider errors so Router can apply its
                    # native fallback policy consistently across providers.
                    raise litellm.RateLimitError(
                        message="provider unavailable", model=model, llm_provider="gateway"
                    ) from error
                state.key_id, state.result = key.id, result
                # Router adds fallback headers to a ModelResponse. The original
                # gateway result retains exact usage/cache metadata for our API.
                return litellm.ModelResponse(
                    model=result.model,
                    choices=[{"message": {"role": "assistant", "content": result.text}}],
                    usage={"prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens, "total_tokens": result.input_tokens + result.output_tokens},
                )

        model = getattr(self.gateway, "model", "openai/gpt-4o-mini")
        ids = list(key_map)
        return ObservableRouter(
            model_list=[{"model_name": key.id, "litellm_params": {"model": model, "api_key": key.secret}} for key in self.keys],
            fallbacks=[{ids[0]: ids[1:]}] if ids else [],
            num_retries=0,
            max_fallbacks=max(1, len(ids)),
            disable_cooldowns=True,
            timeout=30,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        simulated_failures: dict[str, int],
    ) -> ChatResult:
        start = time.perf_counter()
        if not self.keys:
            raise AllProvidersUnavailable("no providers configured")
        if self._router is None:
            self._router = self._build_router()
        state = RoutingState(simulated_failures=simulated_failures)
        token = _routing_state.set(state)
        try:
            try:
                await self._router.acompletion(model=self.keys[0].id, messages=messages)
            except Exception as error:
                if state.fatal is not None:
                    raise state.fatal
                raise AllProvidersUnavailable("all configured providers failed") from error
            result = state.result
            if result is None:
                raise AllProvidersUnavailable("provider returned no response")
            return ChatResult(
                text=result.text,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_hit=result.cache_hit,
                key_id=None if result.cache_hit else state.key_id,
                fallback_attempts=0 if result.cache_hit else state.failed_keys,
                latency_ms=round((time.perf_counter() - start) * 1000),
            )
        finally:
            _routing_state.reset(token)
