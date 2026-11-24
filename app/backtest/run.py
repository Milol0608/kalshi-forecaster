"""Backtest: score every model against the market on months none of them were trained on.

Train period: everything before --test-start. Test period: --test-start onwards.
- `current` needs no fitting (rolling 30-day bias/SD, like live v1.1).
- `emos` is fitted per station on train-period forecasts vs observed highs (IEM climate reports).
- `blend` is fitted on train-period markets (needs market prices), then scored on the test period.

Trading simulation (approximate): the live rules (edge > MIN_EDGE after the real rounded fee,
quarter-Kelly, 5%/10%/25% caps), buying at the historical ask at decision time. History has
top-of-book only, not depth, so each order is also capped at MAX_CONTRACTS_PER_ORDER. Treat its
P&L as a rough sign, not a promise. The Brier comparison is the solid result.

Run: uv run python -m app.backtest.run --test-start 2025-12-01
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

from app.backtest.data import CACHE, LEAD_FOR, bucket_range, event_date, load_observations, series_stations
from app.backtest import nbm
from app.backtest.models import Emos, NbmEmos, bucket_probs, fit_blend, fit_emos, fit_nbm_emos
from app.config import get_settings
from app.evidence.stations import load_stations
from app.kalshi.fees import order_fee
from app.strategy.sizing import kelly_spend

MAX_CONTRACTS_PER_ORDER = 25


@dataclass
class Row:
    event: str
    city: str
    day: date
    ticker: str
    lo: float
    hi: float
    y: int
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-3, 1 - 1e-3)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def boot_gap(events: list[str], p_mkt: np.ndarray, p: np.ndarray, y: np.ndarray, n: int = 2000) -> tuple[float, float, float]:
    idx: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(events):
        idx[e].append(i)
    keys = list(idx)
    def gap(ii: list[int]) -> float:
        return brier(p_mkt[ii], y[ii]) - brier(p[ii], y[ii])
    rng = random.Random(11)
    gaps = sorted(gap([i for k in rng.choices(keys, k=len(keys)) for i in idx[k]]) for _ in range(n))
    return gap(list(range(len(y)))), gaps[int(0.025 * n)], gaps[int(0.975 * n) - 1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-start", default="2025-12-01")
    ap.add_argument("--prices", default=str(CACHE / "prices.json"), help="prices file (e.g. a snapshot)")
    ap.add_argument("--decision", choices=["eve", "am"], default="eve",
                    help="eve: 8pm the evening before (when the live bot trades); am: 8am on the day")
    args = ap.parse_args()
    test_start = date.fromisoformat(args.test_start)
    settings = get_settings()
    stations = load_stations(settings.stations_file)

    markets = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    prices = {t: v[args.decision] for t, v in json.loads(Path(args.prices).read_text(encoding="utf-8")).items()
              if v and v.get(args.decision)}
    from sqlalchemy.orm import Session

    from app.db.session import get_engine

    with Session(get_engine()) as s:
        series_code = series_stations(s)  # today's station per series; data.py confirmed history matches it
    codes = sorted(set(series_code.values()))

    lead = LEAD_FOR[args.decision]
    first_bias_day = 2 if args.decision == "eve" else 1  # yesterday's high isn't published by 8pm yesterday
    forecasts = {}
    for c in codes:
        f = CACHE / f"forecasts2_{c}.json"
        if f.exists():
            forecasts[c] = {d: {"gfs": v[f"gfs{lead}"], "ecmwf": v[f"ecmwf{lead}"]}
                            for d, v in json.loads(f.read_text(encoding="utf-8")).items()
                            if f"gfs{lead}" in v and f"ecmwf{lead}" in v}
    print(f"decision={args.decision}: market price at that time, forecasts issued {24 * lead}h before valid time")
    first_day = min(date.fromisoformat(d) for fc in forecasts.values() for d in fc)
    years = list(range(first_day.year - (1 if first_day.month == 1 else 0), date.today().year + 1))
    obs = {c: load_observations(c, stations[c].icao, years) for c in forecasts}

    # ---- fit EMOS per station on the training period (forecasts vs observed highs only) ----
    emos: dict[str, Emos] = {}
    for c, fc in forecasts.items():
        days = [d for d, v in fc.items() if "gfs" in v and "ecmwf" in v and d in obs[c] and date.fromisoformat(d) < test_start]
        if len(days) >= 120:
            emos[c] = fit_emos(np.array([fc[d]["gfs"] for d in days]), np.array([fc[d]["ecmwf"] for d in days]),
                               np.array([obs[c][d] for d in days]))
    print(f"EMOS fitted for {len(emos)}/{len(forecasts)} stations (>= 120 training days each)")

    # ---- NOAA National Blend of Models: raw, and calibrated per station on the training period ----
    all_days = [first_day + timedelta(days=k) for k in range((date.today() - first_day).days)]
    nbm_feat = nbm.features({c: stations[c] for c in forecasts}, args.decision, all_days)
    nbm_emos: dict[str, NbmEmos] = {}
    for c, fc in nbm_feat.items():
        days = [d for d in fc if d in obs[c] and date.fromisoformat(d) < test_start]
        if len(days) >= 120:
            nbm_emos[c] = fit_nbm_emos(*(np.array([fc[d][k] for d in days], dtype=float) for k in ("txn", "tmax", "xnd")),
                                       np.array([obs[c][d] for d in days], dtype=float))
    print(f"NBM: {sum(map(len, nbm_feat.values()))} station-days; calibrated for {len(nbm_emos)} stations")

    # ---- the 'current' model: rolling 30-day bias + error SD, like live v1.1 ----
    def current(c: str, d: date) -> tuple[float, float] | None:
        fc, ob = forecasts[c], obs[c]
        today = fc.get(d.isoformat())
        if not today or "gfs" not in today or "ecmwf" not in today:
            return None
        errs: dict[str, list[float]] = {"gfs": [], "ecmwf": []}
        for k in range(first_bias_day, first_bias_day + 30):
            p = (d - timedelta(days=k)).isoformat()
            if p in fc and p in ob:
                for m in errs:
                    if m in fc[p]:
                        errs[m].append(ob[p] - fc[p][m])
        if min(len(v) for v in errs.values()) < 10:
            return None
        bias = {m: sum(v) / len(v) for m, v in errs.items()}
        sds = [float(np.std(v, ddof=1)) for v in errs.values()]
        mu = ((today["gfs"] + bias["gfs"]) + (today["ecmwf"] + bias["ecmwf"])) / 2
        return mu, math.sqrt(sum(s * s for s in sds) / len(sds))

    # ---- assemble scored rows: one per market, full events only ----
    events: dict[str, list[tuple[dict, tuple[float, float]]]] = defaultdict(list)
    for m in markets:
        r = bucket_range(m)
        if r is not None and m["ticker"] in prices:
            events[m["event_ticker"]].append((m, r))
    rows: list[Row] = []
    p_cur: list[float] = []
    p_emos: list[float] = []
    p_nraw: list[float] = []
    p_nbm: list[float] = []
    skipped = defaultdict(int)
    for ev, ms in events.items():
        ms.sort(key=lambda x: x[1])
        rngs = [r for _, r in ms]
        ok = rngs[0][0] == -math.inf and rngs[-1][1] == math.inf and all(
            b[0] == a[1] + 1 for a, b in zip(rngs, rngs[1:]))
        if not ok:
            skipped["event buckets incomplete or unpriced"] += 1
            continue
        c, d = series_code[ms[0][0]["series"]], event_date(ev)
        if c not in forecasts or d is None:
            skipped["no forecasts"] += 1
            continue
        cur = current(c, d)
        fc = forecasts[c].get(d.isoformat(), {})
        if cur is None or c not in emos or "gfs" not in fc or "ecmwf" not in fc:
            skipped["not enough history for a model"] += 1
            continue
        nf = nbm_feat.get(c, {}).get(d.isoformat())
        if nf is None or c not in nbm_emos:
            skipped["no NBM bulletin before the decision"] += 1
            continue
        em_mu, em_sd = emos[c].predict(np.array([fc["gfs"]]), np.array([fc["ecmwf"]]))
        pc = bucket_probs(cur[0], cur[1], rngs)
        pe = bucket_probs(float(em_mu[0]), float(em_sd[0]), rngs)
        pnr = bucket_probs(float(nf["txn"]), max(float(nf["xnd"]), 1.0), rngs)
        n_mu, n_sd = nbm_emos[c].predict(*(np.array([float(nf[k])]) for k in ("txn", "tmax", "xnd")))
        pn = bucket_probs(float(n_mu[0]), float(n_sd[0]), rngs)
        for (m, r), a, b, nr, nn in zip(ms, pc, pe, pnr, pn):
            pr = prices[m["ticker"]]
            rows.append(Row(ev, c, d, m["ticker"], r[0], r[1], 1 if m["result"] == "yes" else 0,
                            float(pr["bid"]), float(pr["ask"])))
            p_cur.append(float(a))
            p_emos.append(float(b))
            p_nraw.append(float(nr))
            p_nbm.append(float(nn))
    print(f"scored markets: {len(rows)} in {len({r.event for r in rows})} events; skipped events {dict(skipped)}")

    y = np.array([r.y for r in rows], dtype=float)
    mid = np.array([r.mid for r in rows])
    pc_a, pe_a = np.array(p_cur), np.array(p_emos)
    train = np.array([r.day < test_start for r in rows])
    test = ~train
    pnr_a, pn_a = np.array(p_nraw), np.array(p_nbm)

    def blended(p_model: np.ndarray, label: str):
        b = fit_blend(p_model[train], mid[train], y[train])
        pb = b.predict(p_model, mid)
        sums: dict[str, float] = defaultdict(float)
        for r, p in zip(rows, pb):
            sums[r.event] += p
        print(f"{label} weights (on logits): intercept {b.params[0]:+.3f}, model {b.params[1]:+.3f}, market {b.params[2]:+.3f}")
        return b, np.array([p / sums[r.event] for r, p in zip(rows, pb)])  # renormalise each event to 1

    blend, pb = blended(pe_a, "blend")
    nbm_blend, pnb = blended(pn_a, "nbm_blend")
    models = {"current": pc_a, "emos": pe_a, "blend": pb, "nbm_raw": pnr_a, "nbm": pn_a, "nbm_blend": pnb}

    ev_test = [r.event for r, t in zip(rows, test) if t]
    print(f"\nTEST PERIOD {test_start} .. : {int(test.sum())} markets, {len(set(ev_test))} events "
          f"(train: {int(train.sum())} markets)")
    print(f"{'model':<10}{'Brier':>9}{'LogLoss':>9}   gap vs market (+ = beats market), 95% CI over events")
    print(f"{'market':<10}{brier(mid[test], y[test]):>9.4f}{logloss(mid[test], y[test]):>9.4f}")
    results = {}
    for name, p in models.items():
        g, lo, hi = boot_gap(ev_test, mid[test], p[test], y[test])
        results[name] = (g, lo, hi)
        tag = "BEATS MARKET" if lo > 0 else ("WORSE THAN MARKET" if hi < 0 else "not distinguishable")
        print(f"{name:<10}{brier(p[test], y[test]):>9.4f}{logloss(p[test], y[test]):>9.4f}   "
              f"{g:+.4f} [{lo:+.4f}, {hi:+.4f}]  {tag}")

    # ---- approximate trading simulation on the test period ----
    print(f"\nAPPROX. SHADOW TRADING on test period (buy at historical ask, <= {MAX_CONTRACTS_PER_ORDER} contracts/order)")
    sim = {}
    for name, p in models.items():
        equity = Decimal(str(settings.starting_bankroll))
        peak, max_dd, trades, wins = equity, 0.0, 0, 0
        by_day: dict[date, list[int]] = defaultdict(list)
        for i, r in enumerate(rows):
            if test[i]:
                by_day[r.day].append(i)
        for d in sorted(by_day):
            spent: dict[str, Decimal] = defaultdict(Decimal)
            total = Decimal(0)
            pnl_day = Decimal(0)
            cands = []
            for i in by_day[d]:
                r = rows[i]
                for side, q, ask in (("yes", p[i], r.ask), ("no", 1 - p[i], 1 - r.bid)):
                    if not 0 < ask < 1:
                        continue
                    a = Decimal(str(round(ask, 4)))
                    edge = q - ask - float(order_fee([(a, Decimal(1))]))
                    if edge > settings.min_edge:
                        cands.append((edge, i, side, q, a))
            for edge, i, side, q, a in sorted(cands, reverse=True):
                r = rows[i]
                cap = min(Decimal(str(settings.max_position_pct)) * equity,
                          Decimal(str(settings.max_per_event_pct)) * equity - spent[r.event],
                          Decimal(str(settings.max_total_exposure_pct)) * equity - total)
                budget = min(kelly_spend(q, a, equity, settings.kelly_fraction), cap)
                n = min(int(budget / a) if a > 0 else 0, MAX_CONTRACTS_PER_ORDER)
                while n >= 1:
                    cost = a * n + order_fee([(a, Decimal(n))])
                    if cost <= budget and q - float(cost / n) > settings.min_edge:
                        break
                    n -= 1
                if n < 1:
                    continue
                cost = a * n + order_fee([(a, Decimal(n))])
                won = (r.y == 1) == (side == "yes")
                pnl_day += (Decimal(n) if won else Decimal(0)) - cost
                spent[r.event] += cost
                total += cost
                trades += 1
                wins += won
            equity += pnl_day
            peak = max(peak, equity)
            max_dd = max(max_dd, float(1 - equity / peak))
        rate = f"{wins / trades:.0%}" if trades else "-"
        sim[name] = {"trades": trades, "wins": wins, "final": float(equity), "max_dd": max_dd}
        print(f"  {name:<9} trades {trades:>5}  win rate {rate:>4}  final bankroll ${equity:>9.2f}  max drawdown {max_dd:.0%}")

    out = {"test_start": test_start.isoformat(), "emos": {c: e.params.tolist() for c, e in emos.items()},
           "blend": blend.params.tolist(), "results": results, "sim": sim,
           "nbm_emos": {c: e.params.tolist() for c, e in nbm_emos.items()}, "nbm_blend": nbm_blend.params.tolist()}
    out["decision"] = args.decision
    path = Path(f"data/backtest/results_{args.decision}.json")
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nfitted parameters saved to {path}")


if __name__ == "__main__":
    main()
