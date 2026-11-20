"""LiteLLM integration and deterministic key failover.

LiteLLM owns provider-specific request formatting and response caching.  This
small key-pool wrapper owns assignment-specific observability: stable key IDs,
the number of failed keys, and a simulation hook that never touches a provider.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
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
            model=getattr(response, "model", None) or self.model,
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
    if status == 429 or (status is not None and 500 <= status <= 599):
        return True
    # Some providers represent exhausted quota without a useful HTTP code.
    return "quota" in str(error).lower()


class KeyPool:
    def __init__(self, keys: tuple[str, ...], gateway: Gateway) -> None:
        self.keys = tuple(
            ProviderKey(id=f"key_{index}", secret=secret)
            for index, secret in enumerate(keys, start=1)
        )
        self.gateway = gateway

    async def chat(
        self,
        messages: list[dict[str, str]],
        simulated_failures: dict[str, int],
    ) -> ChatResult:
        fallback_attempts = 0
        start = time.perf_counter()

        for key in self.keys:
            simulated_status = simulated_failures.get(key.id, simulated_failures.get("*"))
            if simulated_status is not None:
                fallback_attempts += 1
                continue

            try:
                result = await self.gateway.complete(
                    messages=messages,
                    key=key,
                    bypass_cache=bool(simulated_failures),
                )
            except Exception as error:
                if is_retryable_provider_error(error):
                    fallback_attempts += 1
                    continue
                raise

            latency_ms = round((time.perf_counter() - start) * 1000)
            if result.cache_hit:
                # LiteLLM returned before contacting a provider.  Cache hits do
                # not belong to any key and have no fallback attempts.
                return ChatResult(
                    text=result.text,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cache_hit=True,
                    key_id=None,
                    fallback_attempts=0,
                    latency_ms=latency_ms,
                )
            return ChatResult(
                text=result.text,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_hit=False,
                key_id=key.id,
                fallback_attempts=fallback_attempts,
                latency_ms=latency_ms,
            )

        raise AllProvidersUnavailable("all configured providers failed")
