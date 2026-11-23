"""Backtest forecast models. All give P(settled whole-degree high falls in each bucket).

  current  v1.1 analogue: mean of bias-corrected GFS and ECMWF day-ahead highs, Gaussian with
           sd = recent error SD. Bias and SD use only the 30 days before the target date,
           exactly like live v1.1. (Live v1.1 uses ensemble members, which aren't archived.)
  emos     v2 (spec 5.5): per-station non-homogeneous Gaussian regression,
             mean = a + b*gfs + c*ecmwf,  log sd = d + e*log(1 + |gfs - ecmwf|)
           fitted by minimising CRPS on the training period only.
  blend    logistic mix of emos and the market's mid, fitted on the training period:
             logit p = k0 + k1*logit(p_emos) + k2*logit(p_market), then renormalised per event.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

EPS = 1e-4


def bucket_probs(mu: float, sd: float, ranges: list[tuple[float, float]]) -> np.ndarray:
    """P(round(T) in [lo, hi]) for T ~ N(mu, sd): integer readings, so edges at +-0.5."""
    sd = max(sd, 0.3)
    lo = np.array([r[0] - 0.5 for r in ranges])
    hi = np.array([r[1] + 0.5 for r in ranges])
    p = norm.cdf((hi - mu) / sd) - norm.cdf((lo - mu) / sd)
    p = np.clip(p, EPS, 1.0)
    return p / p.sum()


def crps_gaussian(y: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


@dataclass
class Emos:
    params: np.ndarray  # a, b, c, d, e

    def predict(self, gfs: np.ndarray, ecmwf: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a, b, c, d, e = self.params
        mu = a + b * gfs + c * ecmwf
        sd = np.exp(d + e * np.log1p(np.abs(gfs - ecmwf)))
        return mu, sd


def fit_emos(gfs: np.ndarray, ecmwf: np.ndarray, obs: np.ndarray) -> Emos:
    def loss(p: np.ndarray) -> float:
        mu, sd = Emos(p).predict(gfs, ecmwf)
        return float(np.mean(crps_gaussian(obs, mu, sd)))

    start = np.array([0.0, 0.5, 0.5, np.log(2.5), 0.0])
    res = minimize(loss, start, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-4, "fatol": 1e-6})
    return Emos(res.x)


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


@dataclass
class Blend:
    params: np.ndarray  # k0, k1 (model), k2 (market)

    def predict(self, p_model: np.ndarray, p_market: np.ndarray) -> np.ndarray:
        k0, k1, k2 = self.params
        return 1 / (1 + np.exp(-(k0 + k1 * logit(p_model) + k2 * logit(p_market))))


def fit_blend(p_model: np.ndarray, p_market: np.ndarray, y: np.ndarray) -> Blend:
    def loss(k: np.ndarray) -> float:
        p = np.clip(Blend(k).predict(p_model, p_market), EPS, 1 - EPS)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    res = minimize(loss, np.array([0.0, 0.5, 0.5]), method="Nelder-Mead", options={"maxiter": 4000})
    return Blend(res.x)
