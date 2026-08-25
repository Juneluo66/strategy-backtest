"""Pre-registered robustness: costs, delay, endpoints, rolling, LOO, bootstrap."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .metrics import rich_metrics, metric_c_relative_stats
from .schedules import SECTORS, run_ew9_version, VERSION_FREQ


def clip_equity(equity: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    eq = equity
    if start is not None:
        eq = eq.loc[eq.index >= pd.Timestamp(start)]
    if end is not None and end != "latest":
        eq = eq.loc[eq.index <= pd.Timestamp(end)]
    return eq


def rolling_win_rates(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    years: int,
    step: int = 63,
) -> dict:
    idx = strategy.index.intersection(benchmark.index).sort_values()
    span = years * 252
    wins = 0
    n = 0
    for st in idx[::step]:
        pos = idx.get_indexer([st])[0]
        en_pos = pos + span
        if en_pos >= len(idx):
            continue
        w = idx[pos : en_pos + 1]
        if len(w) < span * 0.9:
            continue
        s = (1 + strategy.reindex(w)).prod() - 1
        b = (1 + benchmark.reindex(w)).prod() - 1
        n += 1
        if s > b:
            wins += 1
    return {"n": n, "win_rate": (wins / n) if n else np.nan, "years": years}


def leave_one_out(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    version: str = "EW9_monthly",
    one_way_bps: float = 5.0,
) -> dict:
    out = {}
    for drop in SECTORS:
        keep = [s for s in SECTORS if s != drop]
        run = run_ew9_version(
            opens, closes, version, one_way_bps=one_way_bps, symbols=keep
        )
        net = run["equity"]["net_return"]
        years = max((net.index.max() - net.index.min()).days / 365.25, 1 / 12)
        nav = (1 + net).cumprod()
        out[drop] = {
            "cagr": float(nav.iloc[-1] ** (1 / years) - 1),
            "final_wealth": float(nav.iloc[-1]),
            "max_drawdown": float((nav / nav.cummax() - 1).min()),
            "n_sectors": len(keep),
        }
    return out


def block_bootstrap_cagr_edge(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    n_boot: int = 500,
    block: int = 21,
    seed: int = 42,
) -> dict:
    aligned = pd.concat([strategy.rename("s"), benchmark.rename("b")], axis=1).dropna()
    if len(aligned) < block * 5:
        return {"status": "INSUFFICIENT"}
    rng = np.random.default_rng(seed)
    excess = (aligned["s"] - aligned["b"]).to_numpy()
    n = len(excess)
    edges = []
    for _ in range(n_boot):
        picks = []
        while len(picks) < n:
            start = rng.integers(0, n - block + 1)
            picks.extend(excess[start : start + block].tolist())
        arr = np.asarray(picks[:n])
        # Approximate CAGR edge via compounded excess path (diagnostic)
        nav = np.cumprod(1.0 + arr)
        years = n / 252.0
        edges.append(float(nav[-1] ** (1 / years) - 1))
    arr = np.asarray(edges)
    return {
        "status": "OK",
        "n_boot": n_boot,
        "block": block,
        "mean_edge": float(arr.mean()),
        "p05": float(np.quantile(arr, 0.05)),
        "p50": float(np.quantile(arr, 0.50)),
        "p95": float(np.quantile(arr, 0.95)),
        "frac_positive": float((arr > 0).mean()),
    }
