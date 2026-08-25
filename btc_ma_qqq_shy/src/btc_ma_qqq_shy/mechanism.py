"""Economic mechanism: macro correlates + suppressor / incremental R² diagnostics."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .config import ProjectConfig
from .data import cache_path, load_adj_close
from .hac import ols_newey_west
from .predictive import forward_compound_return, forward_realized_vol
from .strategy_core import risk_on_signal


FRED_SERIES = {
    # May be truncated on FRED after 2026 policy; still useful if present
    "HY_OAS": "BAMLH0A0HYM2",
    "REAL_YIELD_10Y": "DFII10",
    "BROAD_DOLLAR": "DTWEXBGS",
    "NFCI": "NFCI",  # Chicago Fed National Financial Conditions (weekly)
}


def fetch_fred_series(series_id: str, start: str = "2010-01-01") -> pd.Series:
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        f"&cosd={start}"
    )
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "btc-ma-qqq-research/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
    from io import StringIO

    df = pd.read_csv(StringIO(raw))
    date_col = df.columns[0]
    val_col = df.columns[1]
    s = pd.Series(pd.to_numeric(df[val_col], errors="coerce").values, index=pd.to_datetime(df[date_col]))
    s.index = s.index.tz_localize(None)
    s.name = series_id
    return s.sort_index().dropna()


def yahoo_macro_proxies(config: ProjectConfig) -> dict[str, pd.Series]:
    """Fallbacks when FRED is unreachable."""
    from .diagnostics import _ensure_symbols, _load_symbol

    syms = ["HYG", "IEF", "UUP", "TLT", "^TNX"]
    _ensure_symbols(config, syms)
    out = {}
    hyg = _load_symbol(config, "HYG")
    ief = _load_symbol(config, "IEF")
    # HY credit proxy: -log(HYG/IEF) level z later; higher = wider stress when HYG underperforms IEF
    ratio = (hyg / ief).dropna()
    out["hy_stress_proxy"] = (-np.log(ratio / ratio.iloc[0])).rename("hy_stress_proxy")
    out["uup"] = _load_symbol(config, "UUP")
    out["tlt"] = _load_symbol(config, "TLT")
    try:
        out["tnx"] = _load_symbol(config, "^TNX")
    except Exception:
        pass
    return out


def fetch_yahoo_macro(symbol: str, start: str = "2010-01-01") -> pd.Series:
    import yfinance as yf

    frame = yf.download(symbol, start=start, auto_adjust=False, progress=False, threads=False)
    if frame.empty:
        raise ValueError(f"empty {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    s = frame["Adj Close"].astype(float) if "Adj Close" in frame.columns else frame["Close"].astype(float)
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = symbol
    return s.sort_index()


def _vif(X: pd.DataFrame) -> dict[str, float]:
    """Variance inflation factors (column-wise)."""
    cols = list(X.columns)
    out = {}
    for j, name in enumerate(cols):
        y = X.iloc[:, j]
        Z = X.drop(columns=[name])
        if Z.shape[1] == 0:
            out[name] = 1.0
            continue
        Zc = pd.concat([pd.Series(1.0, index=Z.index, name="const"), Z], axis=1)
        fit = ols_newey_west(y, Zc, lags=5)
        r2 = fit.get("r2", 0.0) if fit.get("ok") else 0.0
        out[name] = float(1.0 / max(1.0 - r2, 1e-8))
    return out


def _partial_r2(y: pd.Series, X_full: pd.DataFrame, drop_col: str) -> dict:
    """Partial R² of drop_col: (RSS_reduced - RSS_full) / RSS_reduced."""
    frame = pd.concat([y.rename("y"), X_full], axis=1).dropna()
    if drop_col not in frame.columns or len(frame) < 30:
        return {"partial_r2": np.nan, "r2_full": np.nan, "r2_reduced": np.nan}
    yv = frame["y"]
    Xf = frame.drop(columns=["y"])
    Xr = Xf.drop(columns=[drop_col])
    full = ols_newey_west(yv, Xf, lags=20)
    red = ols_newey_west(yv, Xr, lags=20)
    if not full.get("ok") or not red.get("ok"):
        return {"partial_r2": np.nan}
    # Reconstruct RSS from R²
    sst = float(((yv - yv.mean()) ** 2).sum())
    rss_f = sst * (1.0 - full["r2"])
    rss_r = sst * (1.0 - red["r2"])
    pr2 = (rss_r - rss_f) / rss_r if rss_r > 0 else np.nan
    return {
        "partial_r2": float(pr2),
        "r2_full": float(full["r2"]),
        "r2_reduced": float(red["r2"]),
        "delta_r2": float(full["r2"] - red["r2"]),
        "btc_t_full": full["t_stat"].get("btc_signal"),
        "btc_beta_full": full["coef"].get("btc_signal"),
    }


def _rolling_btc_beta(
    y: pd.Series,
    X: pd.DataFrame,
    *,
    window: int = 504,
    step: int = 21,
) -> pd.DataFrame:
    rows = []
    idx = y.dropna().index.intersection(X.dropna().index)
    y2, X2 = y.reindex(idx), X.reindex(idx)
    for end in range(window, len(idx), step):
        sl = idx[end - window : end]
        fit = ols_newey_west(y2.loc[sl], X2.loc[sl], lags=20)
        if not fit.get("ok"):
            continue
        rows.append(
            {
                "end": sl[-1],
                "btc_beta": fit["coef"].get("btc_signal"),
                "btc_t": fit["t_stat"].get("btc_signal"),
                "r2": fit["r2"],
            }
        )
    return pd.DataFrame(rows)


def run_mechanism(config: ProjectConfig) -> dict[str, Any]:
    prices = load_adj_close(config)
    # Ensure VIX / DXY
    from .diagnostics import _ensure_symbols, _load_symbol

    _ensure_symbols(config, ["^VIX", "DX-Y.NYB"])
    vix = _load_symbol(config, "^VIX")
    try:
        dxy = _load_symbol(config, "DX-Y.NYB")
    except Exception:
        dxy = fetch_yahoo_macro("DX-Y.NYB")

    qqq = prices["QQQ"]
    spy = prices["SPY"]
    btc = prices["BTC-USD"]
    cal = prices[["QQQ", "SHY", "SPY"]].dropna().index

    sma0 = int(config.raw["rules"]["sma_window"])
    mom0 = int(config.raw["rules"]["momentum_window"])
    audit_start = pd.Timestamp(config.raw["data"]["audit_start"])

    btc_sig = risk_on_signal(btc, sma_window=sma0, momentum_window=mom0)
    btc_sig = btc_sig.reindex(cal.union(btc_sig.dropna().index)).sort_index().ffill().reindex(cal)
    qqq_tr = risk_on_signal(qqq, sma_window=sma0, momentum_window=mom0).reindex(cal).map(
        {True: 1.0, False: 0.0, pd.NA: np.nan}
    ).astype(float)
    spy_tr = risk_on_signal(spy, sma_window=sma0, momentum_window=mom0).reindex(cal).map(
        {True: 1.0, False: 0.0, pd.NA: np.nan}
    ).astype(float)

    first = btc_sig.dropna().index.min()
    effective = max(audit_start, pd.Timestamp(first))
    mask = cal >= effective
    qqq_r = qqq.reindex(cal).pct_change()
    y20 = forward_compound_return(qqq_r, 20)
    rv20 = forward_realized_vol(qqq_r, 20)

    sig = btc_sig.loc[mask].map({True: 1.0, False: 0.0, pd.NA: np.nan}).astype(float)
    vix_z = vix.reindex(cal).ffill().loc[mask]
    vix_z = (vix_z - vix_z.mean()) / vix_z.std(ddof=1)

    # FRED macros (fail fast) + Yahoo proxies
    fred_raw = {}
    fred_errors = {}
    for name, sid in FRED_SERIES.items():
        path = cache_path(config.prices_dir, f"FRED_{sid}")
        try:
            if path.exists():
                s = pd.read_parquet(path).iloc[:, 0]
                fred_raw[name] = s
            else:
                # skip live FRED in default path if previously timed out; proxies below
                fred_errors[name] = "skipped_live_fetch_use_yahoo_proxy"
        except Exception as exc:  # noqa: BLE001
            fred_errors[name] = str(exc)

    proxies = yahoo_macro_proxies(config)

    def z_on_cal(s: pd.Series) -> pd.Series:
        x = s.reindex(cal).ffill().loc[mask]
        return (x - x.mean()) / x.std(ddof=1)

    macro = {"vix_z": vix_z, "dxy_z": z_on_cal(dxy)}
    for name, s in fred_raw.items():
        macro[f"{name.lower()}_z"] = z_on_cal(s)
    if "hy_stress_proxy" in proxies:
        macro["hy_stress_proxy_z"] = z_on_cal(proxies["hy_stress_proxy"])
    if "uup" in proxies:
        macro["uup_z"] = z_on_cal(proxies["uup"])
    if "tlt" in proxies:
        macro["tlt_z"] = z_on_cal(proxies["tlt"])
    if "tnx" in proxies:
        macro["tnx_z"] = z_on_cal(proxies["tnx"])

    # Correlations of BTC signal with macro (point-in-time levels)
    corr_rows = []
    for name, s in macro.items():
        c = pd.concat([sig.rename("sig"), s.rename("m")], axis=1).dropna()
        if len(c) < 50:
            continue
        corr_rows.append(
            {
                "macro": name,
                "corr_with_btc_signal": float(c["sig"].corr(c["m"])),
                "n": int(len(c)),
            }
        )

    # Nested regressions on forward return and forward vol
    controls_base = pd.DataFrame(
        {
            "const": 1.0,
            "btc_signal": sig,
            "qqq_trend": qqq_tr.loc[mask],
            "spy_trend": spy_tr.loc[mask],
            "vix_z": vix_z,
        }
    )
    specs = {
        "univ": ["const", "btc_signal"],
        "plus_qqq": ["const", "btc_signal", "qqq_trend"],
        "plus_trends": ["const", "btc_signal", "qqq_trend", "spy_trend"],
        "plus_vix": ["const", "btc_signal", "qqq_trend", "spy_trend", "vix_z"],
    }
    # Add HY/NFCI if available
    if "hy_oas_z" in macro:
        controls_base["hy_oas_z"] = macro["hy_oas_z"]
        specs["plus_hy"] = ["const", "btc_signal", "qqq_trend", "spy_trend", "vix_z", "hy_oas_z"]
    elif "hy_stress_proxy_z" in macro:
        controls_base["hy_stress_proxy_z"] = macro["hy_stress_proxy_z"]
        specs["plus_hy_proxy"] = [
            "const",
            "btc_signal",
            "qqq_trend",
            "spy_trend",
            "vix_z",
            "hy_stress_proxy_z",
        ]
    if "nfci_z" in macro:
        controls_base["nfci_z"] = macro["nfci_z"]
        specs["plus_nfci"] = ["const", "btc_signal", "qqq_trend", "spy_trend", "vix_z", "nfci_z"]
    if "real_yield_10y_z" in macro:
        controls_base["real_yield_10y_z"] = macro["real_yield_10y_z"]
    if "dxy_z" in macro:
        controls_base["dxy_z"] = macro["dxy_z"]
        specs["plus_dxy"] = ["const", "btc_signal", "qqq_trend", "spy_trend", "vix_z", "dxy_z"]
    if "tnx_z" in macro:
        controls_base["tnx_z"] = macro["tnx_z"]
        specs["plus_tnx"] = ["const", "btc_signal", "qqq_trend", "spy_trend", "vix_z", "tnx_z"]

    nested_ret = {}
    nested_vol = []
    for name, cols in specs.items():
        X = controls_base[cols]
        fit_r = ols_newey_west(y20.loc[mask], X, lags=20)
        fit_v = ols_newey_west(rv20.loc[mask], X, lags=20)
        nested_ret[name] = fit_r
        nested_vol.append({"spec": name, **{k: fit_v.get(k) for k in ("ok", "coef", "t_stat", "r2", "n")}})

    # VIF on the core controlled design (plus_vix), not every optional macro
    vif_cols = [c for c in ["btc_signal", "qqq_trend", "spy_trend", "vix_z"] if c in controls_base]
    vif = _vif(controls_base[vif_cols].dropna())
    # Extended VIF for reporting
    vif_ext_cols = [
        c
        for c in [
            "btc_signal",
            "qqq_trend",
            "spy_trend",
            "vix_z",
            "hy_oas_z",
            "hy_stress_proxy_z",
            "nfci_z",
            "dxy_z",
            "tnx_z",
        ]
        if c in controls_base
    ]
    vif_extended = _vif(controls_base[vif_ext_cols].dropna())

    # Partial R² of BTC in plus_vix spec (return and vol)
    X_ret = controls_base[specs["plus_vix"]]
    partial_ret = _partial_r2(y20.loc[mask], X_ret, "btc_signal")
    partial_vol = _partial_r2(rv20.loc[mask], X_ret, "btc_signal")

    # Rolling stability
    roll = _rolling_btc_beta(y20.loc[mask], X_ret, window=504, step=21)

    # Incremental OOS R²: expanding train, predict next chunk
    oos_rows = []
    aligned = pd.concat([y20.loc[mask].rename("y"), X_ret], axis=1).dropna()
    n = len(aligned)
    min_train = 756  # ~3y
    step = 63
    for end in range(min_train, n - step, step):
        train = aligned.iloc[:end]
        test = aligned.iloc[end : end + step]
        fit = ols_newey_west(train["y"], train.drop(columns=["y"]), lags=20)
        fit_r = ols_newey_west(train["y"], train.drop(columns=["y", "btc_signal"]), lags=20)
        if not fit.get("ok") or not fit_r.get("ok"):
            continue
        # predict
        def pred(fit_obj, frame):
            beta = fit_obj["coef"]
            cols = list(beta.keys())
            return sum(frame[c] * beta[c] for c in cols)

        e_full = test["y"] - pred(fit, test)
        e_red = test["y"] - pred(fit_r, test)
        sst = ((test["y"] - train["y"].mean()) ** 2).sum()
        if sst <= 0:
            continue
        r2_f = 1.0 - float((e_full**2).sum() / sst)
        r2_r = 1.0 - float((e_red**2).sum() / sst)
        oos_rows.append(
            {
                "train_end": str(train.index[-1].date()),
                "oos_r2_full": r2_f,
                "oos_r2_reduced": r2_r,
                "incremental_oos_r2": r2_f - r2_r,
            }
        )
    oos = pd.DataFrame(oos_rows)

    # Suppressor diagnosis: compare univ vs plus_vix BTC beta
    univ_b = nested_ret["univ"]["coef"].get("btc_signal") if nested_ret["univ"].get("ok") else np.nan
    full_b = nested_ret["plus_vix"]["coef"].get("btc_signal") if nested_ret["plus_vix"].get("ok") else np.nan
    univ_t = nested_ret["univ"]["t_stat"].get("btc_signal") if nested_ret["univ"].get("ok") else np.nan
    full_t = nested_ret["plus_vix"]["t_stat"].get("btc_signal") if nested_ret["plus_vix"].get("ok") else np.nan

    if np.isfinite(full_t) and np.isfinite(univ_t) and abs(full_t) > abs(univ_t) + 0.5:
        suppressor = "BTC_TSTAT_RISES_AFTER_CONTROLS__LIKELY_SUPPRESSOR_OR_ORTHOGONAL_RESIDUAL"
    else:
        suppressor = "NO_CLEAR_SUPPRESSOR_PATTERN"
    if max(vif.values()) > 5:
        suppressor += "__CORE_VIF_ELEVATED"
    elif max(vif_extended.values()) > 5:
        suppressor += "__EXTENDED_MACRO_VIF_ELEVATED_ONLY"

    judgment = "MIXED_MECHANISM"
    pr = partial_ret.get("partial_r2", np.nan)
    pv = partial_vol.get("partial_r2", np.nan)
    oos_m = float(oos["incremental_oos_r2"].mean()) if len(oos) else np.nan
    if np.isfinite(oos_m) and oos_m < 0.005 and np.isfinite(pr) and pr < 0.03:
        judgment = "TSTAT_INFLATED_VS_ECONOMIC_INCREMENT__OOS_R2_NEAR_ZERO"
    if np.isfinite(pv) and np.isfinite(pr) and pv > pr + 0.01:
        judgment = "BTC_ADDS_MORE_TO_FORWARD_VOL_THAN_FORWARD_RETURN__RISK_CHANNEL"

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "effective_sample": [str(effective.date()), str(cal[mask][-1].date())],
        "fred_errors": fred_errors,
        "macro_corr_with_btc_signal": corr_rows,
        "nested_return_regs": {
            k: {
                "btc_beta": v.get("coef", {}).get("btc_signal"),
                "btc_t": v.get("t_stat", {}).get("btc_signal"),
                "r2": v.get("r2"),
                "n": v.get("n"),
                "coefs": v.get("coef"),
                "t_stats": v.get("t_stat"),
            }
            for k, v in nested_ret.items()
            if v.get("ok")
        },
        "nested_vol_regs": nested_vol,
        "vif": vif,
        "vif_extended": vif_extended,
        "partial_r2_return_k20": partial_ret,
        "partial_r2_vol_k20": partial_vol,
        "rolling_btc_beta": roll.to_dict(orient="records") if len(roll) else [],
        "rolling_summary": {
            "median_beta": float(roll["btc_beta"].median()) if len(roll) else np.nan,
            "pct_t_gt_2": float((roll["btc_t"] > 2).mean()) if len(roll) else np.nan,
            "pct_t_lt_0": float((roll["btc_t"] < 0).mean()) if len(roll) else np.nan,
        },
        "incremental_oos_r2": oos.to_dict(orient="records") if len(oos) else [],
        "incremental_oos_r2_mean": float(oos["incremental_oos_r2"].mean()) if len(oos) else np.nan,
        "suppressor_note": suppressor,
        "univ_vs_controlled": {
            "univ_beta": univ_b,
            "univ_t": univ_t,
            "plus_vix_beta": full_b,
            "plus_vix_t": full_t,
        },
        "judgment": judgment,
    }


def render_mechanism_md(payload: dict) -> str:
    lines = [
        "# Mechanism — Macro Correlates, VIF, Partial R²",
        "",
        f"## Judgment: `{payload['judgment']}`",
        "",
        f"Sample: `{payload['effective_sample'][0]}` → `{payload['effective_sample'][1]}`",
        f"Suppressor/collinearity note: `{payload['suppressor_note']}`",
        "",
        "## Why does BTC t-stat rise after VIX + trends?",
        "",
        f"- Univariate β/t: `{payload['univ_vs_controlled']['univ_beta']:.5f}` / `{payload['univ_vs_controlled']['univ_t']:.2f}`",
        f"- After QQQ+SPY trend + VIX β/t: `{payload['univ_vs_controlled']['plus_vix_beta']:.5f}` / `{payload['univ_vs_controlled']['plus_vix_t']:.2f}`",
        "",
        "If |t| rises while VIF is moderate, BTC may act as a **suppressor** (sharing noise with VIX/trend) "
        "or carry residual orthogonal regime info. Partial R² decides economic relevance.",
        "",
        "## VIF",
        "",
    ]
    for k, v in payload["vif"].items():
        lines.append(f"- `{k}`: `{v:.2f}`")
    lines += [
        "",
        "## Partial R² (k=20) of BTC signal",
        "",
        f"- Forward **return**: partial R²=`{payload['partial_r2_return_k20'].get('partial_r2')}` "
        f"(ΔR²=`{payload['partial_r2_return_k20'].get('delta_r2')}`, "
        f"full R²=`{payload['partial_r2_return_k20'].get('r2_full')}`)",
        f"- Forward **RV**: partial R²=`{payload['partial_r2_vol_k20'].get('partial_r2')}` "
        f"(ΔR²=`{payload['partial_r2_vol_k20'].get('delta_r2')}`)",
        "",
        "HAC t≈3 is **not** the same as economic usefulness: check partial R² and especially "
        f"mean incremental OOS R² (`{payload.get('incremental_oos_r2_mean')}`).",
        "Rolling windows with t>2 are intermittent — coefficient is not stably significant.",
        "",
        "## Nested return regressions",
        "",
        "| Spec | β_BTC | t | R² |",
        "|---|---:|---:|---:|",
    ]
    for name, r in payload["nested_return_regs"].items():
        lines.append(f"| {name} | {r['btc_beta']:.5f} | {r['btc_t']:.2f} | {r['r2']:.4f} |")
    lines += [
        "",
        "## Corr(BTC signal, macro)",
        "",
        "| Macro | corr | n |",
        "|---|---:|---:|",
    ]
    for r in payload["macro_corr_with_btc_signal"]:
        lines.append(f"| {r['macro']} | {r['corr_with_btc_signal']:.3f} | {r['n']} |")
    if payload.get("fred_errors"):
        lines += ["", "FRED fetch errors:", ""]
        for k, v in payload["fred_errors"].items():
            lines.append(f"- `{k}`: `{v}`")
    rs = payload["rolling_summary"]
    lines += [
        "",
        "## Rolling 2y BTC β (on return k=20, controlled)",
        "",
        f"- Median β: `{rs.get('median_beta')}`",
        f"- % windows t>2: `{rs.get('pct_t_gt_2')}`",
        f"- % windows t<0: `{rs.get('pct_t_lt_0')}`",
        f"- Mean incremental OOS R²: `{payload.get('incremental_oos_r2_mean')}`",
        "",
        "## Bottom line",
        "",
        "Mechanism work can upgrade an empirical gate only if incremental OOS R² / partial R² "
        "is material on **risk or return**. Significant HAC t alone is not enough.",
        "",
    ]
    return "\n".join(lines)


def write_mechanism_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil

    import yaml

    md = render_mechanism_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_mechanism"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "mechanism_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "mechanism_partial_r2.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    latest = config.reports_dir / "mechanism_partial_r2.md"
    shutil.copy2(run_dir / "mechanism_partial_r2.md", latest)
    return latest
