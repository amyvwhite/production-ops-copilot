"""Settings from the environment (a .env file works too). No secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

try:  # optional convenience for local runs
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    gemini_api_key: str
    gemini_model: str
    # Cost / quota guardrails. The free tier is rate limited, so calls are cached and capped.
    max_ai_calls_per_day: int
    cache_dir: Path
    today_override: date | None

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key)


def get_settings() -> Settings:
    env = os.environ.get
    today = env("PRODOPS_TODAY", "")
    return Settings(
        data_dir=Path(env("PRODOPS_DATA_DIR", str(PROJECT_ROOT / "sample_data"))),
        gemini_api_key=env("GEMINI_API_KEY", ""),
        gemini_model=env("GEMINI_MODEL", "gemini-2.5-flash"),
        max_ai_calls_per_day=int(env("MAX_AI_CALLS_PER_DAY", "200")),
        cache_dir=Path(env("PRODOPS_CACHE_DIR", str(PROJECT_ROOT / ".cache"))),
        today_override=date.fromisoformat(today) if today else None,
    )
