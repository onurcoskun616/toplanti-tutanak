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
    # image. "int8" keeps CPU inference practical without a GPU. "tiny" is
    # the default so a free/memory-constrained host (e.g. Render's free
    # tier, 512MB RAM) has a real chance of loading it — bump to "small"/
    # "base" for better accuracy where more RAM is available.
    asr_model_size: str = "tiny"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_language: str = "tr"
    # Both the first model load (download + init) AND per-chunk inference
    # can be slow on a CPU-constrained host (observed: a 6s chunk taking
    # 45s+ to transcribe on Render's free tier) — cap how long one request
    # waits so a stuck/too-slow attempt 503s instead of hanging forever.
    asr_request_timeout_seconds: int = 120

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
