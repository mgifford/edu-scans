"""Runtime settings model and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.lib.errors import ConfigError


@dataclass(slots=True)
class Settings:
    scheduler_cadence: str = "monthly"
    crawl_rate_limit_per_host: float = 0.5
    crawl_timeout_seconds: int = 20
    toon_output_dir: Path = Path("data/toon-cache")
    metadata_db_url: str = "sqlite:///data/metadata.db"


def _parse_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a float, got: {value}") from exc


def _parse_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an int, got: {value}") from exc


def load_settings() -> Settings:
    """Load runtime settings from environment with validation."""
    settings = Settings(
        scheduler_cadence=os.getenv("SCHEDULER_CADENCE", "monthly").strip().lower(),
        crawl_rate_limit_per_host=_parse_float("CRAWL_RATE_LIMIT_PER_HOST", 0.5),
        crawl_timeout_seconds=_parse_int("CRAWL_TIMEOUT_SECONDS", 20),
        toon_output_dir=Path(os.getenv("TOON_OUTPUT_DIR", "data/toon-cache")),
        metadata_db_url=os.getenv("METADATA_DB_URL", "sqlite:///data/metadata.db").strip(),
    )

    if settings.scheduler_cadence not in {"monthly", "weekly", "daily"}:
        raise ConfigError(
            f"SCHEDULER_CADENCE must be one of monthly|weekly|daily, got: {settings.scheduler_cadence}"
        )
    if settings.crawl_rate_limit_per_host <= 0:
        raise ConfigError("CRAWL_RATE_LIMIT_PER_HOST must be > 0")
    if settings.crawl_timeout_seconds <= 0:
        raise ConfigError("CRAWL_TIMEOUT_SECONDS must be > 0")
    if not settings.metadata_db_url:
        raise ConfigError("METADATA_DB_URL is required")

    return settings
