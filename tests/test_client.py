from __future__ import annotations

import httpx
import pytest

from app.kalshi.client import KalshiClient, KalshiError

BASE = "https://external-api.kalshi.com/trade-api/v2"


def client_with(handler, sleeps: list[float] | None = None) -> KalshiClient:  # type: ignore[no-untyped-def]
    record = sleeps if sleeps is not None else []
    return KalshiClient(BASE, transport=httpx.MockTransport(handler), sleep=record.append)


def test_follows_cursor_until_empty_and_dedupes() -> None:
    pages = {
        "": {"markets": [{"ticker": "A"}, {"ticker": "B"}], "cursor": "c1"},
        "c1": {"markets": [{"ticker": "B"}, {"ticker": "C"}], "cursor": "c2"},
        "c2": {"markets": [{"ticker": "D"}], "cursor": ""},
    }
    seen_cursors: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor", "")
        seen_cursors.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    tickers = [m["ticker"] for m in client_with(handler).iter_markets(series_ticker="X", status="open")]
    assert tickers == ["A", "B", "C", "D"]
    assert seen_cursors == ["", "c1", "c2"]


def test_retries_429_honouring_retry_after() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"series": []})

    sleeps: list[float] = []
    assert client_with(handler, sleeps).list_series("Climate and Weather") == []
    assert calls["n"] == 3
    assert sleeps.count(7.0) == 2


def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(KalshiError, match="503"):
        client_with(handler).list_series("x")


def test_does_not_retry_client_errors() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad"})

    with pytest.raises(KalshiError, match="400"):
        client_with(handler).list_series("x")
    assert calls["n"] == 1


def test_orderbooks_chunked_at_100() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tickers = request.url.params.get_list("tickers")
        sizes.append(len(tickers))
        return httpx.Response(
            200, json={"orderbooks": [{"ticker": t, "orderbook_fp": {"yes_dollars": [], "no_dollars": []}} for t in tickers]}
        )

    books = client_with(handler).get_orderbooks([f"T{i}" for i in range(250)])
    assert sizes == [100, 100, 50]
    assert len(books) == 250


def test_client_has_no_order_methods() -> None:
    """Shadow mode must have no code path to send an order through the market-data client."""
    names = [n for n in dir(KalshiClient) if not n.startswith("_")]
    assert not [n for n in names if any(w in n.lower() for w in ("order", "post", "put", "delete", "cancel"))
                and n != "get_orderbooks"]
