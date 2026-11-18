"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    models_dir: Path = Field(default=Path(__file__).resolve().parents[1] / "models")
    static_dir: Path | None = None
    openmeteo_url: str = "https://api.open-meteo.com/v1/forecast"
    forecast_days: int = Field(default=15, ge=1, le=16)
    past_days: int = Field(default=30, ge=29, le=60)
    cache_ttl_s: int = Field(default=10800, ge=60)
    refresh_interval_s: int = Field(default=10800, ge=300)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    chunk_size: int = Field(default=100, ge=1, le=200)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    enable_spread: bool = True
    monitor_dir: Path = Field(default=Path(__file__).resolve().parents[1] / "monitor_data")
    enable_monitor_snapshots: bool = True
    monitor_duckdb_memory_limit: str = "256MB"
    confidence_horizon_decay_per_day: float = Field(default=0.025, ge=0.0, le=0.2)
    confidence_stale_penalty: float = Field(default=0.15, ge=0.0, le=0.5)
    confidence_high_cutoff: float = Field(default=75.0, ge=0.0, le=100.0)
    confidence_medium_cutoff: float = Field(default=50.0, ge=0.0, le=100.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
