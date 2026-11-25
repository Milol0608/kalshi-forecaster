"""Freeze the D1c decider (trees + GFS/ECMWF forecasts) for the live paper test (ADR 0007).

Same recipe as app/backtest/d1_decider.py (HistGradientBoosting depth 3, 200 rounds, lr 0.05, same features, city
forecast bias/error measured before 2026-03-01), refitted on every daily-high market with an 8pm price up to the end
of the downloaded data. The trees are written as plain JSON so the hosted bot needs no scikit-learn.

  uv run --with scikit-learn python -m app.backtest.d1_export
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from app.backtest import d1_decider as d1
from app.execution.decider import MODEL_FILE, features, predict_raw


def main() -> None:
    rows = d1.load()
    cities = sorted({r["city"] for r in rows})
    fit = [r for r in rows if 0.01 <= (r["bid"] + r["ask"]) / 2 <= 0.99 and r["p_fc"] is not None]
    X, y = d1.features(fit, cities, True), np.array([r["y"] for r in fit])
    m = HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05, random_state=0).fit(X, y)
    trees = []
    for it in m._predictors:
        n = it[0].nodes
        trees.append({"f": n["feature_idx"].tolist(), "t": n["num_threshold"].tolist(), "l": n["left"].tolist(),
                      "r": n["right"].tolist(), "leaf": n["is_leaf"].astype(int).tolist(), "v": n["value"].tolist()})
    # forecast bias and error size per city, exactly as d1.load() computes them (days before ERR_END)
    err = {}
    for c in cities:
        f, o = d1.CACHE / f"forecasts2_{c}.json", d1.CACHE / f"obs_{c}.json"
        fc = json.loads(f.read_text()) if f.exists() else {}
        obs = json.loads(o.read_text()) if o.exists() else {}
        res = [obs[k] - (v["gfs2"] + v["ecmwf2"]) / 2 for k, v in fc.items()
               if k < d1.ERR_END.isoformat() and k in obs and "gfs2" in v and "ecmwf2" in v]
        err[c] = [float(np.mean(res)), max(1.5, float(np.std(res)))] if len(res) >= 60 else [0.0, 3.0]
    model = {"version": "D1c-trees-v1", "theta": 0.02, "cities": cities, "err": err,
             "baseline": float(np.ravel(m._baseline_prediction)[0]), "trees": trees,
             "fitted_on": len(fit), "fitted_through": max(r["day"] for r in fit).isoformat(),
             "exported": date.today().isoformat()}
    # self-check: the JSON trees must reproduce scikit-learn's probabilities
    idx = np.random.default_rng(0).choice(len(X), 200, replace=False)
    want = m.predict_proba(X[idx])[:, 1]
    got = np.array([predict_raw(model, list(x)) for x in X[idx]])
    assert np.max(np.abs(want - got)) < 1e-9, np.max(np.abs(want - got))
    # and the live feature code must rebuild the backtest's feature rows from raw inputs
    for k in idx:
        r = fit[k]
        live = features(model, r["bid"], r["ask"], r["day"], r["city"], r["lo"], r["hi"], r["fc"]["gfs2"],
                        r["fc"]["ecmwf2"])
        assert np.max(np.abs(np.array(live) - X[k])) < 1e-9, (r["ticker"], live, X[k])
    model["check"] = {"x": X[idx[:5]].tolist(), "p": want[:5].tolist()}
    MODEL_FILE.write_text(json.dumps(model))
    print(f"fitted on {len(fit)} markets through {model['fitted_through']}; {len(trees)} trees; "
          f"max |diff| vs sklearn {np.max(np.abs(want - got)):.1e}; wrote {MODEL_FILE}")


if __name__ == "__main__":
    main()
