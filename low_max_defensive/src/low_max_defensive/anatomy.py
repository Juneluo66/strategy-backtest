"""Low-MAX portfolio anatomy vs historical universe (no PIT fundamentals)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from max_effect_vix.factors import max_factor


def _mom_12_1(closes: pd.DataFrame) -> pd.DataFrame:
    """12-1 momentum: return from t-252 to t-21."""
    return closes.shift(21) / closes.shift(252) - 1


def _downside_vol(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    neg = returns.where(returns < 0, 0.0)
    return neg.rolling(window, min_periods=max(window // 2, 10)).std() * np.sqrt(252)


def _recent_dd(closes: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    roll_max = closes.rolling(window, min_periods=window // 2).max()
    return closes / roll_max - 1


def anatomy_table(
    closes: pd.DataFrame,
    holdings: pd.DataFrame,
    membership_on,
    lookback: int,
    top_returns: int,
) -> pd.DataFrame:
    """Monthly cross-section: Low-MAX holdings mean traits minus universe mean traits."""
    returns = closes.pct_change(fill_method=None)
    traits = {
        "realized_vol_20d": returns.rolling(20, min_periods=15).std() * np.sqrt(252),
        "realized_vol_60d": returns.rolling(60, min_periods=40).std() * np.sqrt(252),
        "realized_vol_252d": returns.rolling(252, min_periods=126).std() * np.sqrt(252),
        "beta_60d": _rolling_beta(returns, closes, 60),
        "beta_252d": _rolling_beta(returns, closes, 252),
        "mom_12_1": _mom_12_1(closes),
        "downside_vol_60d": _downside_vol(returns, 60),
        "recent_drawdown_252d": _recent_dd(closes, 252),
        "max_factor": returns.apply(max_factor, lookback=lookback, top_returns=top_returns),
    }
    if holdings.empty:
        return pd.DataFrame()

    signal_dates = sorted(pd.to_datetime(holdings["signal_date"]).unique())
    rows = []
    for date in signal_dates:
        members = list(membership_on(date))
        held = holdings.loc[pd.to_datetime(holdings["signal_date"]) == date, "symbol"].tolist()
        if not held or not members:
            continue
        row = {"signal_date": date}
        for name, panel in traits.items():
            if date not in panel.index:
                continue
            uni = panel.loc[date].reindex(members).dropna()
            port = panel.loc[date].reindex(held).dropna()
            if uni.empty or port.empty:
                row[f"{name}_universe"] = np.nan
                row[f"{name}_low_max"] = np.nan
                row[f"{name}_diff"] = np.nan
            else:
                row[f"{name}_universe"] = float(uni.mean())
                row[f"{name}_low_max"] = float(port.mean())
                row[f"{name}_diff"] = float(port.mean() - uni.mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _rolling_beta(returns: pd.DataFrame, closes: pd.DataFrame, window: int) -> pd.DataFrame:
    """Beta vs equal-weight cross-section market proxy (no PIT mkt)."""
    # Use SPY-like proxy: equal-weight of available returns each day.
    mkt = returns.mean(axis=1)
    out = {}
    for col in returns.columns:
        y = returns[col]
        cov = y.rolling(window, min_periods=max(window // 2, 20)).cov(mkt)
        var = mkt.rolling(window, min_periods=max(window // 2, 20)).var()
        out[col] = cov / var.replace(0, np.nan)
    return pd.DataFrame(out)


def anatomy_summary(monthly: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return pd.DataFrame()
    diff_cols = [c for c in monthly.columns if c.endswith("_diff")]
    rows = []
    for col in diff_cols:
        rows.append(
            {
                "trait": col.replace("_diff", ""),
                "mean_diff": float(monthly[col].mean()),
                "median_diff": float(monthly[col].median()),
                "pct_months_low_max_lower": float((monthly[col] < 0).mean()),
            }
        )
    summary = pd.DataFrame(rows)
    summary["size_valuation_quality"] = "BLOCKED_BY_PIT_DATA"
    summary["sector_composition"] = "BLOCKED_NO_RELIABLE_HISTORICAL_SECTOR_METADATA"
    return summary
