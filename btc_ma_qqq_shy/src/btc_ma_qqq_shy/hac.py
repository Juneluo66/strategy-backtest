"""Newey-West HAC OLS (no statsmodels dependency)."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


def _nw_lags(n: int, lags: Optional[int]) -> int:
    if lags is not None:
        return max(int(lags), 0)
    return max(int(np.floor(4 * (n / 100.0) ** (2 / 9))), 1)


def ols_newey_west(
    y: pd.Series,
    X: pd.DataFrame,
    *,
    lags: Optional[int] = None,
) -> dict:
    """
    y = X β + ε with HAC (Bartlett) covariance on coefficients.
    X should include a constant column named 'const' if intercept desired.
    """
    frame = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(frame) < X.shape[1] + 5:
        return {"n": int(len(frame)), "ok": False}
    yv = frame["y"].to_numpy(dtype=float)
    xv = frame.drop(columns=["y"]).to_numpy(dtype=float)
    names = list(frame.drop(columns=["y"]).columns)
    n, k = xv.shape
    # β = (X'X)^{-1} X'y
    xtx = xv.T @ xv
    try:
        xtx_inv = np.linalg.inv(xtx)
    except np.linalg.LinAlgError:
        return {"n": n, "ok": False}
    beta = xtx_inv @ (xv.T @ yv)
    resid = yv - xv @ beta
    L = _nw_lags(n, lags)
    # S = Γ0 + sum_l w_l (Γl + Γl')
    score = xv * resid[:, None]  # n x k
    gamma0 = (score.T @ score) / n
    S = gamma0.copy()
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        g = (score[lag:].T @ score[:-lag]) / n
        S += w * (g + g.T)
    cov = xtx_inv @ (S * n) @ xtx_inv  # sandwich; note S already /n so *n restores
    # Standard Newey-West: Var(β̂) = (X'X/n)^{-1} S (X'X/n)^{-1} / n
    # = (X'X)^{-1} (n S) (X'X)^{-1}  when S = sum of gamma with /n
    # Actually classic: V = (X'X)^{-1} * Ξ * (X'X)^{-1} where Ξ = n * S_hat and S_hat uses 1/n.
    # Equivalently V = (X'X)^{-1} (n S) (X'X)^{-1}. Yes.
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    tstats = beta / se
    dfs = max(n - k, 1)
    pvals = 2 * (1 - stats.t.cdf(np.abs(tstats), df=dfs))
    out = {
        "ok": True,
        "n": int(n),
        "lags": int(L),
        "coef": {names[i]: float(beta[i]) for i in range(k)},
        "se": {names[i]: float(se[i]) for i in range(k)},
        "t_stat": {names[i]: float(tstats[i]) for i in range(k)},
        "p_value": {names[i]: float(pvals[i]) for i in range(k)},
        "r2": float(1.0 - np.sum(resid**2) / np.sum((yv - yv.mean()) ** 2))
        if np.var(yv) > 0
        else np.nan,
    }
    return out
