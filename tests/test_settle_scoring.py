from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import BankrollSnapshot, Market, Position, Run, Settlement
from app.kalshi.client import KalshiClient
from app.metrics.scoring import Scored, bootstrap_brier_gap, brier, calibration, log_loss
from app.report import verdict
from app.metrics.scoring import VersionScore
from app.settle.resolver import resolve

UTC = timezone.utc
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


# --- scoring math ------------------------------------------------------------

def test_brier_and_log_loss() -> None:
    assert brier([1.0, 0.0], [1, 0]) == 0
    assert brier([0.5, 0.5], [1, 0]) == 0.25
    assert log_loss([0.5], [1]) == pytest.approx(0.693147, abs=1e-6)
    assert log_loss([0.0], [1]) == pytest.approx(6.907755, abs=1e-6)  # clipped, not infinite


def test_calibration_bins() -> None:
    table = calibration([0.05, 0.08, 0.95, 1.0], [0, 1, 1, 1])
    assert [(r["bin"], r["n"], r["observed_freq"]) for r in table] == [("0%-10%", 2, 0.5), ("90%-100%", 2, 1.0)]


def test_bootstrap_detects_a_clearly_better_model() -> None:
    rows = []
    for e in range(40):  # model knows the answer; market says 50/50
        for b in range(2):
            y = 1 if b == e % 2 else 0
            rows.append(Scored(f"T{e}{b}", f"E{e}", "v", 0.9 if y else 0.1, 0.5, y))
    point, lo, hi = bootstrap_brier_gap(rows)
    assert point == pytest.approx(0.25 - 0.01)
    assert lo > 0


def test_verdict_says_plainly_when_model_is_worse() -> None:
    s = VersionScore("v", 100, 100, 20, gap=-0.02, gap_ci=(-0.03, -0.01))
    assert "WORSE THAN THE MARKET" in verdict(s)
    s = VersionScore("v", 100, 100, 20, gap=0.01, gap_ci=(-0.002, 0.02))
    assert "not proven" in verdict(s)
    assert "nothing to judge" in verdict(VersionScore("v", 0, 0, 0))


# --- settlement --------------------------------------------------------------

def settled_market(ticker: str, result: str) -> dict[str, Any]:
    return {"ticker": ticker, "status": "finalized", "result": result,
            "settlement_value_dollars": "1.0000" if result == "yes" else "0.0000",
            "expiration_value": "61.00", "settlement_ts": "2026-11-26T12:12:09Z"}


def client_returning(markets: list[dict[str, Any]]) -> KalshiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        wanted = set(request.url.params.get("tickers", "").split(","))
        return httpx.Response(200, json={"markets": [m for m in markets if m["ticker"] in wanted], "cursor": ""})
    return KalshiClient("https://x/trade-api/v2", transport=httpx.MockTransport(handler), sleep=lambda s: None)


def add_market(s: Session, ticker: str) -> None:
    s.add(Market(ticker=ticker, series_ticker="TS", event_ticker="TS-26NOV25", title="t", rules_primary="r",
                 rules_secondary="r", settlement_sources=[], close_time=NOW - timedelta(hours=8), status="active",
                 first_seen_at=NOW, last_seen_at=NOW))


def add_position(s: Session, ticker: str, side: str, contracts: str, cost: str) -> Position:
    p = Position(ticker=ticker, event_ticker="TS-26NOV25", side=side, contracts=D(contracts), cost=D(cost),
                 fees=D("0.10"), status="open", opened_at=NOW - timedelta(days=1), updated_at=NOW - timedelta(days=1))
    s.add(p)
    return p


