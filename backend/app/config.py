"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
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
    monitor_refresh_interval_s: int = Field(default=21600, ge=300)
    firms_map_key: str = ""
    firms_base_url: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    firms_sources: tuple[str, ...] = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
    firms_bbox: str = "-73.6,-55.2,-53.5,-21.7"
    confidence_horizon_decay_per_day: float = Field(default=0.025, ge=0.0, le=0.2)
    confidence_stale_penalty: float = Field(default=0.15, ge=0.0, le=0.5)
    confidence_high_cutoff: float = Field(default=75.0, ge=0.0, le=100.0)
    confidence_medium_cutoff: float = Field(default=50.0, ge=0.0, le=100.0)
    risk_cutoff_mode: Literal["daily_percentile", "static"] = "daily_percentile"
    risk_top_frac_extremo: float = Field(default=0.0005, gt=0.0, lt=0.5)
    risk_top_frac_alto: float = Field(default=0.004, gt=0.0, lt=0.5)
    risk_top_frac_moderado: float = Field(default=0.025, gt=0.0, lt=0.5)
    risk_floor_extremo: float = Field(default=0.015, ge=0.0, le=1.0)
    risk_floor_alto: float = Field(default=0.013, ge=0.0, le=1.0)
    risk_floor_moderado: float = Field(default=0.0005, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
