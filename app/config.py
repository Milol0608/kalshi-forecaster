"""Settings and the live-trading safety gate.

MODE defaults to shadow. Live trading needs all three conditions from the build spec
(Section 4); `check_live_gate` reports every one that fails, not just the first.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LIVE_CONFIRMATION_PHRASE = "yes-i-understand-real-money"


class Mode(StrEnum):
    SHADOW = "shadow"
    DEMO = "demo"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mode: Mode = Mode.SHADOW
    live_trading_confirmed: str = ""
    gate_file: Path = Path("gate1_passed.json")
    gate_max_age_days: int = 30

    database_url: str = "postgresql+psycopg://kalshi:kalshi@127.0.0.1:5432/kalshi"

    kalshi_prod_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    kalshi_demo_base_url: str = "https://external-api.demo.kalshi.co/trade-api/v2"
    kalshi_demo_key_id: str = ""
    kalshi_demo_private_key_path: Path | None = None
    kalshi_prod_key_id: str = ""
    kalshi_prod_private_key_path: Path | None = None

    anthropic_api_key: str = Field(default="", repr=False)

    starting_bankroll: float = 100.0
    min_edge: float = 0.03
    max_position_pct: float = 0.05
    max_total_exposure_pct: float = 0.25
    max_per_event_pct: float = 0.10
    kill_switch_drawdown_pct: float = 0.30

    # Scanner. Series are discovered from Kalshi metadata, not hardcoded.
    # SERIES_TICKERS (comma-separated) overrides discovery when set.
    series_tickers: str = ""
    series_category: str = "Climate and Weather"
    series_tag: str = "Daily temperature"
    series_title_include: str = r"\b(high|highest|max|maximum)\b"
    series_title_exclude: str = r"\b(low|lowest|min|minimum)\b"
    min_volume_24h: float = 50.0
    min_minutes_to_close: float = 60.0
    kalshi_max_requests_per_second: float = 5.0

    @property
    def market_data_base_url(self) -> str:
        """Shadow and live read production prices; demo reads the demo environment."""
        return self.kalshi_demo_base_url if self.mode is Mode.DEMO else self.kalshi_prod_base_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


class LiveTradingLocked(RuntimeError):
    """Raised when anything tries to trade real money without passing every gate condition."""


def check_live_gate(settings: Settings, now: datetime | None = None) -> list[str]:
    """Return the list of failed live-trading conditions. Empty list means unlocked."""
    now = now or datetime.now(timezone.utc)
    failures: list[str] = []

    if settings.mode is not Mode.LIVE:
        failures.append(f"MODE is '{settings.mode}', not 'live'")

    if settings.live_trading_confirmed != LIVE_CONFIRMATION_PHRASE:
        failures.append("LIVE_TRADING_CONFIRMED is not set to the required confirmation phrase")

    failures.extend(_gate_file_failures(settings.gate_file, settings.gate_max_age_days, now))
    return failures


def _gate_file_failures(path: Path, max_age_days: int, now: datetime) -> list[str]:
    # Age comes from the passed_at timestamp the gate checker writes, not file mtime,
    # because mtime changes on copy/touch and would let a stale pass look fresh.
    if not path.is_file():
        return [f"gate file {path} does not exist"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        passed_at = datetime.fromisoformat(data["passed_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"gate file {path} is unreadable or missing passed_at: {exc}"]

    if data.get("passed") is not True:
        return [f"gate file {path} does not record passed=true"]
    if passed_at.tzinfo is None:
        return [f"gate file {path} passed_at has no timezone"]
    if passed_at > now:
        return [f"gate file {path} passed_at is in the future"]
    if now - passed_at > timedelta(days=max_age_days):
        return [f"gate file {path} is older than {max_age_days} days"]
    return []


def assert_live_allowed(settings: Settings, now: datetime | None = None) -> None:
    failures = check_live_gate(settings, now)
    if failures:
        raise LiveTradingLocked("Live trading is locked: " + "; ".join(failures))
