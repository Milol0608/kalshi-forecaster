# 0005: Shadow-trade the NBM + market blend; keep logging the ensemble model

## Context
The full backtest (docs/BACKTEST.md) found that our ensemble model, `ens-v1.1` and its EMOS version, was clearly worse
than the market at both decision times, and that trading it lost the whole bankroll. NOAA's National Blend of Models
(NBM) alone was also worse than the market. Mixing calibrated NBM with the market mid (`nbm_blend`) beat the market
by a small margin (Brier +0.0008, CI [+0.0005, +0.0012], at the evening decision). In the approximate trading
simulation it grew $100 to $151, but with a 71% worst drawdown, and the bot's own 30% kill switch would have stopped it
on 2026-04-30. That's the only candidate so far with a positive simulated result, but not one robust enough to trust.

## Decision
- New model `nbm-blend-v1` (`app/forecast/nbm_blend.py`). It reads the newest NBS bulletin once per cycle, calibrates
  per station, mixes with each bucket's market mid, and renormalises over the event. Its parameters are fitted on all
  history up to 2026-11-21 by `app.backtest.run --export` and stored in `data/models/nbm_blend_v1.json`. Nothing is
  fitted live.
- The shadow trader acts on `TRADE_MODEL_VERSION` (default `nbm-blend-v1`). `ens-v1.1` keeps logging forecasts and
  being scored, but no longer trades.
- Judging is forward only: Gate 1 on live prices and real order-book depth. The backtest's P&L does not count.

## Alternatives considered
- **Keep trading `ens-v1.1`.** The backtest says it loses at every decision time. Rejected.
- **Trade the ens + market blend instead.** Its simulated result swung between $74 and $137 depending on the split,
  and its model weight (0.07) means it's almost just the market. Rejected for now. It can be re-tested the same way.
- **Market making (resting orders, 0% maker fee).** Not tested yet, because it needs full candle history to model
  fills. Still open, and not rejected.
- **Don't trade anything in shadow until something is robust.** Shadow costs nothing and is the honest forward test.
  Rejected.

## Consequences
- Live forecasts use the newest bulletin (hourly runs). The backtest used the 23Z run for the 8pm decision, so live
  inputs are somewhat fresher than what was tested.
- Each hourly run downloads one ~30 MB file from NOAA's open bucket, once per cycle.
- An event is skipped unless every bucket has a two-sided price, since the mix needs the market for each one.
- The 10 positions `ens-v1.1` opened on 2026-11-23 stay open and settle normally in the same shadow bankroll.
- Parameters go stale. Refit with the export command, and treat a refit as a new model version.

## Status
Accepted, 2026-11-24.
