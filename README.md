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

- **Settlement source (found 2026-11-23, milestone 2).** The spec assumed NWS station observations. Every
  active daily-high series lists **The Weather Company** (weather.com/kalshi) as its settlement source. The rules
  name a station code, e.g. "maximum temperature recorded at New York City (CLINYC) … according to The Weather
  Company". CLINYC is the NWS daily climate report for Central Park, so the *station* still looks like an NWS one,
  but the *published value* that settles the market comes from The Weather Company. The rules warn that its
  preliminary readings can differ by rounding. Milestone 4 must check observed highs against the settled values,
  not just against NWS data.

## Scanner

`uv run python -m app.ingest.scanner` runs one scan. Series are discovered by category "Climate and Weather",
tag "Daily temperature", frequency `daily`, with a title that says high/max and not low/min.
Set `SERIES_TICKERS` to override. On 2026-11-23 that found 24 cities with open markets: 12 markets each, covering
today's and tomorrow's events (6 temperature ranges per day).
Every open market gets a `market_snapshots` row. Only candidates (active, 24h volume ≥ `MIN_VOLUME_24H`,
≥ `MIN_MINUTES_TO_CLOSE` to close, something to buy) get an `orderbook_snapshots` row.

## Notes

- `DATABASE_URL` uses `127.0.0.1`, not `localhost`. On this Windows machine `localhost` tries IPv6 first,
  and Docker only publishes the port on IPv4, so each connection stalled before falling back.

## Rules parser

`uv run python -m app.ingest.rules_parser` parses every active market's rules (regex only, ADR 0003).
Each parse is checked against Kalshi's own `strike_type`/`floor_strike`/`cap_strike`, the title, the YES
subtitle and the event-ticker date. Any mismatch, or wording the regex doesn't fully match, gives
`needs_review`, and that market is never traded. Each event's buckets must also cover every whole-degree reading
exactly once (`event_check_ok`). Results are cached by (ticker, hash of every input field, parser version).

Boundaries (readings are whole °F): "between 49-50" is 49–50 inclusive; "less than 49" is 48 or below;
"greater than 56" is 57 or above. Station codes are NWS climate-report IDs. Watch out: Chicago is Midway (CLIMDW),
Dallas is DFW (CLIDFW), DC is Reagan National (CLIDCA).

## Weather evidence and forecast (milestone 4)

`uv run python -m app.forecast.weather_model` fetches weather, then writes one forecast per market.

- **Stations:** `data/stations.json`, built by `uv run python -m scripts.build_stations`. Each CLI code maps to K+code,
  confirmed by IEM reports carrying the same product code. Coordinates come from api.weather.gov.
  Houston is Hobby (KHOU), NYC is Central Park (KNYC).
- **Observed highs:** NWS climate reports via the IEM archive. These matched Kalshi's settled winning range on 270/270
  recent days across 6 cities. Append-only: a corrected report becomes a new row.
- **Climate day:** midnight to midnight *local standard time* (NWS convention), even during daylight saving.
- **Forecast:** Open-Meteo ensembles, GEFS 0.25 (31 members) + ECMWF IFS 0.25 (51), hourly, max over the climate day.
  Fetched at most every `WEATHER_FETCH_MIN_INTERVAL_MINUTES` (180).
- **Bias:** mean(observed − day-ahead deterministic forecast) over 30 days, per station and model (Open-Meteo
  previous-runs API). Applied to the matching ensemble. *Assumption:* deterministic-run bias stands in for ensemble bias.
- **Model `ens-v1.1`:** bias-correct, inflate spread to each station's recent error (ADR 0004), round to whole degrees,
  count members per range, Laplace smoothing. Only for days whose climate day hasn't started yet.
- **NWS forecast:** stored as a reference only, not used as an input.
- **Open-Meteo terms:** the free API is for non-commercial use, < 10,000 calls/day (we use ~1,600). Personal shadow
  research reads as non-commercial. Trading real money for profit may not. Decide before going live: a paid plan, or
  NOAA's public-domain GEFS files.

## Strategy and shadow execution (milestone 5)

`uv run python -m app.execution.shadow` simulates buys for the freshest forecasts (≤ 60 min old) against the freshest
order book (≤ 45 min old). It refuses to run unless `MODE=shadow`, and it never calls an order API.

- **Fees:** `round up(0.07 × C × P × (1−P))`, from Kalshi's fee schedule (`docs/kalshi-fee-schedule.pdf`, effective
  2026-07-07). It matches every row of the schedule's fee table. No settlement fee. Open question: the text says centicent
  rounding but the table uses cents, so we use cents (conservative) until demo fills show which is right.
- **Edge:** P(side wins) − ask − fee per contract. YES asks come from NO bids (1 − bid). Must beat `MIN_EDGE` (3¢)
  at the *realised* fill, after the per-order rounded fee. Tiny orders often fail this: 1 contract at 1¢ pays a 1¢ fee.
- **Sizing:** quarter-Kelly on equity, then the tightest of 5% per market, 10% per event, 25% total, and cash.
- **Ranking:** each run ranks opportunities by edge and fills the risk budget best-first.
- **Fills:** walk the stored asks cheapest-first, never above the limit, never more than the listed depth. Partial or
  zero fills are recorded too.
- **Kill switch:** equity 30% below its peak means no new positions. Equity counts open positions at cost, so it only
  moves when positions settle.
- **Caveat:** a shadow fill doesn't remove liquidity from later snapshots. The per-market cap limits how much
  that can double-count.

## Running it unattended (milestone 6)

```powershell
docker compose up -d db
uv run python -m app.jobs.schedule
```

- **Every 30 min:** scan → parse → weather → forecast → shadow trades.
- **Hourly at :15:** observed highs → settle closed markets and shadow positions.
- **Daily at 15:00 UTC:** report written to `logs/report-YYYY-MM-DD.txt`.

Each step is its own `runs` row. A failing step is logged and recorded, and the scheduler carries on. Logs go to
`logs/scheduler.log`. `--once` runs every job one time and exits. **The PC must stay awake:** runs missed while it
sleeps are simply skipped (freshness limits stop the bot from trading on stale data afterwards).

- `uv run python -m app.report`: summary in the terminal. Brier and log loss for the model vs the market's mid at
  the same moment; bootstrap CI over whole events; calibration table; P&L gross / net of fees / net of API costs;
  bankroll and drawdown. If the model is worse than the market, it says so in capitals.
- `uv run python -m app.settle.resolver`: settle now. Markets settle when Kalshi reports `settlement_ts` and a
  yes/no result (`finalized`). NYC settled about 6 hours after close.
- **API:** `/health`, `/forecasts?date=YYYY-MM-DD`, `/trades`, `/metrics`.
- **Scoring unit:** each market's last forecast per model version, all made before the climate day starts.
- **Tests** use a separate `kalshi_test` database, created and migrated automatically, so they never touch real data.
