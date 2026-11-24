# Backtest results

`uv run python -m app.backtest.data` downloads the history. `uv run python -m app.backtest.run --decision eve|am`
scores each model against the market on months it wasn't trained on. Backtest results never count toward Gate 1.

## Method
- **Markets:** settled Kalshi daily-high markets, 24 cities. Before Aug 2026 the rules named stations in words and
  settled on the NWS climate report. A data check (the winning range contains today's station's observed high)
  passed on 99–100% of days for every city and period, so all of them are included.
- **Decision times:** `eve` = 8pm local standard time the evening before, which is when the live bot trades.
  `am` = 8am local standard time on the day.
- **Forecasts:** Open-Meteo archived GFS + ECMWF day-ahead highs. At `eve` only 48h-ahead values are guaranteed
  to have been published, at `am` 24h-ahead values, so there's no look-ahead.
- **Market probability:** mid of the last hourly bid/ask candle at or before the decision time.
- **Models:** `current` (rolling 30-day bias and error SD, like live v1.1), `emos` (v2: per-station regression
  fitted by CRPS on the training period), `blend` (logistic mix of emos and the market, fitted on the training period).
- **Scoring:** Brier and log loss, with a 95% CI from resampling whole city-days. Trading P&L is approximate
  (top-of-book prices only, ≤ 25 contracts per order).

## Results (final, 2026-11-23)

All 24 cities. Prices from Sep 2025 onward (earlier markets have forecasts and outcomes but no downloaded prices).
EMOS trains on Mar 2024 – Feb 2026 forecasts vs observed highs. The blend trains on Sep 2025 – Feb 2026 markets.
**Test: 2026-03-01 .. 2026-11-21**, never seen in training. Gap = market Brier − model Brier (+ = model better),
95% CI from resampling whole city-days.

| | eve Brier | eve gap [95% CI] | eve $100 → | am Brier | am gap [95% CI] | am $100 → |
|---|---|---|---|---|---|---|
| market | 0.1045 | | | 0.0953 | | |
| current | 0.1321 | −0.0276 [−0.0290, −0.0262] | $0.37 | 0.1237 | −0.0284 [−0.0299, −0.0269] | $0.38 |
| emos (v2) | 0.1320 | −0.0275 [−0.0289, −0.0261] | $0.39 | 0.1240 | −0.0287 [−0.0302, −0.0271] | $0.36 |
| blend | 0.1034 | +0.0011 [+0.0008, +0.0014] | $89.56 | 0.0947 | +0.0006 [+0.0003, +0.0009] | $93.36 |

eve: 33,786 test markets in 5,631 events. am: 34,038 in 5,673. Blend weights on logits: eve intercept +0.216,
model +0.075, market +1.156; am +0.157 / +0.064 / +1.155.

## Decision
- **The weather model is retired as a trading candidate.** Both versions are clearly worse than the market at both
  decision times, and trading them loses the whole bankroll in simulation. It keeps logging in shadow at no cost.
- **The blend beats the market statistically but not after costs.** Its gain comes from pushing the market's own
  prices further from 50% (market weight 1.16), which suggests a small bias in how the market prices extremes. The
  bias is smaller than the fees plus the bid/ask spread.
- **Next, each through this same backtest before anything else:** (1) NOAA National Blend of Models probabilities,
  (2) same-day high-resolution forecasts plus live observations, (3) market making (maker fees are 0 on these
  series) to capture the spread and the extremes bias without paying taker fees, (4) other categories.

## Earlier interim run (about 60% of cities)
eve: market 0.1014; current 0.1325; emos 0.1314; blend 0.1011. Superseded by the final table above.
