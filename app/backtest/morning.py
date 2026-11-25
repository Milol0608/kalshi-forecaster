"""K6 (alpaca-trader/docs/RESEARCH.md): K2's B1 favourites rule posted at 8am on the market's day instead of 8pm the
evening before. Same fills, same bar, plus the held-out Aug-Nov check.

  uv run python -m app.backtest.morning
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

import numpy as np

from app.backtest.data import CACHE, event_date
from app.backtest.makers import boot_ci, filled, pnl

LO, HI = 0.65, 0.95
TEST_START, LATER_HALF, HELD_OUT = date(2026, 3, 1), date(2026, 7, 1), date(2026, 8, 1)


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load_tapes() -> dict[str, list]:
    tape = {}
    for path in (CACHE / "trades.jsonl", CACHE / "trades_am.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            tape[r["ticker"]] = r["trades"]
    return tape


def orders(when: str) -> dict[str, dict]:
    prices = json.loads((CACHE / "prices.json").read_text(encoding="utf-8"))
    out = {}
    for m in json.loads((CACHE / "markets_kept.json").read_text(encoding="utf-8")):
        d = event_date(m["event_ticker"])
        pr = (prices.get(m["ticker"]) or {}).get(when)
        if not d or d < TEST_START or not pr or m.get("result") not in ("yes", "no"):
            continue
        bid, ask = float(pr["bid"]), float(pr["ask"])
        if LO <= (bid + ask) / 2 < HI and 0 < bid < ask <= 1:
            out[m["ticker"]] = {"day": d, "event": m["event_ticker"], "bid": bid, "ask": ask, "t": int(pr["t"]),
                                "y": 1 if m["result"] == "yes" else 0}
    return out


def score(label: str, book: dict[str, dict], tape: dict[str, list]) -> dict[str, float]:
    fills, groups, late, held, everything, missing = [], defaultdict(list), [], [], [], 0
    for tk, o in book.items():
        if tk not in tape:
            missing += 1
            continue
        trades = [t for t in tape[tk] if ts(t[0]) >= o["t"]]
        everything.append(pnl("buy", o["bid"], o["y"]))
        if filled("buy", o["bid"], trades, True):
            v = pnl("buy", o["bid"], o["y"])
            fills.append(v)
            groups[o["event"]].append(v)
            if o["day"] >= LATER_HALF:
                late.append(v)
            if o["day"] >= HELD_OUT:
                held.append(v)
    lo, hi = boot_ci(groups) if fills else (0.0, 0.0)
    m = lambda x: float(np.mean(x) * 100) if x else 0.0  # noqa: E731
    print(f"{label:<22} posted {len(everything):>4} (no tape {missing}), filled {len(fills):>4} "
          f"({len(fills) / max(1, len(everything)):.0%})  c/fill {m(fills):+.2f}  CI [{lo * 100:+.2f}, {hi * 100:+.2f}]  "
          f"Jul-Nov {m(late):+.2f} (n={len(late)})  Aug-Nov {m(held):+.2f} (n={len(held)})  if all filled {m(everything):+.2f}")
    return {"fills": len(fills), "c": m(fills), "lo": lo * 100, "hi": hi * 100, "late": m(late), "held": m(held)}


def main() -> None:
    tape = load_tapes()
    am, eve = orders("am"), orders("eve")
    a = score("8am B1 (K6)", am, tape)
    score("8pm B1 (K2, same code)", eve, tape)
    both = set(am) & set(eve)
    print(f"overlap: {len(both)} markets are favourites at both times ({len(both) / max(1, len(am)):.0%} of 8am orders)")
    score("8am, not at 8pm", {k: v for k, v in am.items() if k not in eve}, tape)
    ok = a["c"] > 0 and a["lo"] > 0 and a["late"] > 0 and a["fills"] >= 100 and a["held"] > 0
    print(f"K6 verdict: {'PASS' if ok else ('NOT ENOUGH DATA' if a['fills'] < 100 else 'FAIL')}")


if __name__ == "__main__":
    main()
