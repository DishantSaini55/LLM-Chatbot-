"""Environment-only configuration.

Keeping configuration in one small module makes deployments predictable: Docker,
local development, and a cloud host all supply the same variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    api_keys: tuple[str, ...]
    model: str
    database_url: str
    allowed_origins: tuple[str, ...]
    enable_failure_simulation: bool
    default_system_prompt: str
    cache_type: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_keys=_csv(os.getenv("LLM_API_KEYS", "")),
            model=os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash"),
            database_url=os.getenv("DATABASE_URL", "sqlite:////data/app.db"),
            allowed_origins=_csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")),
            enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower()
            == "true",
            default_system_prompt=os.getenv(
                "DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."
            ),
            # LiteLLM supports both "local" and "disk" without extra services.
            cache_type=os.getenv("LITELLM_CACHE_TYPE", "local"),
        )
