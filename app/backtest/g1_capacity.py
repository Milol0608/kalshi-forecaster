"""G1 (alpaca-trader/docs/RESEARCH.md): how B1's ¼ / ½ Kelly result scales with the bankroll.

  uv run python -m app.backtest.g1_capacity

Re-runs the D1/S1 money rule on the saved Aug–Nov 2026 B1 fills (data/backtest/d1/result.json, which carry each
order's through-volume) at bigger starting bankrolls. Writes data/backtest/g1/result.json.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUT = Path("data/backtest/g1")
BANKS = (100, 300, 1_000, 3_000, 10_000, 30_000)
EDGE = 0.0342


def money(fills: list[dict], start: float, kelly: float, cap: int | None) -> dict:
    bank = peak = start
    worst, capped, orders, contracts = 0.0, 0, 0, 0
    by_day = defaultdict(list)
    for f in fills:
        by_day[f["day"]].append(f)
    for d in sorted(by_day):
        spend = pnl = 0.0
        for f in by_day[d]:
            cost = f["price"] if f["side"] == "buy" else 1 - f["price"]
            frac = min(0.05, kelly * EDGE / max(1e-6, 1 - cost))
            want = frac * bank / cost
            limit = 0.25 * f["thru"] if cap is None else min(0.25 * f["thru"], cap)
            n = int(min(want, limit))
            n = min(n, int(max(0.0, 0.25 * bank - spend) / cost))
            if n <= 0:
                continue
            orders += 1
            capped += want > limit
            contracts += n
            spend += n * cost
            pnl += n * f["v"]
        bank += pnl
        peak = max(peak, bank)
        worst = max(worst, 1 - bank / peak)
    return {"start": start, "end": round(bank, 2), "return": round(bank / start - 1, 4), "profit": round(bank - start, 2),
            "worst_drop": round(worst, 3), "orders": orders, "volume_capped_share": round(capped / max(orders, 1), 3),
            "contracts": contracts}


def main() -> None:
    fills = json.loads(Path("data/backtest/d1/result.json").read_text(encoding="utf-8"))["test_fills"]["D1a B1 rule"]
    print(f"{len(fills)} B1 fills, Aug-Nov 2026")
    res = {}
    print(f"{'sizing':<22}{'start':>8}{'end':>11}{'return':>8}{'profit':>10}{'drop':>6}{'capped':>8}")
    for kelly in (0.25, 0.5):
        for cap in (500, None):
            key = f"{kelly:g} Kelly, {'500 cap' if cap else 'no cap'}"
            rows = [money(fills, b, kelly, cap) for b in BANKS]
            base = rows[0]["return"]
            ok = [r["start"] for r in rows if r["return"] >= base / 2]
            res[key] = {"rows": rows, "capacity": max(ok) if ok else None}
            for r in rows:
                print(f"{key:<22}{r['start']:>8,}{r['end']:>11,.2f}{r['return']:>8.1%}{r['profit']:>10,.2f}"
                      f"{r['worst_drop']:>6.0%}{r['volume_capped_share']:>8.0%}")
            print(f"  -> capacity (return >= half of $100's): ${res[key]['capacity']:,}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
