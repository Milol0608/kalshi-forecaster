from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Mode, Settings
from app.db.models import Forecast, Market, MarketSnapshot, OrderbookSnapshot, Position, ShadowOrder
from app.execution.shadow import Plan, plan_side, run_shadow, walk_book
from app.forecast.nbm_blend import MODEL_VERSION  # the model the shadow trader acts on by default
from app.strategy.edge import asks_for, edge_at, limit_price
from app.strategy.risk import Account, kill_switch_on, max_new_spend
from app.strategy.sizing import kelly_fraction, kelly_spend

UTC = timezone.utc

# Synthetic book. YES asks come from NO bids: NO bid 0.62 -> YES ask 0.38.
YES_BIDS = [["0.30", "50.00"], ["0.34", "20.00"]]
NO_BIDS = [["0.55", "100.00"], ["0.60", "10.00"], ["0.62", "5.00"]]


def acct(equity: str = "100") -> Account:
    return Account(cash=D(equity), open_cost=D(0), peak_equity=D(equity))


# --- edge --------------------------------------------------------------------

def test_asks_are_derived_from_opposite_bids_cheapest_first() -> None:
    assert asks_for("yes", YES_BIDS, NO_BIDS) == [(D("0.38"), D(5)), (D("0.40"), D(10)), (D("0.45"), D(100))]
    assert asks_for("no", YES_BIDS, NO_BIDS) == [(D("0.66"), D(20)), (D("0.70"), D(50))]


def test_edge_is_net_of_fee() -> None:
    # 0.50 - 0.38 - 0.07*0.38*0.62
    assert edge_at(0.50, D("0.38")) == D("0.50") - D("0.38") - D("0.016492")


def test_limit_is_highest_price_with_edge() -> None:
    asks = asks_for("yes", YES_BIDS, NO_BIDS)
    assert limit_price(0.47, asks, D("0.03")) == D("0.40")  # 0.45 leaves < 3c after fee
    assert limit_price(0.40, asks, D("0.03")) is None


# --- sizing ------------------------------------------------------------------

def test_kelly() -> None:
    assert kelly_fraction(0.6, D("0.5")) == D("0.2")
    assert kelly_fraction(0.4, D("0.5")) == 0
    assert kelly_spend(0.6, D("0.5"), D(100), 0.25) == D("5.0")


# --- risk --------------------------------------------------------------------

def test_caps_take_the_tightest_limit(settings: Settings) -> None:
    a = acct()
    assert max_new_spend(a, "T", "E", "yes", settings) == D("5")  # 5% per market
    a.record("T", "E", "yes", D("4"))
    assert max_new_spend(a, "T", "E", "yes", settings) == D("1.0")  # equity still 100 (cost basis)
    a.record("T2", "E", "yes", D("5"))
    assert max_new_spend(a, "T3", "E", "yes", settings) == D("1.0")  # 10% per event: 10 - 9
    for i in range(4):
        a.record(f"X{i}", f"E{i}", "yes", D("4"))
    assert max_new_spend(a, "Y", "EY", "yes", settings) == D("0")  # 25% total: 9 + 16 = 25


def test_kill_switch_at_30pct_drawdown(settings: Settings) -> None:
    a = Account(cash=D("71"), open_cost=D(0), peak_equity=D("100"))
    assert not kill_switch_on(a, settings)
    a.cash = D("70")
    assert kill_switch_on(a, settings)


# --- fills -------------------------------------------------------------------

def test_walk_never_exceeds_limit_or_depth() -> None:
    asks = [(D("0.38"), D(5)), (D("0.40"), D(10)), (D("0.45"), D(100))]
    assert walk_book(asks, D("0.40"), D(8)) == [(D("0.38"), D(5)), (D("0.40"), D(3))]
    assert walk_book(asks, D("0.40"), D(50)) == [(D("0.38"), D(5)), (D("0.40"), D(10))]  # partial
    assert walk_book(asks, D("0.37"), D(50)) == []  # nothing at or under the limit


def test_plan_fills_at_ask_and_checks_edge_after_rounded_fee(settings: Settings) -> None:
    plan = plan_side("yes", 0.55, asks_for("yes", YES_BIDS, NO_BIDS), acct(), "T", "E", settings)
    assert isinstance(plan, Plan)
    assert plan.fills[0][0] == D("0.38")  # bought at the ask, not the mid (0.36)
    assert plan.total_cost <= D("5")  # 5% position cap
    assert plan.edge_per_contract is not None and plan.edge_per_contract > settings.min_edge


def test_tiny_edge_dies_to_fee_rounding(settings: Settings) -> None:
    # One contract at 1c with p=0.045: unrounded edge 0.0343 > 3c, but the fee rounds to a full
    # cent, so real cost is 2c and edge is 2.5c: no trade.
    asks = [(D("0.01"), D(1))]
    assert plan_side("yes", 0.045, asks, acct(), "T", "E", settings) == "no size clears min edge after rounded fees"


def test_no_edge_returns_reason(settings: Settings) -> None:
    assert plan_side("yes", 0.30, asks_for("yes", YES_BIDS, NO_BIDS), acct(), "T", "E", settings) == "no edge"


