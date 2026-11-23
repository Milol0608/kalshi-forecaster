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

## Results

**Interim, 2026-11-23** (about 60% of cities' archived prices downloaded). Train < 2026-03-01, test 2026-03-01 .. 2026-11-21:

| eve (8pm before) | Brier | Gap vs market (+ = model better) | $100 becomes |
|---|---|---|---|
| market | 0.1014 | | |
| current | 0.1325 | −0.0311 [−0.0328, −0.0294] | $0.38 |
| emos (v2) | 0.1314 | −0.0301 [−0.0319, −0.0283] | $0.37 |
| blend | 0.1011 | +0.0003 [+0.0000, +0.0005] | $90.46 |

21,708 test markets in 3,618 events. The blend's weights were model +0.015, market +1.18.

**Earlier check, `am` (8am on the day), recent 3 months:** market 0.0833, current 0.1232, emos 0.1237, blend 0.0833.

## Conclusion so far
Free global NWP forecasts are much less sharp than the Kalshi market, at both decision times. The market's implied
error is about ±1.7°F the evening before, against ±2.5–3°F for these forecasts. Trading on the model loses
everything in simulation, because the trades it favours are exactly where it's wrong. Blending with the market
adds nothing that survives fees. Gate 1 would correctly block live trading. Beating this market would need
materially better inputs (for example NWS National Blend probabilities, high-resolution short-range models, or
same-day observations), not more tuning of this model.
