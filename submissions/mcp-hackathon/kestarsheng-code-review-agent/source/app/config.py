# -*- coding: utf-8 -*-
"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_SLUG = "kestarsheng-code-review-agent"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM (OpenAI-compatible protocol: DeepSeek / Qwen / etc.)
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 120.0

    # Deployment identification
    commit: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000

    # Safety
    max_code_chars: int = 60_000
    max_response_chars: int = 20_000


@lru_cache
def get_settings() -> Settings:
    return Settings()