# --- full run: no look-ahead, mode guard ---------------------------------------

AS_OF = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)


def seed(s: Session, probability: float, book_at: datetime) -> str:
    t = "TESTSH-26NOV25-B50.5"
    s.add(Market(ticker=t, series_ticker="TESTSH", event_ticker="TESTSH-26NOV25", title="t", rules_primary="r",
                 rules_secondary="r", settlement_sources=[], close_time=AS_OF + timedelta(days=1), status="active",
                 first_seen_at=AS_OF, last_seen_at=AS_OF))
    s.flush()
    snap = MarketSnapshot(ticker=t, fetched_at=AS_OF - timedelta(minutes=10), status="active", minutes_to_close=900,
                          is_candidate=True, raw={})
    s.add(snap)
    s.flush()
    s.add(Forecast(ticker=t, event_ticker="TESTSH-26NOV25", decided_at=AS_OF - timedelta(minutes=5),
                   model_version=MODEL_VERSION, inputs_hash="h", probability=probability, market_snapshot_id=snap.id,
                   n_members=82, details={}))
    s.add(OrderbookSnapshot(ticker=t, fetched_at=book_at, yes_bids=YES_BIDS, no_bids=NO_BIDS))
    s.flush()
    return t


@pytest.fixture
def clean_account(db_session: Session) -> Session:
    # Isolate from any real shadow history in the dev DB.
    for model in (ShadowOrder, Position):
        db_session.query(model).delete()
    db_session.flush()
    return db_session


def test_run_trades_and_records_everything(clean_account: Session, settings: Settings) -> None:
    t = seed(clean_account, 0.55, AS_OF - timedelta(minutes=10))
    r = run_shadow(clean_account, settings, AS_OF)
    assert len(r.orders) == 1
    o = r.orders[0]
    assert (o.ticker, o.side, o.status) == (t, "yes", "filled")
    assert o.orderbook_snapshot_id is not None and o.forecast_id is not None
    pos = clean_account.scalar(select(Position).where(Position.ticker == t))
    assert pos is not None and pos.contracts == o.filled_contracts and pos.cost == o.total_cost


def test_book_stamped_after_decision_is_never_used(clean_account: Session, settings: Settings) -> None:
    seed(clean_account, 0.55, AS_OF + timedelta(seconds=1))
    r = run_shadow(clean_account, settings, AS_OF)
    assert r.orders == [] and r.skipped["no fresh order book"] == 1


def test_stale_book_is_not_used(clean_account: Session, settings: Settings) -> None:
    seed(clean_account, 0.55, AS_OF - timedelta(minutes=settings.book_max_age_minutes + 1))
    assert run_shadow(clean_account, settings, AS_OF).skipped["no fresh order book"] == 1


def test_refuses_outside_shadow_mode(db_session: Session, settings: Settings) -> None:
    settings.mode = Mode.DEMO
    with pytest.raises(RuntimeError, match="refuses"):
        run_shadow(db_session, settings, AS_OF)


def test_limited_budget_goes_to_the_best_edge_not_the_first_ticker(clean_account: Session, settings: Settings) -> None:
    # Two markets; the total-exposure cap only has room for about one $5 position.
    settings.max_total_exposure_pct = 0.05
    weak = seed_named(clean_account, "TESTAA-26NOV25-B1", 0.46)    # sorts first, small edge
    strong = seed_named(clean_account, "TESTZZ-26NOV25-B1", 0.70)  # sorts last, big edge
    r = run_shadow(clean_account, settings, AS_OF)
    traded = {o.ticker for o in r.orders if o.filled_contracts > 0}
    assert strong in traded and weak not in traded


def seed_named(s: Session, ticker: str, probability: float) -> str:
    event = ticker.rsplit("-", 1)[0]
    s.add(Market(ticker=ticker, series_ticker=event.split("-")[0], event_ticker=event, title="t", rules_primary="r",
                 rules_secondary="r", settlement_sources=[], close_time=AS_OF + timedelta(days=1), status="active",
                 first_seen_at=AS_OF, last_seen_at=AS_OF))
    s.flush()
    snap = MarketSnapshot(ticker=ticker, fetched_at=AS_OF - timedelta(minutes=10), status="active",
                          minutes_to_close=900, is_candidate=True, raw={})
    s.add(snap)
    s.flush()
    s.add(Forecast(ticker=ticker, event_ticker=event, decided_at=AS_OF - timedelta(minutes=5), model_version=MODEL_VERSION,
                   inputs_hash="h", probability=probability, market_snapshot_id=snap.id, n_members=82, details={}))
    s.add(OrderbookSnapshot(ticker=ticker, fetched_at=AS_OF - timedelta(minutes=10), yes_bids=YES_BIDS, no_bids=NO_BIDS))
    s.flush()
    return ticker


def test_only_the_configured_model_is_traded(clean_account: Session, settings: Settings) -> None:
    seed(clean_account, 0.55, AS_OF - timedelta(minutes=10))
    other = settings.model_copy(update={"trade_model_version": "some-other-model"})
    assert run_shadow(clean_account, other, AS_OF).orders == []
