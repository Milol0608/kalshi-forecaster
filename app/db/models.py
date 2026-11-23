"""ORM models.

Each milestone adds its own tables
(Section 6 of the build spec) in its own migration, so schemas are shaped by real
API data instead of guessed up front.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Prices are dollars with 4 decimals ("0.4200"); counts can be fractional ("9261.48").
Price = Numeric(10, 4)
Count = Numeric(18, 2)
Json = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One pipeline run: status, duration and errors. Failures are recorded, not raised."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)  # running | ok | failed
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class Market(Base):
    """Latest known metadata for one market. Prices live in market_snapshots, not here."""

    __tablename__ = "markets"

    ticker: Mapped[str] = mapped_column(String(128), primary_key=True)
    series_ticker: Mapped[str] = mapped_column(String(64), index=True)
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    yes_sub_title: Mapped[str | None] = mapped_column(Text)
    strike_type: Mapped[str | None] = mapped_column(String(32))
    floor_strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cap_strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    rules_primary: Mapped[str] = mapped_column(Text)
    rules_secondary: Mapped[str] = mapped_column(Text)
    settlement_sources: Mapped[Any] = mapped_column(Json)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expected_expiration_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketSnapshot(Base):
    """Top-of-book and activity for one market at one scan. fetched_at = when we received it."""

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    yes_bid: Mapped[Decimal | None] = mapped_column(Price)
    yes_ask: Mapped[Decimal | None] = mapped_column(Price)
    no_bid: Mapped[Decimal | None] = mapped_column(Price)
    no_ask: Mapped[Decimal | None] = mapped_column(Price)
    yes_bid_size: Mapped[Decimal | None] = mapped_column(Count)
    yes_ask_size: Mapped[Decimal | None] = mapped_column(Count)
    last_price: Mapped[Decimal | None] = mapped_column(Price)
    volume: Mapped[Decimal | None] = mapped_column(Count)
    volume_24h: Mapped[Decimal | None] = mapped_column(Count)
    open_interest: Mapped[Decimal | None] = mapped_column(Count)
    minutes_to_close: Mapped[float] = mapped_column(Float)
    is_candidate: Mapped[bool] = mapped_column(Boolean)
    skip_reason: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[Any | None] = mapped_column(Json, nullable=True)  # no longer stored (storage); kept for old rows

    __table_args__ = (Index("ix_market_snapshots_ticker_fetched_at", "ticker", "fetched_at"),)


class OrderbookSnapshot(Base):
    """Full depth for one market. Bids only, as Kalshi returns them: [[price, count], ...] ascending.

    A YES ask at price p is a NO bid at (1 - p), so buying YES walks no_bids from the top.
    """

    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    yes_bids: Mapped[Any] = mapped_column(Json)
    no_bids: Mapped[Any] = mapped_column(Json)
    best_yes_bid: Mapped[Decimal | None] = mapped_column(Price)
    best_no_bid: Mapped[Decimal | None] = mapped_column(Price)

    __table_args__ = (Index("ix_orderbook_snapshots_ticker_fetched_at", "ticker", "fetched_at"),)


class ParsedRule(Base):
    """Structured reading of one market's rules. Cached by (ticker, inputs_hash, parser_version).

    status is 'ok' or 'needs_review'. event_check_ok is recomputed every parse run because it
    depends on the sibling markets of the same event. A market is tradable only if both pass.
    """

    __tablename__ = "parsed_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"), index=True)
    inputs_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(32))
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    location: Mapped[str | None] = mapped_column(Text)
    station_id: Mapped[str | None] = mapped_column(String(16))
    variable: Mapped[str | None] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(4))
    bucket_low: Mapped[float | None] = mapped_column(Float)
    bucket_high: Mapped[float | None] = mapped_column(Float)
    inclusive_low: Mapped[bool | None] = mapped_column(Boolean)
    inclusive_high: Mapped[bool | None] = mapped_column(Boolean)
    resolution_source: Mapped[str | None] = mapped_column(Text)
    resolution_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    event_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    event_check_note: Mapped[str | None] = mapped_column(Text)
    review_resolution: Mapped[str | None] = mapped_column(Text)  # filled by a human after review

    __table_args__ = (
        UniqueConstraint("ticker", "inputs_hash", "parser_version", name="uq_parsed_rules_cache_key"),
    )


class WeatherForecastRaw(Base):
    """One raw API response, stored as received. source: open_meteo_ensemble | open_meteo_previous_runs | nws."""

    __tablename__ = "weather_forecasts_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    station: Mapped[str] = mapped_column(String(16))  # CLI code, e.g. CLINYC
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    params: Mapped[Any] = mapped_column(Json)
    response: Mapped[Any] = mapped_column(Json)

    __table_args__ = (Index("ix_weather_raw_station_source_fetched", "station", "source", "fetched_at"),)


class WeatherForecastHigh(Base):
    """Parsed daily high for one member of one model for one climate day. member 0 = control/deterministic."""

    __tablename__ = "weather_forecast_highs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_id: Mapped[int] = mapped_column(ForeignKey("weather_forecasts_raw.id"), index=True)
    station: Mapped[str] = mapped_column(String(16))
    target_date: Mapped[date] = mapped_column(Date)
    model: Mapped[str] = mapped_column(String(48))
    member: Mapped[int] = mapped_column(Integer)
    high_f: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_weather_highs_station_date_fetched", "station", "target_date", "fetched_at"),)


class WeatherObservation(Base):
    """Observed daily high from the NWS climate report (via IEM archive)."""

    __tablename__ = "weather_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station: Mapped[str] = mapped_column(String(16))
    obs_date: Mapped[date] = mapped_column(Date)
    high_f: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))
    product_id: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Append-only: a corrected report is a new row with a later fetched_at, so past decisions
    # can always be replayed with exactly what was known then.
    __table_args__ = (
        UniqueConstraint("station", "obs_date", "source", "high_f", name="uq_weather_obs"),
        Index("ix_weather_obs_station_date_fetched", "station", "obs_date", "fetched_at"),
    )


class Forecast(Base):
    """Our probability for one market at one decision time, logged before the outcome is known."""

    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"))
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_version: Mapped[str] = mapped_column(String(32))
    inputs_hash: Mapped[str] = mapped_column(String(64))
    probability: Mapped[float] = mapped_column(Float)
    market_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("market_snapshots.id"))
    yes_bid: Mapped[Decimal | None] = mapped_column(Price)
    yes_ask: Mapped[Decimal | None] = mapped_column(Price)
    n_members: Mapped[int] = mapped_column(Integer)
    details: Mapped[Any] = mapped_column(Json)  # bias per model, inflation, member counts, data timestamps

    __table_args__ = (Index("ix_forecasts_ticker_decided_at", "ticker", "decided_at"),)


class ShadowOrder(Base):
    """One simulated buy, filled by walking a stored order book. Unfilled attempts are kept too."""

    __tablename__ = "shadow_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("forecasts.id"))
    orderbook_snapshot_id: Mapped[int] = mapped_column(ForeignKey("orderbook_snapshots.id"))
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"), index=True)
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    side: Mapped[str] = mapped_column(String(3))  # yes | no
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    probability: Mapped[float] = mapped_column(Float)  # model probability that this side wins
    limit_price: Mapped[Decimal] = mapped_column(Price)
    intended_contracts: Mapped[Decimal] = mapped_column(Count)
    filled_contracts: Mapped[Decimal] = mapped_column(Count)
    avg_price: Mapped[Decimal | None] = mapped_column(Price)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6))  # contracts x price + fee
    edge_per_contract: Mapped[float | None] = mapped_column(Float)  # net of fees, at the realised fill
    status: Mapped[str] = mapped_column(String(16))  # filled | partial | unfilled
    fills: Mapped[Any] = mapped_column(Json)  # [[price, contracts], ...]


class Position(Base):
    """Net holding in one side of one market. Cost includes fees."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"))
    event_ticker: Mapped[str] = mapped_column(String(128), index=True)
    side: Mapped[str] = mapped_column(String(3))
    contracts: Mapped[Decimal] = mapped_column(Count)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    fees: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    status: Mapped[str] = mapped_column(String(16), index=True)  # open | settled
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payout: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    __table_args__ = (UniqueConstraint("ticker", "side", name="uq_positions_ticker_side"),)


class BankrollSnapshot(Base):
    """Shadow account state after each run. equity = cash + open positions at cost."""

    __tablename__ = "bankroll_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    open_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    equity: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    drawdown_pct: Mapped[float] = mapped_column(Float)
    kill_switch: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)


class Settlement(Base):
    """Final outcome of one market, as published by Kalshi."""

    __tablename__ = "settlements"

    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"), primary_key=True)
    result: Mapped[str] = mapped_column(String(8))  # yes | no
    settlement_value: Mapped[Decimal] = mapped_column(Price)  # YES payout per contract
    expiration_value: Mapped[str | None] = mapped_column(String(32))  # the settled temperature, e.g. "61.00"
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))


class ApiCost(Base):
    """Usage and dollar cost of external APIs, per run. Free APIs are logged at $0 so quota use is visible."""

    __tablename__ = "api_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(64))
    calls: Mapped[int] = mapped_column(Integer)
    quota_units: Mapped[float] = mapped_column(Float)  # provider's own accounting, e.g. Open-Meteo x-ratelimit-cost
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
