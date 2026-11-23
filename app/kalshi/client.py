"""Kalshi REST client: public market data.

Endpoints and fields checked against docs/vendor/kalshi_openapi.yaml (v3.37.0):
- GET /series?category=&tags=        -> {"series": [...]}            (not paginated)
- GET /markets?series_ticker=&status= -> {"markets": [...], "cursor"} (stop when cursor is empty)
- GET /markets/orderbooks?tickers=... -> {"orderbooks": [{"ticker", "orderbook_fp"}]}, max 100 tickers

There are deliberately no order methods here. Order placement lives in execution/demo.py
and execution/live.py, so shadow mode has no code path that can send an order.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}
ORDERBOOKS_MAX_TICKERS = 100


class KalshiError(RuntimeError):
    pass


class KalshiClient:
    def __init__(
        self,
        base_url: str,
        *,
        max_requests_per_second: float = 5.0,
        max_retries: int = 5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=30, transport=transport)
        self._min_interval = 1.0 / max_requests_per_second
        self._max_retries = max_retries
        self._sleep = sleep
        self._last_request = 0.0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KalshiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, path: str, params: Any = None) -> dict[str, Any]:
        """GET with throttling and exponential backoff on 429/5xx and network errors."""
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            self._last_request = time.monotonic()
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise KalshiError(f"GET {path} failed after retries: {exc}") from exc
                self._sleep(2**attempt)
                continue
            if resp.status_code in RETRY_STATUSES and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After")
                self._sleep(float(retry_after) if retry_after else 2**attempt)
                continue
            if resp.status_code != 200:
                raise KalshiError(f"GET {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise KalshiError(f"GET {path} exhausted retries")  # unreachable; keeps type checkers happy

    def list_series(self, category: str, tag: str | None = None) -> list[dict[str, Any]]:
        params = {"category": category}
        if tag:
            params["tags"] = tag
        return self.get("/series", params)["series"]

    def get_series(self, series_ticker: str) -> dict[str, Any]:
        return self.get(f"/series/{series_ticker}")["series"]

    def iter_markets(self, **filters: str) -> Iterator[dict[str, Any]]:
        cursor = ""
        seen: set[str] = set()
        while True:
            params = {**filters, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            page = self.get("/markets", params)
            for market in page.get("markets", []):
                if market["ticker"] not in seen:  # docs: dedupe by ticker across pages
                    seen.add(market["ticker"])
                    yield market
            cursor = page.get("cursor") or ""
            if not cursor:
                return

    def get_orderbooks(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """Return {ticker: orderbook_fp}. Chunks requests at the 100-ticker API limit."""
        books: dict[str, dict[str, Any]] = {}
        for i in range(0, len(tickers), ORDERBOOKS_MAX_TICKERS):
            chunk = tickers[i : i + ORDERBOOKS_MAX_TICKERS]
            resp = self.get("/markets/orderbooks", [("tickers", t) for t in chunk])
            for entry in resp["orderbooks"]:
                books[entry["ticker"]] = entry["orderbook_fp"]
        return books
