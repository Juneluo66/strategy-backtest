"""Automatic SPY stress windows — no hand-picked favorable crises."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics_ext import capture_ratio, max_drawdown


def detect_spy_stress_windows(
    spy_prices: pd.Series,
    *,
    drawdown_threshold: float = -0.15,
    vol_window: int = 21,
    vol_quantile: float = 0.90,
    min_days: int = 15,
) -> pd.DataFrame:
    """
    Identify stress periods as union of:
      1) SPY peak-to-trough drawdowns reaching drawdown_threshold
      2) high realized-vol regimes (vol_window vol above historical vol_quantile)
    Returns non-overlapping labeled windows covering the sample.
    """
    spy = spy_prices.dropna().sort_index()
    rets = spy.pct_change(fill_method=None)
    equity = spy / spy.iloc[0]
    # Actually use price drawdown from rolling peak
    dd = spy / spy.cummax() - 1

    windows = []
    # Drawdown episodes: from peak until recovery to prior peak (or end)
    in_dd = False
    start = None
    peak_level = None
    trough = 0.0
    for date, level in dd.items():
        if not in_dd and level <= drawdown_threshold:
            # walk back to last peak (dd==0)
            hist = dd.loc[:date]
            peak_dates = hist[hist == 0]
            start = peak_dates.index[-1] if len(peak_dates) else hist.index[0]
            in_dd = True
            trough = level
            peak_level = spy.loc[start]
        elif in_dd:
            trough = min(trough, level)
            if spy.loc[date] >= peak_level * 0.999:
                end = date
                if (end - start).days >= min_days:
                    windows.append(
                        {
                            "name": f"DD_{start.date()}_{end.date()}",
                            "start": start,
                            "end": end,
                            "type": "drawdown",
                            "trough_dd": trough,
                        }
                    )
                in_dd = False
    if in_dd and start is not None:
        end = dd.index[-1]
        if (end - start).days >= min_days:
            windows.append(
                {
                    "name": f"DD_{start.date()}_{end.date()}",
                    "start": start,
                    "end": end,
                    "type": "drawdown",
                    "trough_dd": trough,
                }
            )

    # High-vol regimes: consecutive days above quantile
    vol = rets.rolling(vol_window, min_periods=vol_window).std() * np.sqrt(252)
    thr = vol.quantile(vol_quantile)
    high = vol >= thr
    if high.any():
        group = (high != high.shift(fill_value=False)).cumsum()
        for gid, block in high.groupby(group):
            if not block.iloc[0]:
                continue
            idx = block.index
            if len(idx) >= min_days:
                windows.append(
                    {
                        "name": f"HIVOL_{idx[0].date()}_{idx[-1].date()}",
                        "start": idx[0],
                        "end": idx[-1],
                        "type": "high_vol",
                        "trough_dd": float(dd.loc[idx[0] : idx[-1]].min()),
                    }
                )

    return pd.DataFrame(windows)


def crisis_metrics(
    windows: pd.DataFrame,
    series_map: dict[str, pd.Series],
    spy_returns: pd.Series,
) -> pd.DataFrame:
    rows = []
    for _, win in windows.iterrows():
        start, end = win["start"], win["end"]
        spy_seg = spy_returns.loc[start:end]
        for label, rets in series_map.items():
            seg = rets.loc[start:end].dropna()
            if seg.empty:
                continue
            equity = (1 + seg).cumprod()
            # recovery: first day after trough back to pre-window equity=1 path relative to start
            trough_i = equity.idxmin()
            after = equity.loc[trough_i:]
            recovered = after[after >= 1.0]
            if not recovered.empty:
                recovery_days = int((recovered.index[0] - trough_i).days)
            else:
                recovery_days = np.nan
            rows.append(
                {
                    "window": win["name"],
                    "type": win["type"],
                    "start": str(pd.Timestamp(start).date()),
                    "end": str(pd.Timestamp(end).date()),
                    "strategy": label,
                    "crisis_return": float((1 + seg).prod() - 1),
                    "max_drawdown": max_drawdown(seg),
                    "downside_capture": capture_ratio(seg, spy_seg, upside=False),
                    "recovery_days_from_trough": recovery_days,
                }
            )
    return pd.DataFrame(rows)