def test_settles_yes_and_no_positions(db_session: Session, settings: Settings) -> None:
    for t in ("TS-A", "TS-B", "TS-C"):
        add_market(db_session, t)
    db_session.flush()
    win_yes = add_position(db_session, "TS-A", "yes", "10", "4.00")   # A resolves yes: pays 10
    lose_yes = add_position(db_session, "TS-B", "yes", "5", "1.00")   # B resolves no: pays 0
    win_no = add_position(db_session, "TS-B", "no", "4", "3.00")      # NO on B: pays 4
    db_session.flush()

    r = resolve(db_session, client_returning([settled_market("TS-A", "yes"), settled_market("TS-B", "no")]),
                settings, clock=lambda: NOW)
    assert (r.newly_settled, r.positions_settled) == (2, 3)
    assert (win_yes.payout, win_yes.pnl) == (D(10), D(6))
    assert (lose_yes.payout, lose_yes.pnl) == (D(0), D(-1))
    assert (win_no.payout, win_no.pnl) == (D(4), D(1))
    assert r.pnl == D(6)
    assert db_session.get(Settlement, "TS-C") is None  # no result from Kalshi yet: untouched
    assert db_session.get(Market, "TS-A").status == "finalized"  # type: ignore[union-attr]
    assert db_session.scalar(select(BankrollSnapshot).where(BankrollSnapshot.at == NOW)) is not None


def test_determined_but_not_final_is_not_settled(db_session: Session, settings: Settings) -> None:
    add_market(db_session, "TS-D")
    db_session.flush()
    pos = add_position(db_session, "TS-D", "yes", "1", "0.50")
    m = settled_market("TS-D", "yes") | {"status": "determined", "settlement_ts": None}
    r = resolve(db_session, client_returning([m]), settings, clock=lambda: NOW)
    assert r.newly_settled == 0 and pos.status == "open"
    assert db_session.get(Market, "TS-D").status == "determined"  # type: ignore[union-attr]


def test_resolving_twice_does_not_pay_twice(db_session: Session, settings: Settings) -> None:
    add_market(db_session, "TS-E")
    db_session.flush()
    pos = add_position(db_session, "TS-E", "yes", "2", "1.00")
    client = client_returning([settled_market("TS-E", "yes")])
    resolve(db_session, client, settings, clock=lambda: NOW)
    second = resolve(db_session, client, settings, clock=lambda: NOW)
    assert second.positions_settled == 0 and pos.payout == D(2)


def test_stranded_position_settles_from_an_earlier_result(db_session: Session, settings: Settings) -> None:
    """The result was recorded earlier (a cancelled run, or a copied database) and the market already
    looks final, but the position is still open: it must settle anyway."""
    add_market(db_session, "TS-F")
    db_session.flush()
    db_session.get(Market, "TS-F").status = "finalized"  # type: ignore[union-attr]
    db_session.add(Settlement(ticker="TS-F", result="no", settlement_value=D(0), expiration_value="61.00",
                              settled_at=NOW - timedelta(hours=2), fetched_at=NOW - timedelta(hours=1),
                              status="finalized"))
    pos = add_position(db_session, "TS-F", "no", "3", "2.00")
    db_session.flush()
    r = resolve(db_session, client_returning([settled_market("TS-F", "no")]), settings, clock=lambda: NOW)
    assert (r.newly_settled, r.positions_settled) == (0, 1)
    assert pos.status == "settled" and pos.payout == D(3) and pos.pnl == D(1)


def test_final_status_without_result_is_rechecked_while_a_position_is_open(
        db_session: Session, settings: Settings) -> None:
    add_market(db_session, "TS-G")
    db_session.flush()
    db_session.get(Market, "TS-G").status = "finalized"  # type: ignore[union-attr]
    pos = add_position(db_session, "TS-G", "yes", "1", "0.40")
    db_session.flush()
    r = resolve(db_session, client_returning([settled_market("TS-G", "yes")]), settings, clock=lambda: NOW)
    assert r.checked == 1 and pos.status == "settled" and pos.payout == D(1)


# --- scheduler -----------------------------------------------------------------

def test_failing_step_is_recorded_and_does_not_raise(settings: Settings) -> None:
    from app.db.session import get_engine
    from app.jobs.schedule import step

    def boom(session: Session, run_id: int) -> str:
        raise RuntimeError("simulated outage")

    assert step("testfail", boom, settings) is False
    assert step("testok", lambda s, r: "fine", settings) is True
    with Session(get_engine()) as s:
        failed = s.scalars(select(Run).where(Run.job == "testfail").order_by(Run.id.desc())).first()
        assert failed is not None and failed.status == "failed" and "simulated outage" in (failed.error or "")
        s.query(Run).filter(Run.job.in_(["testfail", "testok"])).delete()
        s.commit()
