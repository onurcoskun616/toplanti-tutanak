"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite+aiosqlite:///./toplanti.db"

    # The published GitHub Pages frontend, plus any localhost port for local
    # dev/testing (matched separately via a regex — see main.py).
    cors_origins: str = "https://onurcoskun616.github.io"

    # ASR (Faz 1 — faster-whisper, Turkish, no diarization). Model weights
    # download from Hugging Face on first use unless pre-baked into the
    # image. "int8" keeps CPU inference practical without a GPU.
    asr_model_size: str = "small"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_language: str = "tr"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
