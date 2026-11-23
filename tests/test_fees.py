from __future__ import annotations

from decimal import Decimal as D

from app.kalshi.fees import model_fee, order_fee


def test_docs_worked_example() -> None:
    """docs.kalshi.com/getting_started/fee_rounding: 1 contract at $0.055."""
    assert model_fee(D("0.055"), D(1)) == D("0.00363825")
    # Balance changes by -$0.06, so trade fee + rounding fee = $0.005.
    assert order_fee([(D("0.055"), D(1))]) == D("0.005")


def test_fee_peaks_at_fifty_cents_and_is_symmetric() -> None:
    assert model_fee(D("0.50"), D(100)) == D("1.75")
    assert model_fee(D("0.30"), D(10)) == model_fee(D("0.70"), D(10))


def test_whole_cent_price_rounds_fee_up_to_next_cent() -> None:
    # 10 x 0.42: model fee 0.07*10*0.42*0.58 = 0.17052 -> 0.18
    assert order_fee([(D("0.42"), D(10))]) == D("0.18")


def test_tiny_orders_pay_a_full_cent() -> None:
    # 1 contract at 1c: model fee 0.000693, but the balance must move in whole cents.
    assert order_fee([(D("0.01"), D(1))]) == D("0.01")


def test_multiple_fills_charged_like_one_order() -> None:
    one = order_fee([(D("0.40"), D(5)), (D("0.41"), D(5))])
    # Total model fee 0.07*(5*.4*.6 + 5*.41*.59) = 0.168665 -> cost 4.05 + fee -> ceil 4.22
    assert one == D("0.17")
    # Charging each fill separately would round up twice: 0.09 + 0.09.
    assert one < order_fee([(D("0.40"), D(5))]) + order_fee([(D("0.41"), D(5))])


def test_no_fills_no_fee() -> None:
    assert order_fee([]) == 0


def test_multiplier_scales_fee() -> None:
    assert model_fee(D("0.5"), D(10), D(2)) == 2 * model_fee(D("0.5"), D(10))


# Every row of the "General Trading Fees Table" in Kalshi's fee schedule (effective July 7, 2026),
# docs/kalshi-fee-schedule.pdf page 4-5: (price, fee for 1 contract, fee for 100 contracts).
FEE_TABLE = [
    ("0.01", "0.01", "0.07"), ("0.05", "0.01", "0.34"), ("0.10", "0.01", "0.63"), ("0.15", "0.01", "0.90"),
    ("0.20", "0.02", "1.12"), ("0.25", "0.02", "1.32"), ("0.30", "0.02", "1.47"), ("0.35", "0.02", "1.60"),
    ("0.40", "0.02", "1.68"), ("0.45", "0.02", "1.74"), ("0.50", "0.02", "1.75"), ("0.55", "0.02", "1.74"),
    ("0.60", "0.02", "1.68"), ("0.65", "0.02", "1.60"), ("0.70", "0.02", "1.47"), ("0.75", "0.02", "1.32"),
    ("0.80", "0.02", "1.12"), ("0.85", "0.01", "0.90"), ("0.90", "0.01", "0.63"), ("0.95", "0.01", "0.34"),
    ("0.99", "0.01", "0.07"),
]


import pytest  # noqa: E402


@pytest.mark.parametrize("price, fee_1, fee_100", FEE_TABLE)
def test_matches_official_fee_table(price: str, fee_1: str, fee_100: str) -> None:
    assert order_fee([(D(price), D(1))]) == D(fee_1)
    assert order_fee([(D(price), D(100))]) == D(fee_100)
