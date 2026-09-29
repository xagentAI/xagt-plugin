# -*- coding: utf-8 -*-
"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_SLUG = "kestarsheng-contract-guard"
PROJECT_NAME = "Contract Guard"
PROJECT_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM (OpenAI-compatible protocol) — optional advisory layer only.
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 60.0

    # Deployment identification
    commit: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000

    # Safety
    max_spec_chars: int = 200_000
    max_spec_bytes: int = 2_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()