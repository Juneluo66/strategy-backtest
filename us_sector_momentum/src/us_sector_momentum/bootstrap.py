"""Block bootstrap for strategy-minus-SPY CAGR difference (preserves serial dependence)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def block_bootstrap_cagr_diff(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    n_boot: int = 400,
    block: int = 21,
    seed: int = 42,
) -> dict:
    """
    Moving-block bootstrap of paired daily returns; estimate CAGR(strategy) - CAGR(bench).

    Forbidden: i.i.d. daily bootstrap that breaks time-series structure.
    """
    aligned = pd.concat(
        [strategy.rename("s"), benchmark.rename("b")], axis=1
    ).dropna()
    n = len(aligned)
    empty = {
        "n": n,
        "n_boot": n_boot,
        "block": block,
        "seed": seed,
        "observed_cagr_diff": np.nan,
        "mean_cagr_diff": np.nan,
        "ci_2_5": np.nan,
        "ci_97_5": np.nan,
        "p_diff_positive": np.nan,
        "method": "moving_block_bootstrap_paired_returns",
    }
    if n < block * 3:
        return empty

    s = aligned["s"].to_numpy()
    b = aligned["b"].to_numpy()
    years = n / 252.0

    def _cagr(rets: np.ndarray) -> float:
        nav = np.cumprod(1.0 + rets)
        if years <= 0 or nav[-1] <= 0:
            return float("nan")
        return float(nav[-1] ** (1.0 / years) - 1.0)

    observed = _cagr(s) - _cagr(b)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    diffs = []
    for _ in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        idx = np.concatenate([np.arange(st, st + block) for st in starts])[:n]
        diffs.append(_cagr(s[idx]) - _cagr(b[idx]))
    arr = np.asarray(diffs, dtype=float)
    return {
        "n": n,
        "n_boot": n_boot,
        "block": block,
        "seed": seed,
        "observed_cagr_diff": float(observed),
        "mean_cagr_diff": float(np.nanmean(arr)),
        "ci_2_5": float(np.nanpercentile(arr, 2.5)),
        "ci_97_5": float(np.nanpercentile(arr, 97.5)),
        "p_diff_positive": float(np.mean(arr > 0)),
        "method": "moving_block_bootstrap_paired_returns",
    }
