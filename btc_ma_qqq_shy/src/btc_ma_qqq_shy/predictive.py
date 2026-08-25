"""Predictive diagnostics: conditional forwards, HAC regs, lead-lag."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .hac import ols_newey_west


def forward_compound_return(rets: pd.Series, k: int) -> pd.Series:
    """At t: compound return from t+1 through t+k inclusive."""
    cum = (1.0 + rets.astype(float)).cumprod()
    return cum.shift(-k) / cum - 1.0


def forward_realized_vol(rets: pd.Series, k: int) -> pd.Series:
    """At t: ann. realized vol of daily returns in (t+1..t+k)."""
    if k <= 1:
        # single-day: use |r| * sqrt(252) as a vol proxy
        return (rets.shift(-1).abs() * np.sqrt(252.0)).rename("vol_1")
    roll = rets.rolling(k).std(ddof=1)
    return (roll.shift(-k) * np.sqrt(252.0)).rename(f"vol_{k}")


def forward_downside_vol(rets: pd.Series, k: int) -> pd.Series:
    if k <= 1:
        neg = rets.shift(-1).clip(upper=0.0).abs() * np.sqrt(252.0)
        return neg.rename("dvol_1")
    neg = rets.clip(upper=0.0)
    roll = neg.rolling(k).std(ddof=1)
    return (roll.shift(-k) * np.sqrt(252.0)).rename(f"dvol_{k}")


def forward_min_drawdown(rets: pd.Series, k: int) -> pd.Series:
    """Worst peak-to-trough inside the forward k-day path (negative)."""
    r = rets.astype(float).to_numpy()
    idx = rets.index
    out = np.full(len(r), np.nan)
    for i in range(len(r) - k):
        path = np.cumprod(1.0 + r[i + 1 : i + 1 + k])
        if len(path) == 0:
            continue
        peak = np.maximum.accumulate(path)
        dd = path / peak - 1.0
        out[i] = float(dd.min())
    return pd.Series(out, index=idx, name=f"mdd_{k}")


def conditional_forward_table(
    signal: pd.Series,
    qqq_rets: pd.Series,
    horizons: Iterable[int] = (1, 5, 10, 20, 60),
) -> pd.DataFrame:
    """E[R|ON], E[R|OFF], vols, downside, ΔR for each horizon (daily signal)."""
    sig = signal.astype("boolean")
    rows = []
    for k in horizons:
        fwd = forward_compound_return(qqq_rets, k)
        vol = forward_realized_vol(qqq_rets, k)
        dvol = forward_downside_vol(qqq_rets, k)
        frame = pd.concat(
            [sig.rename("on"), fwd.rename("fwd"), vol.rename("vol"), dvol.rename("dvol")],
            axis=1,
        ).dropna()
        on = frame[frame["on"] == True]  # noqa: E712
        off = frame[frame["on"] == False]  # noqa: E712
        e_on = float(on["fwd"].mean()) if len(on) else np.nan
        e_off = float(off["fwd"].mean()) if len(off) else np.nan
        rows.append(
            {
                "k": int(k),
                "n_on": int(len(on)),
                "n_off": int(len(off)),
                "E_R_on": e_on,
                "E_R_off": e_off,
                "delta_R": e_on - e_off,
                "vol_on": float(on["vol"].mean()) if len(on) else np.nan,
                "vol_off": float(off["vol"].mean()) if len(off) else np.nan,
                "delta_vol": (float(on["vol"].mean()) - float(off["vol"].mean()))
                if len(on) and len(off)
                else np.nan,
                "dvol_on": float(on["dvol"].mean()) if len(on) else np.nan,
                "dvol_off": float(off["dvol"].mean()) if len(off) else np.nan,
                "delta_dvol": (float(on["dvol"].mean()) - float(off["dvol"].mean()))
                if len(on) and len(off)
                else np.nan,
                "hit_on": float((on["fwd"] > 0).mean()) if len(on) else np.nan,
                "hit_off": float((off["fwd"] > 0).mean()) if len(off) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def predictive_regressions(
    signal: pd.Series,
    qqq_rets: pd.Series,
    horizons: Iterable[int] = (1, 5, 10, 20, 60),
    controls: pd.DataFrame | None = None,
) -> list[dict]:
    """R_{t+1:t+k} = a + b Signal_t (+ controls) with NW lags >= k."""
    sig = signal.map({True: 1.0, False: 0.0, pd.NA: np.nan}).astype(float)
    results = []
    for k in horizons:
        y = forward_compound_return(qqq_rets, int(k))
        X = pd.DataFrame({"const": 1.0, "btc_signal": sig}, index=sig.index)
        if controls is not None:
            X = pd.concat([X, controls], axis=1)
        # drop duplicate colnames if any
        X = X.loc[:, ~X.columns.duplicated()]
        fit = ols_newey_west(y, X, lags=max(int(k), 1))
        fit["horizon"] = int(k)
        fit["dep"] = f"R_QQQ_t+1:t+{k}"
        results.append(fit)
    return results


def lead_lag_corr(
    btc_rets: pd.Series,
    qqq_rets: pd.Series,
    lags: Iterable[int] = (-20, -10, -5, -1, 0, 1, 5, 10, 20),
) -> pd.DataFrame:
    """
    Corr(R_BTC_{t-k}, R_QQQ_t).
    Negative k: BTC leads QQQ (BTC past vs QQQ present) when we use shift(-k) on BTC...
    Define: corr(BTC.shift(k), QQQ) where k>0 means BTC lagged (past BTC vs now QQQ = BTC leads).
    User asked Corr(R_{t-k}^BTC, R_t^QQQ) for k in {-20..+20}.
    k>0: past BTC vs current QQQ (BTC leads if corr strong).
    k<0: future BTC vs current QQQ (QQQ leads).
    k=0: contemporaneous.
    """
    a = pd.concat([btc_rets.rename("btc"), qqq_rets.rename("qqq")], axis=1).dropna()
    rows = []
    for k in lags:
        # R_BTC_{t-k} aligned to t: shift BTC by +k
        x = a["btc"].shift(int(k))
        c = x.corr(a["qqq"])
        rows.append(
            {
                "k": int(k),
                "corr": float(c) if pd.notna(c) else np.nan,
                "interpretation": (
                    "BTC_leads" if k > 0 else ("contemporaneous" if k == 0 else "QQQ_leads")
                ),
            }
        )
    return pd.DataFrame(rows)
