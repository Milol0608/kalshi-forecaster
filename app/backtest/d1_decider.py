"""D1 (alpaca-trader/docs/RESEARCH.md): a trained decider for Kalshi daily-high bets, with and without the forecasts.

  uv run --with scikit-learn python -m app.backtest.d1_decider

D1a = the B1 rule (no model). D1b = model on market data only. D1c = D1b plus the GFS/ECMWF forecasts available at
8pm the evening before. Models fitted on markets dated before 2026-08-01; model type and threshold chosen on Mar-Jul
2026 fills; judged once on Aug-Nov 2026. Writes data/backtest/d1/result.json (incl. daily money paths).
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from app.backtest.data import CACHE, bucket_range, event_date
from app.backtest.makers import boot_ci, filled

OUT = Path("data/backtest/d1")
FIT_END, TEST_START, SPLIT, END = date(2026, 8, 1), date(2026, 3, 1), date(2026, 8, 1), date(2026, 11, 24)
ERR_END = date(2026, 3, 1)  # forecast bias and error size measured before this
THETAS = (0.0, 0.02, 0.04, 0.06)
CLI = re.compile(r"\((CLI[A-Z]{3})\)")
EPS = 1e-9


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def logit(p: float) -> float:
    p = min(max(p, 0.005), 0.995)
    return math.log(p / (1 - p))


def load() -> list[dict]:
    prices = json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))
    rows = []
    fc, obs = {}, {}
    markets = json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8"))
    # older rules don't name the station; take each series' station from its newer markets
    station = defaultdict(lambda: defaultdict(int))
    for m in markets:
        code = CLI.search(m.get("rules_primary") or "")
        if code:
            station[m["series"]][code.group(1)] += 1
    station = {s: max(v, key=v.get) for s, v in station.items()}
    for m in markets:
        pr = (prices.get(m["ticker"]) or {}).get("eve")
        d = event_date(m["event_ticker"])
        rng = bucket_range(m)
        c = station.get(m["series"])
        if not (pr and d and c and rng and m.get("result") in ("yes", "no")) or not m["series"].startswith("KXHIGH"):
            continue
        bid, ask = float(pr["bid"]), float(pr["ask"])
        if not (0 <= bid < ask <= 1):
            continue
        if c not in fc:
            f = CACHE / f"forecasts2_{c}.json"
            o = CACHE / f"obs_{c}.json"
            fc[c] = json.loads(f.read_text()) if f.exists() else {}
            obs[c] = json.loads(o.read_text()) if o.exists() else {}
        rows.append({"ticker": m["ticker"], "event": m["event_ticker"], "day": d, "city": c, "lo": rng[0], "hi": rng[1],
                     "bid": bid, "ask": ask, "t": int(pr["t"]), "y": 1 if m["result"] == "yes" else 0,
                     "fc": fc[c].get(d.isoformat())})
    # each city's forecast bias and error size, on days before ERR_END only
    err = {}
    for c in fc:
        res = []
        for k, v in fc[c].items():
            if k < ERR_END.isoformat() and k in obs[c] and "gfs2" in v and "ecmwf2" in v:
                res.append(obs[c][k] - (v["gfs2"] + v["ecmwf2"]) / 2)
        err[c] = (float(np.mean(res)), max(1.5, float(np.std(res)))) if len(res) >= 60 else (0.0, 3.0)
    for r in rows:
        v = r["fc"]
        if v and "gfs2" in v and "ecmwf2" in v:
            b, s = err[r["city"]]
            mu = (v["gfs2"] + v["ecmwf2"]) / 2 + b
            lo = -1e9 if r["lo"] == -math.inf else (r["lo"] - 0.5 - mu) / s
            hi = 1e9 if r["hi"] == math.inf else (r["hi"] + 0.5 - mu) / s
            r["p_fc"] = min(max(phi(hi) - phi(lo), 0.002), 0.998)
            r["disagree"] = abs(v["gfs2"] - v["ecmwf2"]) / s
            centre = mu if (r["lo"] == -math.inf and r["hi"] == math.inf) else \
                (r["hi"] if r["lo"] == -math.inf else (r["lo"] if r["hi"] == math.inf else (r["lo"] + r["hi"]) / 2))
            r["dist"] = max(-4.0, min(4.0, (mu - centre) / s))
        else:
            r["p_fc"] = None
    return rows


def features(rows: list[dict], cities: list[str], with_fc: bool) -> np.ndarray:
    X = []
    for r in rows:
        mid = (r["bid"] + r["ask"]) / 2
        m = r["day"].month
        x = [logit(mid), r["ask"] - r["bid"], math.sin(2 * math.pi * m / 12), math.cos(2 * math.pi * m / 12)]
        x += [1.0 if r["city"] == c else 0.0 for c in cities]
        if with_fc:
            x += [logit(r["p_fc"]), r["disagree"], r["dist"]]
        X.append(x)
    return np.array(X)


def load_tapes(keep: dict[str, dict]) -> dict[str, list]:
    tape = {}
    with (CACHE / "trades.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = keep.get(r["ticker"])
            if m:
                tape[r["ticker"]] = [t for t in r["trades"]
                                     if datetime.fromisoformat(t[0].replace("Z", "+00:00")).timestamp() >= m["t"]]
    return tape


def orders(r: dict, p: float | None) -> list[dict]:
    """The candidate order for a market and the model's edge for it (None = rule only)."""
    mid = (r["bid"] + r["ask"]) / 2
    if 0.65 <= mid < 0.95 and r["bid"] > 0:
        return [{"side": "buy", "price": r["bid"], "edge": None if p is None else p - r["bid"], "fav": True}]
    if 0.05 <= mid < 0.20 and r["ask"] < 1:
        return [{"side": "sell", "price": r["ask"], "edge": None if p is None else r["ask"] - p, "fav": False}]
    return []


