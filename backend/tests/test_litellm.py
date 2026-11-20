"""Exercise LiteLLM's actual cache with its provider mock (no paid requests)."""
import asyncio

import litellm

from app.llm import LiteLLMGateway, ProviderKey, KeyPool, AllProvidersUnavailable


def test_real_litellm_cache_and_usage(monkeypatch):
    original = litellm.acompletion
    monkeypatch.setattr(litellm, "cache", None)

    async def mocked_provider(**kwargs):
        return await original(**kwargs, mock_response="Paris is the capital of France.")

    monkeypatch.setattr(litellm, "acompletion", mocked_provider)

    async def scenario():
        gateway = LiteLLMGateway("openai/gpt-4o-mini", "local")
        gateway.initialize_cache()
        messages = [{"role": "user", "content": "What is the capital of France?"}]
        first = await gateway.complete(messages=messages, key=ProviderKey("key_1", "fake-one"), bypass_cache=False)
        # Allow LiteLLM's asynchronous cache write to finish.
        await asyncio.sleep(0.1)
        second = await gateway.complete(messages=messages, key=ProviderKey("key_2", "fake-two"), bypass_cache=False)
        changed = await gateway.complete(messages=[{"role": "user", "content": "Different question"}], key=ProviderKey("key_1", "fake-one"), bypass_cache=False)
        assert not first.cache_hit
        assert second.cache_hit
        assert not changed.cache_hit
        assert first.text == second.text
        assert first.input_tokens == second.input_tokens
        assert first.output_tokens == second.output_tokens
        assert second.input_tokens > 0

    asyncio.run(scenario())


def test_concurrent_requests_keep_simulation_and_key_ids_separate():
    from test_api import FakeGateway

    gateway = FakeGateway()
    gateway.initialize_cache()
    original = gateway.complete

    async def delayed_provider(**kwargs):
        await asyncio.sleep(0.01)
        return await original(**kwargs)

    gateway.complete = delayed_provider
    pool = KeyPool(("fake-one", "fake-two"), gateway)

    async def scenario():
        results = await asyncio.gather(
            pool.chat([{"role": "user", "content": "fallback request"}], {"key_1": 429}),
            pool.chat([{"role": "user", "content": "normal request"}], {}),
            pool.chat([{"role": "user", "content": "unavailable request"}], {"*": 503}),
            return_exceptions=True,
        )
        assert results[0].key_id == "key_2"
        assert results[0].fallback_attempts == 1
        assert results[1].key_id == "key_1"
        assert results[1].fallback_attempts == 0
        assert isinstance(results[2], AllProvidersUnavailable)

    asyncio.run(scenario())


def test_router_fallback_then_cache_preserves_metadata(monkeypatch):
    original = litellm.acompletion
    monkeypatch.setattr(litellm, "cache", None)

    async def mocked_provider(**kwargs):
        return await original(**kwargs, mock_response="A real LiteLLM mock completion.")

    monkeypatch.setattr(litellm, "acompletion", mocked_provider)

    async def scenario():
        gateway = LiteLLMGateway("openai/gpt-4o-mini", "local")
        gateway.initialize_cache()
        pool = KeyPool(("fake-one", "fake-two", "fake-three"), gateway)
        messages = [{"role": "user", "content": "Router integration test"}]
        fallback = await pool.chat(messages, {"key_1": 429, "key_2": 502})
        assert fallback.key_id == "key_3"
        assert fallback.fallback_attempts == 2
        assert not fallback.cache_hit
        first = await pool.chat(messages, {})
        await asyncio.sleep(0.1)
        cached = await pool.chat(messages, {})
        assert not first.cache_hit
        assert cached.cache_hit
        assert cached.key_id is None
        assert cached.fallback_attempts == 0
        assert cached.text == first.text
        assert cached.input_tokens == first.input_tokens
        assert cached.output_tokens == first.output_tokens

    asyncio.run(scenario())
