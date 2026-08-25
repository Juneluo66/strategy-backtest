"""Full research diagnostics: return timing vs risk timing."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import fetch_prices, load_adj_close
from .hac import ols_newey_west
from .metrics import summary_stats
from .predictive import (
    conditional_forward_table,
    forward_compound_return,
    forward_realized_vol,
    lead_lag_corr,
    predictive_regressions,
)
from .strategy_core import risk_on_signal as gate_signal
from .strategy_core import run_gated_strategy


HORIZONS = (1, 5, 10, 20, 60)
SMA_GRID = (20, 50, 100, 150, 200)
MOM_GRID = (5, 10, 20, 40, 60)
PLACEBOS = ("BTC-USD", "QQQ", "SPY", "IWM", "SOXX")
CRISIS_WINDOWS = {
    "2018Q4": ("2018-10-01", "2018-12-31"),
    "2020_COVID": ("2020-02-15", "2020-04-30"),
    "2022_bear": ("2022-01-01", "2022-12-31"),
}


def _ensure_symbols(config: ProjectConfig, extra: list[str]) -> None:
    """Fetch any missing symbols into the price cache."""
    # temporarily extend symbol list via direct fetch loop
    from .data import cache_path
    import yfinance as yf

    prices_dir = config.prices_dir
    prices_dir.mkdir(parents=True, exist_ok=True)
    start = config.raw["data"]["start"]
    for symbol in extra:
        path = cache_path(prices_dir, symbol)
        if path.exists():
            continue
        frame = yf.download(symbol, start=start, auto_adjust=False, progress=False, threads=False)
        if frame.empty:
            raise ValueError(f"empty download for {symbol}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame = frame.rename_axis("date").reset_index()
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
        frame = frame.set_index("date").sort_index()
        keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in frame.columns]
        frame[keep].to_parquet(path)


def _load_symbol(config: ProjectConfig, symbol: str) -> pd.Series:
    from .data import cache_path

    path = cache_path(config.prices_dir, symbol)
    frame = pd.read_parquet(path)
    s = frame["Adj Close"].astype(float)
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = symbol
    return s


def _sharpe(rets: pd.Series) -> float:
    r = rets.dropna()
    if len(r) < 5 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252))


def _block_bootstrap_sharpes(
    strat: pd.Series,
    qqq: pd.Series,
    *,
    block: int = 21,
    n_boot: int = 2000,
    seed: int = 7,
) -> dict:
    a = pd.concat([strat.rename("s"), qqq.rename("q")], axis=1).dropna()
    s = a["s"].to_numpy()
    q = a["q"].to_numpy()
    n = len(s)
    rng = np.random.default_rng(seed)

    def _idx():
        picks = []
        while len(picks) < n:
            start = int(rng.integers(0, max(n - block + 1, 1)))
            picks.extend(range(start, min(start + block, n)))
        return np.asarray(picks[:n])

    sh_s, sh_q, sh_diff = [], [], []
    for _ in range(n_boot):
        i = _idx()
        ss, qq = s[i], q[i]
        if ss.std() == 0 or qq.std() == 0:
            continue
        hs = ss.mean() / ss.std() * np.sqrt(252)
        hq = qq.mean() / qq.std() * np.sqrt(252)
        sh_s.append(hs)
        sh_q.append(hq)
        sh_diff.append(hs - hq)
    def ci(x):
        x = np.asarray(x, dtype=float)
        return {
            "mean": float(np.mean(x)),
            "p05": float(np.quantile(x, 0.05)),
            "p50": float(np.quantile(x, 0.50)),
            "p95": float(np.quantile(x, 0.95)),
            "p_gt_0": float(np.mean(x > 0)),
        }

    return {
        "block": block,
        "n_boot": n_boot,
        "strategy_sharpe": ci(sh_s),
        "qqq_sharpe": ci(sh_q),
        "sharpe_diff_strategy_minus_qqq": ci(sh_diff),
        "point_strategy": _sharpe(a["s"]),
        "point_qqq": _sharpe(a["q"]),
        "point_diff": _sharpe(a["s"]) - _sharpe(a["q"]),
    }


def run_diagnostics(config: ProjectConfig | None = None) -> dict[str, Any]:
    config = config or ProjectConfig()
    extra = ["IWM", "SOXX", "^VIX"]
    _ensure_symbols(config, extra)
    # also ensure core
    fetch_prices(config, refresh=False)

    prices = load_adj_close(config)
    for sym in extra:
        prices[sym] = _load_symbol(config, sym)

    audit_start = pd.Timestamp(config.raw["data"]["audit_start"])
    sma0 = int(config.raw["rules"]["sma_window"])
    mom0 = int(config.raw["rules"]["momentum_window"])

    qqq = prices["QQQ"]
    shy = prices["SHY"]
    spy = prices["SPY"]
    btc = prices["BTC-USD"]
    vix = prices["^VIX"]

    # Align ETF calendar
    cal = pd.concat([qqq, shy, spy], axis=1).dropna().index
    qqq_r = qqq.reindex(cal).pct_change()
    btc_on_cal = btc.reindex(cal.union(btc.dropna().index)).sort_index().ffill().reindex(cal)
    btc_r = btc_on_cal.pct_change()

    btc_sig = gate_signal(btc, sma_window=sma0, momentum_window=mom0)
    btc_sig_cal = btc_sig.reindex(cal.union(btc_sig.dropna().index)).sort_index().ffill().reindex(cal)

    first_sig = btc_sig.dropna().index.min()
    effective = max(audit_start, pd.Timestamp(first_sig))
    sample_mask = cal >= effective
    sig_s = btc_sig_cal.loc[sample_mask]
    qqq_rs = qqq_r.loc[sample_mask]
    btc_rs = btc_r.loc[sample_mask]

    # --- 1. Conditional forwards ---
    cond = conditional_forward_table(sig_s, qqq_rs, HORIZONS)

    # --- 2. Predictive regressions (univariate) ---
    univ = predictive_regressions(sig_s, qqq_rs, HORIZONS)

    # --- 3. Lead-lag ---
    ll = lead_lag_corr(btc_rs, qqq_rs)

    # --- 4. Placebos ---
    placebos = {}
    for src in PLACEBOS:
        px = prices[src] if src in prices.columns else _load_symbol(config, src)
        bt = run_gated_strategy(
            px, qqq, shy, sma_window=sma0, momentum_window=mom0, audit_start=audit_start
        )
        placebos[src] = {
            "effective_start": str(bt["effective_start"].date()),
            "stats": bt["stats_strategy"],
            "qqq_stats": bt["stats_qqq"],
            "sharpe": bt["stats_strategy"].get("sharpe"),
            "cagr": bt["stats_strategy"].get("cagr"),
            "max_dd": bt["stats_strategy"].get("max_drawdown"),
            "ann_vol": bt["stats_strategy"].get("ann_vol"),
            "pct_qqq": float((bt["position"] == "QQQ").mean()),
        }

    # --- 5. Controls: QQQ trend, SPY trend, VIX ---
    qqq_trend = gate_signal(qqq, sma_window=sma0, momentum_window=mom0).map(
        {True: 1.0, False: 0.0, pd.NA: np.nan}
    ).astype(float)
    spy_trend = gate_signal(spy, sma_window=sma0, momentum_window=mom0).map(
        {True: 1.0, False: 0.0, pd.NA: np.nan}
    ).astype(float)
    vix_lvl = vix.reindex(cal).ffill()
    # standardize VIX a bit for coefficient readability (z-score in sample)
    vix_s = vix_lvl.loc[sample_mask]
    vix_z = (vix_s - vix_s.mean()) / vix_s.std(ddof=1)

    controls_q = pd.DataFrame({"qqq_trend": qqq_trend.reindex(cal).loc[sample_mask]})
    controls_full = pd.DataFrame(
        {
            "qqq_trend": qqq_trend.reindex(cal).loc[sample_mask],
            "spy_trend": spy_trend.reindex(cal).loc[sample_mask],
            "vix_z": vix_z,
        }
    )
    incr_qqq = predictive_regressions(sig_s, qqq_rs, HORIZONS, controls=controls_q)
    incr_full = predictive_regressions(sig_s, qqq_rs, HORIZONS, controls=controls_full)

    # Also: |R| and realized vol as dependent vars for risk-timing test (k=20)
    abs_dep = qqq_rs.abs()
    Xsig = pd.DataFrame(
        {
            "const": 1.0,
            "btc_signal": sig_s.map({True: 1.0, False: 0.0, pd.NA: np.nan}).astype(float),
        }
    )
    # next-day |r|
    vol_timing_1 = ols_newey_west(abs_dep.shift(-1), Xsig, lags=5)
    vol_timing_1["dep"] = "|R_QQQ_{t+1}|"
    fwd_vol20 = forward_realized_vol(qqq_rs, 20)
    vol_timing_20 = ols_newey_west(fwd_vol20, Xsig, lags=20)
    vol_timing_20["dep"] = "RV_QQQ_{t+1:t+20}"

    # --- 6. Yearly active return attribution (strategy - QQQ) ---
    base = run_gated_strategy(
        btc, qqq, shy, sma_window=sma0, momentum_window=mom0, audit_start=audit_start
    )
    active = (base["strategy_return"] - base["qqq_return"]).dropna()
    by_year = active.groupby(active.index.year).agg(["sum", "mean", "count"])
    by_year.columns = ["sum_active", "mean_daily_active", "n"]
    # cumulative contribution share (only negative active years matter for "protection")
    # share of total positive contribution to -active when strategy underperforms QQQ on CAGR:
    # Look at years where active sum helps relative drawdown: when QQQ has bad years and active>0
    yearly = []
    for y, row in by_year.iterrows():
        yearly.append(
            {
                "year": int(y),
                "sum_active": float(row["sum_active"]),
                "n": int(row["n"]),
                "strategy_sharpe": _sharpe(base["strategy_return"][base["strategy_return"].index.year == y]),
                "qqq_sharpe": _sharpe(base["qqq_return"][base["qqq_return"].index.year == y]),
                "strategy_cagr_approx": float(
                    (1 + base["strategy_return"][base["strategy_return"].index.year == y]).prod() - 1
                ),
                "qqq_cagr_approx": float(
                    (1 + base["qqq_return"][base["qqq_return"].index.year == y]).prod() - 1
                ),
            }
        )

    # --- 7. Leave-one-crisis-out ---
    loco = {}
    full_s = base["strategy_return"]
    full_q = base["qqq_return"]
    for name, (a, b) in CRISIS_WINDOWS.items():
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        mask = ~((full_s.index >= a) & (full_s.index <= b))
        loco[name] = {
            "removed": [str(a.date()), str(b.date())],
            "strategy_sharpe": _sharpe(full_s.loc[mask]),
            "qqq_sharpe": _sharpe(full_q.loc[mask]),
            "strategy_stats": summary_stats(full_s.loc[mask]),
            "qqq_stats": summary_stats(full_q.loc[mask]),
        }
    # drop best calendar year by strategy - qqq active sum
    best_year = max(yearly, key=lambda r: r["sum_active"])["year"]
    mask = full_s.index.year != best_year
    loco[f"drop_best_year_{best_year}"] = {
        "removed": [str(best_year)],
        "strategy_sharpe": _sharpe(full_s.loc[mask]),
        "qqq_sharpe": _sharpe(full_q.loc[mask]),
        "strategy_stats": summary_stats(full_s.loc[mask]),
        "qqq_stats": summary_stats(full_q.loc[mask]),
    }
    # drop best 63 trading days by rolling active
    roll = active.rolling(63).sum()
    if roll.notna().any():
        end = roll.idxmax()
        # find window end at `end` covering 63 days
        loc = full_s.index.get_loc(end)
        start_loc = max(0, int(loc) - 62)
        drop_idx = full_s.index[start_loc : int(loc) + 1]
        mask = ~full_s.index.isin(drop_idx)
        loco["drop_best_63d_active"] = {
            "removed": [str(drop_idx[0].date()), str(drop_idx[-1].date())],
            "strategy_sharpe": _sharpe(full_s.loc[mask]),
            "qqq_sharpe": _sharpe(full_q.loc[mask]),
            "strategy_stats": summary_stats(full_s.loc[mask]),
            "qqq_stats": summary_stats(full_q.loc[mask]),
        }

    # --- 8. Parameter grid (Sharpe surface) ---
    grid_rows = []
    for sma in SMA_GRID:
        for mom in MOM_GRID:
            try:
                bt = run_gated_strategy(
                    btc, qqq, shy, sma_window=sma, momentum_window=mom, audit_start=audit_start
                )
                grid_rows.append(
                    {
                        "sma": sma,
                        "mom": mom,
                        "sharpe": bt["stats_strategy"].get("sharpe"),
                        "cagr": bt["stats_strategy"].get("cagr"),
                        "max_dd": bt["stats_strategy"].get("max_drawdown"),
                        "ann_vol": bt["stats_strategy"].get("ann_vol"),
                        "is_frozen_50_20": sma == 50 and mom == 20,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                grid_rows.append({"sma": sma, "mom": mom, "error": str(exc)})
    grid = pd.DataFrame(grid_rows)
    sharpe_pivot = grid.pivot(index="sma", columns="mom", values="sharpe") if "sharpe" in grid else None

    # --- 9. Walk-forward (contaminated research note) ---
    splits = {
        "discovery_2014_2018": ("2014-11-05", "2018-12-31"),
        "validation_2019_2022": ("2019-01-01", "2022-12-31"),
        "locked_oos_2023_2026": ("2023-01-01", "2026-12-31"),
    }
    walk = {}
    for name, (a, b) in splits.items():
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        m = (full_s.index >= a) & (full_s.index <= b)
        walk[name] = {
            "window": [str(a.date()), str(b.date())],
            "strategy": summary_stats(full_s.loc[m]),
            "qqq": summary_stats(full_q.loc[m]),
            "note": "ENTIRE_SPAN_IS_RESEARCH_CONTAMINATED_after_seeing_full_sample",
        }

    # --- 10. Bootstrap Sharpe ---
    boot = _block_bootstrap_sharpes(full_s, full_q, block=21, n_boot=2000)

    # --- 11. Simple CAPM alpha (strategy excess vs SPY excess; rf≈0 for speed) ---
    spy_r = spy.reindex(full_s.index).pct_change().fillna(0.0)
    aligned = pd.concat([full_s.rename("s"), spy_r.rename("mkt")], axis=1).dropna()
    # use SHY as crude rf proxy on same days when in sample — optional; keep rf=0
    X = pd.DataFrame({"const": 1.0, "mkt": aligned["mkt"]})
    capm = ols_newey_west(aligned["s"], X, lags=10)
    capm["note"] = "rf_approx_0; dynamic_beta_caveat_applies"

    # Judgment
    # Extract k=20 univ beta t
    univ20 = next((u for u in univ if u.get("horizon") == 20), {})
    incr20 = next((u for u in incr_qqq if u.get("horizon") == 20), {})
    full20 = next((u for u in incr_full if u.get("horizon") == 20), {})
    beta_univ = (univ20.get("coef") or {}).get("btc_signal", np.nan)
    t_univ = (univ20.get("t_stat") or {}).get("btc_signal", np.nan)
    beta_ctrl = (incr20.get("coef") or {}).get("btc_signal", np.nan)
    t_ctrl = (incr20.get("t_stat") or {}).get("btc_signal", np.nan)
    beta_full = (full20.get("coef") or {}).get("btc_signal", np.nan)
    t_full = (full20.get("t_stat") or {}).get("btc_signal", np.nan)

    placebo_sharpes = {k: v.get("sharpe") for k, v in placebos.items()}
    btc_sh = placebo_sharpes.get("BTC-USD")
    qqq_sh = placebo_sharpes.get("QQQ")
    similar_placebo = (
        btc_sh is not None
        and qqq_sh is not None
        and abs(btc_sh - qqq_sh) < 0.15
    )

    cond20 = cond[cond["k"] == 20].iloc[0].to_dict() if (cond["k"] == 20).any() else {}
    return_edge = abs(cond20.get("delta_R", 0)) 
    vol_edge = cond20.get("delta_vol", 0)  # expect negative if ON has lower vol

    if similar_placebo and (not np.isfinite(t_ctrl) or abs(t_ctrl) < 2) and vol_edge < 0:
        judgment = "PRIMARILY_RISK_TIMING_BTC_LIKELY_PROXY_FOR_TREND_RISK_FILTER"
    elif (
        np.isfinite(t_full)
        and t_full > 2
        and not similar_placebo
        and np.isfinite(vol_timing_20.get("t_stat", {}).get("btc_signal", np.nan))
        and vol_timing_20["t_stat"]["btc_signal"] < -2
    ):
        judgment = (
            "MIXED_IN_SAMPLE_RETURN_AND_RISK_TIMING__"
            "RISK_CHANNEL_STRONGER__BTC_BEATS_PLACEBOS__TRUE_OOS_REQUIRED"
        )
    elif np.isfinite(t_full) and t_full > 2 and not similar_placebo:
        judgment = "POSSIBLE_INCREMENTAL_RETURN_SIGNAL_NEEDS_TRUE_OOS"
    else:
        judgment = "MIXED_LEAN_RISK_TIMING_NO_CLEAR_INCREMENTAL_BTC_ALPHA"

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "effective_sample": [str(effective.date()), str(cal[sample_mask][-1].date())],
        "frozen_rules": {"sma": sma0, "mom": mom0},
        "sample_label": "DISCOVERY_SAMPLE_RESEARCH_CONTAMINATED",
        "judgment": judgment,
        "conditional_forwards": cond.to_dict(orient="records"),
        "predictive_univariate": univ,
        "predictive_control_qqq_trend": incr_qqq,
        "predictive_control_full": incr_full,
        "vol_timing_regs": [vol_timing_1, vol_timing_20],
        "lead_lag": ll.to_dict(orient="records"),
        "placebos": placebos,
        "yearly_active": yearly,
        "leave_one_crisis_out": loco,
        "param_grid": grid.to_dict(orient="records"),
        "param_grid_sharpe_pivot": sharpe_pivot.to_dict() if sharpe_pivot is not None else {},
        "walk_forward": walk,
        "bootstrap_sharpe": boot,
        "capm": capm,
        "key_tests": {
            "univ_k20_beta": beta_univ,
            "univ_k20_t": t_univ,
            "ctrl_qqq_trend_k20_beta": beta_ctrl,
            "ctrl_qqq_trend_k20_t": t_ctrl,
            "ctrl_full_k20_beta": beta_full,
            "ctrl_full_k20_t": t_full,
            "placebo_sharpes": placebo_sharpes,
            "cond_k20": cond20,
        },
    }
    return payload
