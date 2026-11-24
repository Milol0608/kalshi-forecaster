"""Daily summary. Run: uv run python -m app.report

Says plainly when the model is worse than the market. Never hides a bad number.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, check_live_gate
from app.db.models import ApiCost, BankrollSnapshot, Forecast, Market, Position, Run, Settlement
from app.metrics.scoring import VersionScore, pnl, score_versions

MONTHLY_COST_WARNING = Decimal("10")


def verdict(s: VersionScore) -> str:
    if s.gap is None or s.n_compared == 0:
        return "No resolved forecasts with a market price yet: nothing to judge."
    if s.gap_ci is None:
        return "Only one event resolved: far too few to judge."
    lo, hi = s.gap_ci
    if hi < 0:
        return "MODEL IS WORSE THAN THE MARKET (whole confidence interval below zero)."
    if lo > 0:
        return "Model beats the market (whole confidence interval above zero)."
    if s.gap < 0:
        return "Model is behind the market so far; the interval still includes zero, so it's not settled yet."
    return "Model is ahead of the market so far, but the interval includes zero: not proven."


def schedule_health(session: Session, now: datetime, max_gap_hours: float = 2.0) -> list[str]:
    """How regularly the hourly pipeline actually ran. The trigger lives outside this repo
    (cron-job.org calling GitHub), so a stopped trigger only shows up as missing runs."""
    starts = sorted(session.scalars(select(Run.started_at).where(
        Run.job == "scan", Run.started_at >= now - timedelta(days=1))))
    if not starts:
        return ["  ATTENTION: no pipeline run in the last 24h; check the cron-job.org trigger."]
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip([now - timedelta(days=1)] + starts, starts + [now])]
    hours = len({t.replace(minute=0, second=0, microsecond=0) for t in starts})
    out = [f"  pipeline ran in {hours} of the last 24 hours; longest gap {max(gaps):.1f} h"]
    if max(gaps) > max_gap_hours:
        out.append(f"  ATTENTION: a gap over {max_gap_hours:g} h; check the cron-job.org trigger's history.")
    return out


def build_report(session: Session, settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [f"KALSHI FORECASTER REPORT  {now:%Y-%m-%d %H:%M} UTC   mode={settings.mode.value}", "=" * 72]

    lines.append("\nFORECAST SKILL (Brier: lower is better; market = YES mid at forecast time)")
    scores = score_versions(session)
    if not scores:
        lines.append("  No forecasts have resolved yet.")
    for s in scores:
        lines.append(f"\n  model {s.model_version}: {s.n_resolved} resolved, {s.n_compared} with a market price, "
                     f"{s.n_events} events")
        if s.brier_model is not None:
            lines.append(f"    Brier   model {s.brier_model:.4f}   market {s.brier_market:.4f}")
            lines.append(f"    LogLoss model {s.logloss_model:.4f}   market {s.logloss_market:.4f}")
            ci = f"  95% CI [{s.gap_ci[0]:+.4f}, {s.gap_ci[1]:+.4f}]" if s.gap_ci else ""
            lines.append(f"    Brier gap (market - model, + = model better): {s.gap:+.4f}{ci}")
        lines.append(f"    -> {verdict(s)}")
        if s.calibration_model:
            lines.append("    Calibration     model: predicted -> observed (n)    market: predicted -> observed (n)")
            market = {c["bin"]: c for c in s.calibration_market}
            bins = sorted({c["bin"] for c in s.calibration_model} | set(market), key=lambda b: float(str(b).split("%")[0]))
            model = {c["bin"]: c for c in s.calibration_model}
            for b in bins:
                fmt = lambda c: f"{c['mean_predicted']:.2f} -> {c['observed_freq']:.2f} ({c['n']})" if c else "-"  # noqa: E731
                lines.append(f"      {b:>9}   {fmt(model.get(b)):<24} {fmt(market.get(b))}")

    p = pnl(session)
    last = session.scalars(select(BankrollSnapshot).order_by(BankrollSnapshot.at.desc()).limit(1)).first()
    lines.append("\nSHADOW P&L (simulated, no real money)")
    lines.append(f"  filled orders: {p.filled_orders}   settled positions: {p.settled_positions}   "
                 f"open positions: {p.open_positions} (${p.open_cost:.2f} at cost)")
    for pos, mkt, st in session.execute(
            select(Position, Market, Settlement).join(Market, Market.ticker == Position.ticker, isouter=True)
            .join(Settlement, Settlement.ticker == Position.ticker, isouter=True)
            .where(Position.status == "open").order_by(Position.opened_at)).all():
        lines.append(f"    open: {pos.ticker} {pos.side} x{pos.contracts} opened {pos.opened_at:%Y-%m-%d %H:%M}  "
                     f"closes {mkt.close_time:%Y-%m-%d %H:%M} status {mkt.status}  " if mkt else
                     f"    open: {pos.ticker} (no market row)  ")
        lines[-1] += f"result {st.result if st else 'none yet'}"
    lines.append(f"  gross (before fees):   ${p.gross:+.2f}")
    lines.append(f"  fees:                  ${-p.fees:+.2f}")
    lines.append(f"  net of fees:           ${p.net_of_fees:+.2f}")
    lines.append(f"  API/LLM costs:         ${-p.api_costs:+.2f}")
    lines.append(f"  net of all costs:      ${p.net_of_costs:+.2f}")
    if last:
        lines.append(f"  bankroll: equity ${last.equity:.2f} (cash ${last.cash:.2f})   peak ${last.peak_equity:.2f}   "
                     f"drawdown {last.drawdown_pct:.1%}   kill switch {'ON' if last.kill_switch else 'off'}")

    month = now - timedelta(days=30)
    cost_30d = Decimal(session.scalar(select(func.coalesce(func.sum(ApiCost.cost_usd), 0)).where(ApiCost.at >= month)) or 0)
    units_day = session.execute(
        select(ApiCost.provider, func.sum(ApiCost.quota_units)).where(ApiCost.at >= now - timedelta(days=1)).group_by(ApiCost.provider)
    ).all()
    lines.append("\nCOSTS AND QUOTAS")
    lines.append(f"  API spend, last 30 days: ${cost_30d:.2f}"
                 + ("   WARNING: above $10/month" if cost_30d > MONTHLY_COST_WARNING else ""))
    for provider, units in units_day:
        limit = " of 10,000/day free limit" if provider == "open-meteo" else ""
        lines.append(f"  {provider}: {units:.0f} quota units in the last 24h{limit}")

    runs = session.execute(
        select(Run.job, Run.status, func.count()).where(Run.started_at >= now - timedelta(days=1)).group_by(Run.job, Run.status)
    ).all()
    lines.append("\nRUNS (last 24h)")
    for job, status, n in sorted(runs):
        lines.append(f"  {job:<10} {status:<8} {n}")
    failed = [r for r in runs if r[1] == "failed"]
    if failed:
        lines.append("  ATTENTION: some runs failed; see the runs table `error` column.")
    lines.extend(schedule_health(session, now))
    pending = session.scalar(select(func.count()).select_from(Forecast).where(Forecast.decided_at >= now - timedelta(days=1)))
    lines.append(f"  forecasts logged in last 24h: {pending}")

    lines.append(f"\nLIVE TRADING: {'LOCKED' if check_live_gate(settings) else 'UNLOCKED'}")
    return "\n".join(lines)


def main() -> None:
    from app.config import get_settings
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        print(build_report(session, get_settings()))


if __name__ == "__main__":
    main()
