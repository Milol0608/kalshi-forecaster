"""K10 stage 1, Polymarket US part (alpaca-trader/docs/RESEARCH.md). Polymarket US's only recurring non-temperature
markets are sports games, so this is research only (standing rule: no sports trading). The 3 leagues with the most
closed game markets are picked from the market list before any price is pulled. Price 6 h before the market's end
date; favourite = whichever side has a mid of 65-95c.

  uv run python -m app.backtest.k10_poly          (downloads into data/backtest/k10/poly_rows.jsonl, then scores)
  uv run python -m app.backtest.k10_poly --score
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import httpx
import numpy as np

from app.backtest import k8_poly as k8

DIR = k8.DIR.parent / "k10"
SPLIT = date(2026, 8, 1)
LO, HI = 0.65, 0.95
PER_LEAGUE = 1500
GAME = re.compile(r"^aec-([a-z0-9]+)-")


def list_games(http: httpx.Client) -> list[dict]:
    out, offset = [], 0
    while True:
        page = (k8.get(http, "/v1/markets", {"categories": "sports", "closed": "true", "limit": 100, "offset": offset})
                or {}).get("markets") or []
        for m in page:
            g = GAME.match(m.get("slug") or "")
            if g and m.get("endDate"):
                out.append({"slug": m["slug"], "league": g.group(1), "end": m["endDate"],
                            "outcomes": m.get("outcomes"), "final": m.get("outcomePrices")})
        if len(page) < 100:
            return out
        offset += 100
        if offset % 5000 == 0:
            print(f"  listed {offset}", flush=True)


def fetch(http: httpx.Client, m: dict) -> dict:
    end = int(datetime.fromisoformat(m["end"].replace("Z", "+00:00")).timestamp())
    t = end - 6 * 3600
    h = (k8.get(http, "/v1/price-history", {"symbol": m["slug"], "timestamp.startTimestamp": t - 7200,
                                             "timestamp.endTimestamp": t, "fidelity": 1}) or {}).get("history") or []
    pts = [p for p in h if int(p["timestamp"]) <= t]
    price = None
    if pts:
        p = max(pts, key=lambda p: int(p["timestamp"]))
        price = {"t": int(p["timestamp"]), "ask": float(p["longPrice"]), "bid": 1 - float(p["shortPrice"])}
    s = k8.get(http, f"/v1/markets/{m['slug']}/settlement")
    return {**m, "decision": t, "price": price, "settlement": (s or {}).get("settlement")}


def download() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / "poly_rows.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(x)["slug"] for x in path.read_text(encoding="utf-8").splitlines() if x.strip()}
    with httpx.Client(timeout=30) as http:
        games = list_games(http)
        leagues = Counter(g["league"] for g in games)
        top = [k for k, _ in leagues.most_common(3)]
        print(f"{len(games)} closed game markets; leagues {leagues.most_common(8)}; screening {top}", flush=True)
        rng = random.Random(11)
        todo = []
        for lg in top:
            pool = [g for g in games if g["league"] == lg]
            rng.shuffle(pool)
            todo += [g for g in pool[:PER_LEAGUE] if g["slug"] not in done]

        def safe(m):
            try:
                return fetch(http, m)
            except RuntimeError as e:
                print(f"  skipped for now: {e}", flush=True)
                return None
        with ThreadPoolExecutor(6) as pool, path.open("a", encoding="utf-8") as fh:
            for i, r in enumerate(pool.map(safe, todo), 1):
                if r is not None:
                    fh.write(json.dumps(r) + "\n")
                if i % 250 == 0:
                    fh.flush()
                    print(f"  {i}/{len(todo)}", flush=True)


def score() -> dict:
    rows = [json.loads(x) for x in (DIR / "poly_rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:  # outcomePrices can arrive as a JSON string
        if isinstance(r.get("final"), str):
            try:
                r["final"] = json.loads(r["final"])
            except json.JSONDecodeError:
                r["final"] = None
    # settlement 1 should mean the first-listed side won: check it against the final prices Polymarket shows
    agree = [int(float(r["final"][0]) > 0.5) == int(r["settlement"]) for r in rows
             if r.get("settlement") is not None and isinstance(r.get("final"), list) and r["final"]
             and float(r["final"][0]) in (0.0, 1.0)]
    print(f"{len(rows)} game markets; settlement matches final price on {np.mean(agree):.0%} of {len(agree)}"
          if agree else f"{len(rows)} game markets; no final prices to check settlement against")
    out = {}
    for lg in sorted({r["league"] for r in rows}):
        for split in ("train", "test"):
            g, mids, ys = defaultdict(list), [], []
            for r in rows:
                p, s = r.get("price"), r.get("settlement")
                if r["league"] != lg or not p or s is None:
                    continue
                d = datetime.fromisoformat(r["end"].replace("Z", "+00:00")).date()
                if (d < SPLIT) != (split == "train"):
                    continue
                bid, ask = p["bid"], p["ask"]
                if not (0 < bid < ask <= 1):
                    continue
                mid, y = (bid + ask) / 2, float(s)
                if not (LO <= mid < HI):
                    mid, y = 1 - mid, 1 - y  # the other side may be the favourite
                    if not (LO <= mid < HI):
                        continue
                g[r["slug"]].append(y - mid)
                mids.append(mid)
                ys.append(y)
            n = len(mids)
            if not n:
                print(f"{lg:<8}{split:<7}{0:>6}")
                out[f"{lg}|{split}"] = {"favs": 0}
                continue
            keys, rng = list(g), random.Random(3)
            boots = sorted(np.mean([x for k in rng.choices(keys, k=len(keys)) for x in g[k]]) for _ in range(2000))
            e, lo, hi = float(np.mean(np.array(ys) - np.array(mids))), boots[50], boots[1949]
            verdict = (("PASS -> stage 2 (research only)" if (e >= 0.03 and lo > 0 and n >= 200) else
                        ("too few" if n < 200 else "fail")) if split == "train" else ("positive" if e > 0 else "not positive"))
            out[f"{lg}|{split}"] = {"favs": n, "edge": e, "lo": lo, "hi": hi, "verdict": verdict}
            print(f"{lg:<8}{split:<7}{n:>6}  mid {np.mean(mids):.2f}  won {np.mean(ys):.2f}  won-mid {e * 100:+.1f}c  "
                  f"CI [{lo * 100:+.1f}, {hi * 100:+.1f}]   {verdict}")
    (DIR / "poly_screen.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    if "--score" not in sys.argv:
        download()
    score()
