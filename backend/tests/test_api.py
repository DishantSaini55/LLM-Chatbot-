from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMResult, ProviderKey
from app.main import create_app


@dataclass
class FakeGateway:
    """Test double: behaves like LiteLLM without network calls or real keys."""

    cache_enabled: bool = False
    seen: list[tuple[str, list[dict[str, str]]]] = field(default_factory=list)
    cache: dict[str, LLMResult] = field(default_factory=dict)

    def initialize_cache(self) -> None:
        self.cache_enabled = True

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        key: ProviderKey,
        bypass_cache: bool,
    ) -> LLMResult:
        self.seen.append((key.id, messages))
        fingerprint = repr(messages)
        if not bypass_cache and fingerprint in self.cache:
            cached = self.cache[fingerprint]
            return LLMResult(
                text=cached.text,
                model=cached.model,
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                cache_hit=True,
            )
        result = LLMResult(
            text=f"reply to {messages[-1]['content']}",
            model="gemini/gemini-2.0-flash",
            input_tokens=len(messages),
            output_tokens=4,
            cache_hit=False,
        )
        if not bypass_cache:
            self.cache[fingerprint] = result
        return result


def make_client(tmp_path: Path) -> tuple[TestClient, FakeGateway]:
    gateway = FakeGateway()
    settings = Settings(
        api_keys=("key-a", "key-b"),
        model="gemini/gemini-2.0-flash",
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        allowed_origins=("http://localhost:3000",),
        enable_failure_simulation=True,
        default_system_prompt="Be useful.",
        cache_type="local",
    )
    return TestClient(create_app(settings, gateway)), gateway


def test_chat_persists_turns_and_keeps_context(tmp_path: Path) -> None:
    client, gateway = make_client(tmp_path)
    with client:
        first = client.post("/chat", json={"session_id": "s-1", "message": "First question"})
        assert first.status_code == 200
        assert first.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        assert first.json()["metadata"]["key_id"] == "key_1"

        second = client.post("/chat", json={"session_id": "s-1", "message": "Second question"})
        assert second.status_code == 200
        sent_messages = gateway.seen[-1][1]
        assert [message["role"] for message in sent_messages] == [
            "system",
            "user",
            "assistant",
            "user",
        ]

        history = client.get("/sessions/s-1/messages")
        assert history.status_code == 200
        assert [message["role"] for message in history.json()["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]


def test_cache_hit_has_no_key_and_no_fallbacks(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        first = client.post("/chat", json={"session_id": "a", "message": "same"})
        second = client.post("/chat", json={"session_id": "b", "message": "same"})
    assert first.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    metadata = second.json()["metadata"]
    assert metadata["resolution_source"] == "LLM_CACHE"
    assert metadata["key_id"] is None
    assert metadata["fallback_attempts"] == 0


def test_failure_hook_uses_the_next_key_and_all_failed_is_503(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        fallback = client.post(
            "/chat",
            headers={"X-Simulate-Failure": "key_1=429"},
            json={"session_id": "failover", "message": "hello"},
        )
        assert fallback.status_code == 200
        assert fallback.json()["metadata"]["key_id"] == "key_2"
        assert fallback.json()["metadata"]["fallback_attempts"] == 1

        unavailable = client.post(
            "/chat",
            headers={"X-Simulate-Failure": "*=429"},
            json={"session_id": "all-fail", "message": "hello"},
        )
        assert unavailable.status_code == 503
        assert unavailable.json() == {"detail": "all providers unavailable"}
        assert client.get("/sessions/all-fail/messages").status_code == 404


def test_validation_and_health_contract(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        assert client.get("/health").json() == {
            "status": "ok",
            "keys_configured": 2,
            "cache_enabled": True,
        }
        bad = client.post("/chat", json={"session_id": "x", "message": "   "})
        assert bad.status_code == 422
