# 0007. Two more maker paper arms: B1 at ¼ Kelly, and the D1c decider at ¼ Kelly

## Status
Accepted 2026-11-25 (owner: "we will check the decider with 1/4 Kelly … against normal 1/4 Kelly and against B1").
Paper only. Pre-registered as F1 in alpaca-trader/docs/RESEARCH.md.

## Context
- B1 (ADR 0006) is the only Kalshi rule that passed out of sample. It runs on paper at 1 contract per bid.
- S1/D1 backtests on Aug–Nov 2026 from $100: B1 1 contract $113, B1 ¼ Kelly $140 (worst drop 10%), D1c decider
  (trees on price + GFS/ECMWF forecasts) ¼ Kelly $187 (worst drop 28%). D1c **failed** its pre-registered bar: its
  per-bet edge was +1.36¢ with a 95% range that includes zero. The owner wants it tested forward anyway, as an arm.
- Checked when freezing the model: on favourites D1c mostly encodes the same ~9¢ underpricing B1 trades, so it bets
  on nearly the same favourites as B1 but sizes them larger (its claimed edge is bigger, so ¼ Kelly hits the 5% cap).
  The forecasts matter mostly for which longshots it sells. Its extra backtest dollars come from bigger bets and
  longshots, which is also where its extra drawdown comes from.

## Decision
- The maker step runs three arms on the same live markets, same 8pm post window, same "through" fill rule:
  `B1-fav-bid` (unchanged), `B1-kelly`, `D1c-kelly`. Each Kelly arm has its own $100 paper bankroll
  ($100 + its settled P&L).
- Sizing as in the backtest: ¼ Kelly, ≤ 5% of the arm's bankroll per order, ≤ 25% posted per 20 h, ≤ 500 contracts;
  at close a Kelly order counts min(size, 25% of the through-volume) as filled, else it expires.
- D1c is **frozen**: same recipe as the D1 backtest, refitted once on all 40,869 daily-high markets with an 8pm price
  through 2026-11-21, exported to JSON (`app/execution/d1c_model.json`, no scikit-learn in the bot). The export
  checks the JSON trees reproduce scikit-learn exactly and that the live feature code rebuilds the backtest's
  features exactly. Live forecasts: Open-Meteo previous-runs `temperature_2m_previous_day2`, one call per event.
- The report shows the three arms side by side.

## Alternatives considered
- **Simulate ¼ Kelly from B1's fills in the report only** (no new orders). Cheaper, but sizes would be computed after
  the fact and the 25%-of-through-volume cap needs trade counts at close; a real arm records what it would have
  posted at the time. Rejected.
- **Freeze the exact pre-Aug model that was tested.** Purer, but discards four months of data; the forward test is
  of the recipe. Rejected; the refit is recorded here.
- **Switch B1 to ¼ Kelly outright.** The owner chose to compare first.
- **Add scikit-learn to the hosted bot.** Heavier install and pickle/version risk for 177 small trees. Rejected.

## Consequences
- Up to ~3× the maker orders per evening, and up to ~24 more Open-Meteo calls a day (logged in api_costs).
- `maker_orders` gains `edge`, `thru_volume`, `filled_contracts` (migration a7d1c0f3e2b1). The unmerged V1 gap-logger
  branch also adds a migration on top of d8333c63b71c; it must be re-parented onto a7d1c0f3e2b1 before merging.
- Known live/backtest gap: for late hours of the climate day, the "48 h before" forecast run may not exist yet at
  8pm, so Open-Meteo returns the latest run instead; the backtest saw the true 48 h run. Usually irrelevant to the
  daily high (afternoon), but it is a reason the forward result can differ.
- Review per F1 in RESEARCH.md. No real money, no change to the taker bot.
