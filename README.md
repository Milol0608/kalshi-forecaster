# Kalshi Calibrated Forecaster

Forecasts Kalshi daily high-temperature markets and simulates trades against real order books.
**Shadow mode only.** Live trading is locked until Gate 1 passes (see `scripts/gate_check.py`, milestone 7).

## Run

```powershell
uv sync
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.api.main:app --reload
uv run pytest
```

Copy `.env.example` to `.env` first if you need to change anything. Defaults are safe (`MODE=shadow`).

## Modes

| MODE | Market data | Orders |
|---|---|---|
| `shadow` (default) | production | simulated in our DB, no order API calls |
| `demo` | demo env | real orders against Kalshi demo (mock funds) |
| `live` | production | real money; needs `LIVE_TRADING_CONFIRMED=yes-i-understand-real-money` **and** a `gate1_passed.json` under 30 days old |

## Where the build spec and Kalshi's docs differ

Checked against Kalshi's OpenAPI spec (v3.37.0, snapshot in `docs/vendor/kalshi_openapi.yaml`) on 2026-11-22.

- **Demo base URL.** The spec lists `https://external-api.demo.kalshi.co/trade-api/v2` as the demo Trade API server.
  The build spec's `https://demo-api.kalshi.co/trade-api/v2` is still listed as "also supported". We default to the first.
  Production is `https://external-api.kalshi.com/trade-api/v2` (`api.elections.kalshi.com` also supported).
- **Auth key type.** The docs now recommend **Ed25519** keys. RSA-2048 is still supported (RSA-PSS, SHA-256,
  MGF1-SHA-256, salt length = digest length). Signed message: `timestamp_ms + METHOD + path` without the query string.
  Headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`. Auth is built in milestone 7.

## Notes

- `DATABASE_URL` uses `127.0.0.1`, not `localhost`. On this Windows machine `localhost` tries IPv6 first,
  and Docker only publishes the port on IPv4, so each connection stalled before falling back.
