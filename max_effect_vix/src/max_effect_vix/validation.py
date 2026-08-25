"""Cross-sectional IC, Fama-MacBeth, and factor-regression validation."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .status import SIZE_BLOCKED


def spearman_ic(signal: pd.Series, forward_return: pd.Series) -> float:
    frame = pd.concat({"signal": signal, "forward": forward_return}, axis=1).dropna()
    if len(frame) < 10:
        return np.nan
    return float(frame["signal"].corr(frame["forward"], method="spearman"))


def monthly_ic_table(signals: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date in signals.index:
        if date not in forward_returns.index:
            continue
        rows.append(
            {
                "date": date,
                "ic": spearman_ic(signals.loc[date], forward_returns.loc[date]),
                "n": int(signals.loc[date].notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def fama_macbeth(
    signals: pd.DataFrame,
    forward_returns: pd.DataFrame,
    controls: Optional[dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Monthly cross-sectional OLS of forward returns on signal (+ optional controls)."""
    controls = controls or {}
    rows = []
    for date in signals.index:
        if date not in forward_returns.index:
            continue
        data = {"y": forward_returns.loc[date], "MAX": signals.loc[date]}
        for name, panel in controls.items():
            if date in panel.index:
                data[name] = panel.loc[date]
        frame = pd.DataFrame(data).dropna()
        if len(frame) < 20 or frame["MAX"].nunique() < 2:
            continue
        y = frame["y"].to_numpy()
        x = np.column_stack([np.ones(len(frame)), frame.drop(columns=["y"]).to_numpy()])
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        columns = ["intercept", "MAX"] + [name for name in frame.columns if name != "y"]
        row = {"date": date, "n": len(frame)}
        for name, value in zip(columns, beta):
            row[name] = float(value)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_fama_macbeth(monthly: pd.DataFrame) -> dict:
    if monthly.empty or "MAX" not in monthly:
        return {"mean_max_slope": np.nan, "t_stat": np.nan, "months": 0, "size_status": SIZE_BLOCKED}
    series = monthly["MAX"].dropna()
    mean = float(series.mean())
    se = float(series.std(ddof=1) / np.sqrt(len(series))) if len(series) > 1 else np.nan
    return {
        "mean_max_slope": mean,
        "t_stat": mean / se if se else np.nan,
        "months": len(series),
        "size_status": SIZE_BLOCKED,
    }


def factor_regression(portfolio_excess: pd.Series, factors: pd.DataFrame) -> dict:
    """OLS of portfolio excess returns on provided factor columns."""
    available = [column for column in ["MKT_RF", "SMB", "HML", "MOM", "QMJ"] if column in factors.columns]
    qmj_status = "OK" if "QMJ" in factors.columns else "NOT_AVAILABLE"
    frame = pd.concat([portfolio_excess.rename("y"), factors[available]], axis=1).dropna()
    if len(frame) < 24 or not available:
        return {
            "alpha": np.nan,
            "alpha_t_stat": np.nan,
            "t_stat": np.nan,
            "n": len(frame),
            "qmj_status": qmj_status,
            "loadings": {},
            "loading_t_stats": {},
        }
    y = frame["y"].to_numpy()
    x = np.column_stack([np.ones(len(frame)), frame[available].to_numpy()])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    sigma2 = float(resid @ resid / max(len(frame) - x.shape[1], 1))
    xtx_inv = np.linalg.pinv(x.T @ x)
    se = np.sqrt(np.diag(xtx_inv) * sigma2)
    loadings = {name: float(value) for name, value in zip(available, beta[1:])}
    loading_t_stats = {
        name: float(value / err) if err else np.nan
        for name, value, err in zip(available, beta[1:], se[1:])
    }
    alpha_t = float(beta[0] / se[0]) if se[0] else np.nan
    return {
        "alpha": float(beta[0]),
        "alpha_annualized": float(beta[0] * 12),
        "alpha_t_stat": alpha_t,
        "t_stat": alpha_t,
        "n": len(frame),
        "qmj_status": qmj_status,
        "loadings": loadings,
        "loading_t_stats": loading_t_stats,
    }


def load_ken_french_factors(cache_path: Optional[str] = None) -> pd.DataFrame:
    """Best-effort load of Ken French monthly FF3; empty frame if unavailable."""
    import io
    import zipfile
    from urllib.request import Request, urlopen

    url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (research; max-effect-vix)"})
        with urlopen(request, timeout=60) as response:
            raw = response.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            name = next(item for item in archive.namelist() if item.lower().endswith(".csv"))
            text = archive.read(name).decode("latin-1")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return pd.DataFrame()

    lines = []
    for line in text.splitlines():
        if line.startswith("1926") or (lines and line[:4].isdigit()):
            if line.startswith(" Annual"):
                break
            lines.append(line)
    if not lines:
        return pd.DataFrame()
    frame = pd.read_csv(io.StringIO("\n".join(lines)), header=None)
    # File includes a header row after the date start; detect column count.
    if frame.shape[1] == 5:
        frame.columns = ["ym", "MKT_RF", "SMB", "HML", "RF"]
    else:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["ym"].astype(str), format="%Y%m") + pd.offsets.MonthEnd(0)
    for column in ["MKT_RF", "SMB", "HML", "RF"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce") / 100.0
    return frame.dropna().set_index("date")[["MKT_RF", "SMB", "HML", "RF"]]
