# 0004: Inflate ensemble spread to each station's recent forecast error

## Context
Spec Section 5.5 calls for "a small spread inflation to fix overconfidence". The first live run (2026-11-23) used a fixed 1.25× factor. Over the previous 29 days, bias-corrected day-ahead forecasts missed by a typical 2.1–2.5°F, but the inflated ensemble spread averaged only 1.7°F (Los Angeles: 0.59°F). The model put about 1% on ranges the market priced at 40–50%, and showed apparent edge on 84 of 144 ranges.

## Decision
Forecast `ens-v1.1`: per station, inflate the bias-corrected ensemble spread so its standard deviation is at least the root-mean-square of the deterministic models' error SDs over the bias window (past days only, `fetched_at <= decision time`). The factor never drops below the fixed minimum (`SPREAD_INFLATION`, 1.25). `ens-v1` forecasts already logged are kept and scored as their own model version.

## Alternatives considered
- **Keep the fixed 1.25×.** It's what the spec says, but it was measurably too narrow. Rejected.
- **A bigger global factor (e.g. 1.6×).** Crude: stations differ from 0.6 to 2.4°F in raw spread. Rejected.
- **Wait for EMOS (v2).** That's the principled fix, but it needs our own stored ensemble history first. Planned, not rejected; v1.1 bridges until then.

## Consequences
The error SD comes from deterministic day-ahead runs, not ensemble means. Ensemble means are usually a bit more accurate, so v1.1 may now be slightly *under*confident. Scoring will show it. v1.1 did not reduce disagreement with the market (mean |model − mid| 0.128 vs 0.120). Most of the remaining gap is where each distribution is centered. Only resolved outcomes can say who is right. Don't tune further by eye.

## Status
Accepted, 2026-11-23.
