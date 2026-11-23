"""Scoring: is the model a better forecaster than the market?

Unit of scoring: one row per (market, model version), using that version's LAST forecast
for the market. Every forecast is made before its climate day starts (weather_model v1
rule), so this is the most informed pre-event forecast. The market's probability is the
YES mid at that same moment (stored on the forecast row), so both are judged on the same
information time. Rows without both a bid and an ask have no market probability and are
counted but excluded from the comparison.

Bootstrap: the ranges in one event are mutually exclusive and strongly correlated, so we
resample whole events (cluster bootstrap), not individual markets.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ApiCost, Forecast, Position, Settlement, ShadowOrder

CLIP = 1e-3  # log loss is infinite at 0/1; market mids of 0 or 1 happen


@dataclass(frozen=True)
class Scored:
    ticker: str
    event: str
    model_version: str
    p_model: float
    p_market: float | None
    outcome: int


def scored_rows(session: Session) -> list[Scored]:
    last = (
        select(Forecast.ticker, Forecast.model_version, func.max(Forecast.decided_at).label("decided_at"))
        .group_by(Forecast.ticker, Forecast.model_version)
        .subquery()
    )
    rows = session.execute(
        select(Forecast, Settlement.result)
        .join(last, (Forecast.ticker == last.c.ticker) & (Forecast.model_version == last.c.model_version)
              & (Forecast.decided_at == last.c.decided_at))
        .join(Settlement, Settlement.ticker == Forecast.ticker)
    ).all()
    out = []
    for f, result in rows:
        mid = None
        if f.yes_bid is not None and f.yes_ask is not None:
            mid = float((f.yes_bid + f.yes_ask) / 2)
        out.append(Scored(f.ticker, f.event_ticker, f.model_version, f.probability, mid, 1 if result == "yes" else 0))
    return out


def brier(ps: list[float], ys: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def log_loss(ps: list[float], ys: list[int]) -> float:
    total = 0.0
    for p, y in zip(ps, ys):
        p = min(max(p, CLIP), 1 - CLIP)
        total -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return total / len(ps)


def calibration(ps: list[float], ys: list[int], bins: int = 10) -> list[dict[str, float | int | str]]:
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(ps) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            table.append({
                "bin": f"{lo:.0%}-{hi:.0%}", "n": len(idx),
                "mean_predicted": sum(ps[i] for i in idx) / len(idx),
                "observed_freq": sum(ys[i] for i in idx) / len(idx),
            })
    return table


def bootstrap_brier_gap(rows: list[Scored], n_boot: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    """(market Brier - model Brier, 2.5th pct, 97.5th pct). Positive = model better. Resamples events."""
    events: dict[str, list[Scored]] = {}
    for r in rows:
        events.setdefault(r.event, []).append(r)
    keys = list(events)

    def gap(sample: list[Scored]) -> float:
        ys = [r.outcome for r in sample]
        return brier([r.p_market for r in sample], ys) - brier([r.p_model for r in sample], ys)  # type: ignore[misc]

    point = gap(rows)
    rng = random.Random(seed)
    gaps = sorted(gap([r for k in rng.choices(keys, k=len(keys)) for r in events[k]]) for _ in range(n_boot))
    return point, gaps[int(0.025 * n_boot)], gaps[int(0.975 * n_boot) - 1]


@dataclass
class VersionScore:
    model_version: str
    n_resolved: int
    n_compared: int
    n_events: int
    brier_model: float | None = None
    brier_market: float | None = None
    logloss_model: float | None = None
    logloss_market: float | None = None
    gap: float | None = None  # market - model; positive = model better
    gap_ci: tuple[float, float] | None = None
    calibration_model: list[dict[str, float | int | str]] = field(default_factory=list)
    calibration_market: list[dict[str, float | int | str]] = field(default_factory=list)


def score_versions(session: Session) -> list[VersionScore]:
    rows = scored_rows(session)
    out = []
    for version in sorted({r.model_version for r in rows}):
        vr = [r for r in rows if r.model_version == version]
        cmp = [r for r in vr if r.p_market is not None]
        s = VersionScore(version, len(vr), len(cmp), len({r.event for r in cmp}))
        if cmp:
            ys = [r.outcome for r in cmp]
            pm, pk = [r.p_model for r in cmp], [r.p_market for r in cmp]
            s.brier_model, s.brier_market = brier(pm, ys), brier(pk, ys)  # type: ignore[arg-type]
            s.logloss_model, s.logloss_market = log_loss(pm, ys), log_loss(pk, ys)  # type: ignore[arg-type]
            s.calibration_model, s.calibration_market = calibration(pm, ys), calibration(pk, ys)  # type: ignore[arg-type]
            if s.n_events >= 2:
                point, lo, hi = bootstrap_brier_gap(cmp)
                s.gap, s.gap_ci = point, (lo, hi)
            else:
                s.gap = s.brier_market - s.brier_model
        out.append(s)
    return out


@dataclass
class PnL:
    settled_positions: int
    open_positions: int
    open_cost: Decimal
    gross: Decimal  # payout - contract cost, before fees
    fees: Decimal
    net_of_fees: Decimal
    api_costs: Decimal
    net_of_costs: Decimal
    filled_orders: int


def pnl(session: Session) -> PnL:
    settled = list(session.scalars(select(Position).where(Position.status == "settled")))
    open_ = list(session.scalars(select(Position).where(Position.status == "open")))
    net = sum((p.pnl or Decimal(0) for p in settled), Decimal(0))
    fees = sum((p.fees for p in settled), Decimal(0))
    api = Decimal(session.scalar(select(func.coalesce(func.sum(ApiCost.cost_usd), 0))) or 0)
    filled = session.scalar(select(func.count()).select_from(ShadowOrder).where(ShadowOrder.filled_contracts > 0)) or 0
    return PnL(
        settled_positions=len(settled), open_positions=len(open_),
        open_cost=sum((p.cost for p in open_), Decimal(0)),
        gross=net + fees, fees=fees, net_of_fees=net, api_costs=api, net_of_costs=net - api, filled_orders=filled,
    )
