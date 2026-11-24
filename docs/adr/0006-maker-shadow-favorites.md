# 0006. Shadow-trade K2 rule B1: resting bids on evening favorites

## Status
Accepted 2026-11-24 (owner approved: "Yes, yes please").

## Context
K2 (alpaca-trader/docs/RESEARCH.md) replayed maker orders against Kalshi's real trade tape for every
test-period weather market (Mar–Nov 2026). Buying YES at the best bid at 8pm local standard time the
evening before, on buckets priced 65–95¢, filled 89% of the time under the conservative "through" rule. It
earned +7.1¢ per contract (95% CI +3.0 to +11.1 over city-days) and +5.4¢ in Jul–Nov alone. Weather series
charge makers no fee: the API reports `fee_type: "quadratic"`, versus `"quadratic_with_maker_fees"` for
Fed/CPI/NFL. The sample is small (419 markets), and a backtest can't show queue position.

## Decision
Run B1 forward in shadow mode as its own step (`maker`, after `shadow`) in the hourly pipeline:
- Post: within 2 hours after each event's 8pm-local-standard-time eve, one buy-YES order per bucket whose
  latest snapshot (at most 90 minutes old) has a mid in [65¢, 95¢), at the YES bid, for 1 contract.
- Fill: from the market's real public trade tape (`GET /markets/trades`), only when a taker sells YES strictly
  below our price.
- Expire: if the market closes unfilled. Settle filled orders from the existing settlement rows.
- Stored in `maker_orders`. Kept out of the taker bankroll and kill switch. The report shows posted, fill rate
  and net ¢ per contract against the backtest's 89% and +7.1¢.

## Alternatives considered
- **Use the NBM blend's taker bankroll for B1 as a taker at the ask.** Rejected: +4.66¢ as a taker wasn't
  pre-registered (K1 skipped it on 26 training markets), and it would mix two strategies in one P&L.
- **Size by Kelly with real money.** Rejected: the project is paper/shadow only, and 419 markets is too few to
  size on.
- **Don't run it; wait for more backtest months.** Rejected: only a forward run checks the one thing the
  backtest can't, whether fills still happen once the order is really in the queue.

## Consequences
- About 1–2 orders a day. A meaningful read (fill rate and ¢/contract with a usable interval) needs about
  6–8 weeks (roughly 100 fills).
- Through-fills are conservative, so a real order at the same price would fill at least as often. Partial
  fills and size beyond 1 contract are not measured.
- Pass to keep going: fill rate within 10 points of 89% and mean ¢ per contract positive after about
  100 settled fills. Otherwise, stop and write down why.
