"""ORM models.

Each milestone adds its own tables
(Section 6 of the build spec) in its own migration, so schemas are shaped by real
API data instead of guessed up front.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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
    raw: Mapped[Any] = mapped_column(Json)

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
