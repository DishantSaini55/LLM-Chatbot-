"""Exercise LiteLLM's actual cache with its provider mock (no paid requests)."""
import asyncio

import litellm

from app.llm import LiteLLMGateway, ProviderKey


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