def through_volume(side: str, price: float, trades: list) -> float:
    return sum(n for _, px, n, tk in trades if n > 0 and ((side == "buy" and tk == "no" and px < price - EPS) or
                                                          (side == "sell" and tk == "yes" and px > price + EPS)))


def evaluate(cands: list[dict], tape: dict, pred: dict | None, theta: float, lo: date, hi: date) -> dict:
    fills, groups = [], defaultdict(list)
    for r in cands:
        if not (lo <= r["day"] < hi) or r["ticker"] not in tape:
            continue
        for o in orders(r, None if pred is None else pred[r["ticker"]]):
            if pred is None:
                if not o["fav"]:
                    continue  # D1a is B1 only: favourites
            elif o["edge"] < theta:
                continue
            if filled(o["side"], o["price"], tape[r["ticker"]], True):
                v = (r["y"] - o["price"]) if o["side"] == "buy" else (o["price"] - r["y"])
                fills.append({"day": r["day"], "event": r["event"], "v": v, "side": o["side"], "price": o["price"],
                              "edge": o["edge"], "thru": through_volume(o["side"], o["price"], tape[r["ticker"]])})
                groups[r["event"]].append(v)
    vs = [f["v"] for f in fills]
    lo_ci, hi_ci = boot_ci(groups) if len(groups) > 1 else (0.0, 0.0)
    return {"fills": len(vs), "c": float(np.mean(vs)) if vs else 0.0, "total": float(sum(vs)), "lo": lo_ci,
            "hi": hi_ci, "list": fills}


