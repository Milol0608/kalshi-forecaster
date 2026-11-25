"""K12 (alpaca-trader/docs/RESEARCH.md): buy hourly-temperature favourites at the ask, Kalshi taker fee included.
Scores K11's rows; no new data.   uv run python -m app.backtest.k12_taker"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime

import numpy as np

from app.backtest import k7_screen as k7
from app.backtest.k11_hourly import DIR, HALF, is_fav


def fee(p: float, lots: int) -> float:
    return math.ceil(0.07 * lots * p * (1 - p) * 100 - 1e-9) / 100 / lots


def main() -> None:
    rows = [json.loads(x) for x in (DIR / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {}
    for label, pick in (("8 unseen cities", lambda r: r.get("stage1")), ("Miami", lambda r: not r.get("stage1"))):
        g, nets, nets1, halves, buys = defaultdict(list), [], [], defaultdict(list), []
        for r in rows:
            if not pick(r) or not is_fav(r.get("price")):
                continue
            ask, y = float(r["price"]["ask"]), 1 if r["result"] == "yes" else 0
            if ask >= 1:
                continue
            v = y - ask - 0.07 * ask * (1 - ask)
            nets.append(v)
            nets1.append(y - ask - fee(ask, 1))
            g[r["event"]].append(v)
            d = datetime.fromisoformat(r["close_time"].replace("Z", "+00:00")).date()
            halves["before Oct" if d < HALF else "Oct-Nov"].append(v)
            buys.append({"day": d.isoformat(), "v": v, "side": "buy", "price": ask, "edge": None, "thru": 1e9,
                         "series": r["series"]})
        lo, hi = k7.boot(g)
        e = float(np.mean(nets))
        ok = e >= 0.02 and lo > 0 and len(nets) >= 200 and len(halves) == 2 and all(np.mean(v) > 0 for v in halves.values())
        out[label] = {"buys": len(nets), "net": e, "lo": lo, "hi": hi, "net_1lot": float(np.mean(nets1)),
                      "halves": {k: [len(v), float(np.mean(v))] for k, v in halves.items()}, "pass": ok, "list": buys}
        print(f"{label:<16} buys {len(nets):>5}  net {e * 100:+.2f}c (1-lot {np.mean(nets1) * 100:+.2f}c)  CI [{lo * 100:+.2f}, "
              f"{hi * 100:+.2f}]  halves { {k: (len(v), round(float(np.mean(v)) * 100, 2)) for k, v in halves.items()} }"
              f"  {'PASS' if ok else 'FAIL'}{'' if label.startswith('8') else ' (Miami: reported only)'}")
    (DIR / "k12.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