def money(fills: list[dict], sizing: str, start: float = 100.0, fallback_edge: float = 0.0342) -> dict:
    """Daily bankroll path. 1 contract, or quarter Kelly with the model's edge (B1's train lower bound if no model),
    at most 5% of bankroll per bid, 25% per day, 25% of the through-volume, 500 contracts."""
    bank, peak, worst, path = start, start, 0.0, []
    by_day = defaultdict(list)
    for f in fills:
        by_day[f["day"]].append(f)
    for d in sorted(by_day):
        spend, pnl = 0.0, 0.0
        for f in by_day[d]:
            cost = f["price"] if f["side"] == "buy" else 1 - f["price"]
            if sizing == "1":
                n = 1
            else:
                edge = f["edge"] if f["edge"] is not None else fallback_edge
                frac = min(0.05, 0.25 * max(edge, 0) / max(1e-6, 1 - cost))
                n = int(min(frac * bank / cost, 0.25 * f["thru"], 500))
            n = min(n, int(max(0.0, 0.25 * bank - spend) / cost))
            if n <= 0:
                continue
            spend += n * cost
            pnl += n * f["v"]
        bank += pnl
        peak = max(peak, bank)
        worst = max(worst, 1 - bank / peak)
        path.append([d.isoformat(), round(bank, 2)])
    return {"end": round(bank, 2), "worst_drop": round(worst, 3), "path": path}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load()
    cities = sorted({r["city"] for r in rows})
    fit = [r for r in rows if r["day"] < FIT_END and 0.01 <= (r["bid"] + r["ask"]) / 2 <= 0.99]
    fit_fc = [r for r in fit if r["p_fc"] is not None]
    cands = [r for r in rows if r["day"] >= TEST_START]
    keep = {r["ticker"]: r for r in cands if orders(r, None)}
    tape = load_tapes(keep)
    print(f"{len(rows)} daily-high markets with an 8pm price; fit on {len(fit)} ({len(fit_fc)} with forecasts); "
          f"{len(keep)} candidates since Mar 2026, {len(tape)} with a tape", flush=True)

    preds = {}
    for with_fc in (False, True):
        tr = fit_fc if with_fc else fit
        X, y = features(tr, cities, with_fc), np.array([r["y"] for r in tr])
        usable = [r for r in keep.values() if (r["p_fc"] is not None or not with_fc)]
        Xc = features(usable, cities, with_fc)
        for name, model in (("logistic", LogisticRegression(C=1.0, max_iter=2000)),
                            ("trees", HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05,
                                                                     random_state=0))):
            model.fit(X, y)
            p = model.predict_proba(Xc)[:, 1]
            preds[(name, with_fc)] = {r["ticker"]: float(q) for r, q in zip(usable, p)}

    train, test = (TEST_START, SPLIT), (SPLIT, END)
    res = {"D1a B1 rule": {"train": evaluate(cands, tape, None, 0, *train), "test": evaluate(cands, tape, None, 0, *test)}}
    print(f"\n{'version':<34}{'theta':>6}{'tr fills':>9}{'tr c':>7}{'tr $':>7}{'te fills':>9}{'te c':>7}{'te $':>7}"
          f"{'te 95% CI':>18}")
    b = res["D1a B1 rule"]
    print(f"{'D1a B1 rule (no model)':<34}{'-':>6}{b['train']['fills']:>9}{b['train']['c'] * 100:>7.2f}"
          f"{b['train']['total']:>7.2f}{b['test']['fills']:>9}{b['test']['c'] * 100:>7.2f}{b['test']['total']:>7.2f}"
          f"   [{b['test']['lo'] * 100:+.2f}, {b['test']['hi'] * 100:+.2f}]")
    best = {}
    for (name, with_fc), pred in preds.items():
        label = f"D1{'c' if with_fc else 'b'} {name}{' + forecasts' if with_fc else ''}"
        sub = [r for r in cands if r["ticker"] in pred]
        for th in THETAS:
            a, t = evaluate(sub, tape, pred, th, *train), evaluate(sub, tape, pred, th, *test)
            res[f"{label} | {th:.2f}"] = {"train": a, "test": t}
            print(f"{label:<34}{th * 100:>6.0f}{a['fills']:>9}{a['c'] * 100:>7.2f}{a['total']:>7.2f}{t['fills']:>9}"
                  f"{t['c'] * 100:>7.2f}{t['total']:>7.2f}   [{t['lo'] * 100:+.2f}, {t['hi'] * 100:+.2f}]")
            fam = "D1c" if with_fc else "D1b"
            if a["fills"] >= 100 and (fam not in best or a["total"] > res[best[fam]]["train"]["total"]):
                best[fam] = f"{label} | {th:.2f}"

    print("\nChoices (made on Mar-Jul fills only):")
    summary = {}
    b_test = res["D1a B1 rule"]["test"]
    for fam in ("D1b", "D1c"):
        k = best.get(fam)
        if not k:
            print(f"  {fam}: no setting reached 100 train fills")
            continue
        t = res[k]["test"]
        ok = t["c"] > 0 and t["lo"] > 0 and t["total"] > b_test["total"]
        print(f"  {fam}: {k}  ->  test {t['fills']} fills, {t['c'] * 100:+.2f}c/fill, ${t['total']:.2f} at 1 contract "
              f"vs B1 ${b_test['total']:.2f}   {'PASS' if ok else 'FAIL'}")
        summary[fam] = {"choice": k, "pass": ok}
    money_out = {}
    for k in ["D1a B1 rule"] + [best[f] for f in ("D1b", "D1c") if f in best]:
        for sizing in ("1", "kelly"):
            money_out[f"{k} | {sizing}"] = money(res[k]["test"]["list"], sizing)
            m = money_out[f"{k} | {sizing}"]
            print(f"  money Aug-Nov from $100, {k}, {'1 contract' if sizing == '1' else '1/4 Kelly'}: ${m['end']:.2f}, "
                  f"worst drop {m['worst_drop']:.0%}")
    slim = {k: {s: {x: v for x, v in d.items() if x != "list"} for s, d in r.items()} for k, r in res.items()}
    kept = {k: res[k]["test"]["list"] for k in ["D1a B1 rule"] + [best[f] for f in ("D1b", "D1c") if f in best]}
    (OUT / "result.json").write_text(json.dumps({"results": slim, "choices": summary, "money": money_out,
                                                 "test_fills": kept}, indent=1, default=str))


if __name__ == "__main__":
    random.seed(0)
    main()
