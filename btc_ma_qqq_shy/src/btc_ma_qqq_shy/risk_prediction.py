"""Risk prediction: BTC signal vs VIX/RV/trend for future QQQ risk."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from .config import ProjectConfig
from .data import load_adj_close
from .predictive import forward_downside_vol, forward_realized_vol
from .strategy_core import risk_on_signal


def _forward_min_dd(rets: pd.Series, k: int) -> pd.Series:
    r = rets.astype(float).to_numpy()
    out = np.full(len(r), np.nan)
    for i in range(len(r) - k):
        path = np.cumprod(1.0 + r[i + 1 : i + 1 + k])
        peak = np.maximum.accumulate(path)
        out[i] = float((path / peak - 1.0).min())
    return pd.Series(out, index=rets.index)


def _auc_safe(y, p) -> float:
    y = np.asarray(y).astype(int)
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, p))


def _fit_predict_logit(X: pd.DataFrame, y: pd.Series) -> tuple[np.ndarray, dict]:
    frame = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(frame) < 80 or frame["y"].nunique() < 2:
        return np.full(len(y), np.nan), {"ok": False, "n": int(len(frame))}
    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(frame.drop(columns=["y"]).to_numpy(), frame["y"].to_numpy())
    # in-sample probs aligned
    proba = pd.Series(index=frame.index, dtype=float)
    proba.loc[frame.index] = model.predict_proba(frame.drop(columns=["y"]).to_numpy())[:, 1]
    coefs = {c: float(model.coef_[0][i]) for i, c in enumerate(frame.drop(columns=["y"]).columns)}
    return proba.reindex(y.index).to_numpy(), {
        "ok": True,
        "n": int(len(frame)),
        "coefs": coefs,
        "intercept": float(model.intercept_[0]),
    }


def _oos_expanding_auc(X: pd.DataFrame, y: pd.Series, *, min_train: int = 756, step: int = 63) -> dict:
    """Expanding-window OOS probabilities → AUC/Brier/logloss."""
    frame = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(frame) < min_train + step:
        return {"ok": False}
    probs = []
    actual = []
    for end in range(min_train, len(frame) - 1, step):
        train = frame.iloc[:end]
        test = frame.iloc[end : min(end + step, len(frame))]
        if train["y"].nunique() < 2 or len(test) == 0:
            continue
        model = LogisticRegression(max_iter=1000, solver="lbfgs")
        model.fit(train.drop(columns=["y"]).to_numpy(), train["y"].to_numpy())
        p = model.predict_proba(test.drop(columns=["y"]).to_numpy())[:, 1]
        probs.extend(p.tolist())
        actual.extend(test["y"].tolist())
    if len(actual) < 30 or len(set(actual)) < 2:
        return {"ok": False, "n_oos": len(actual)}
    yv = np.asarray(actual, dtype=int)
    pv = np.asarray(probs, dtype=float)
    return {
        "ok": True,
        "n_oos": int(len(yv)),
        "auc": _auc_safe(yv, pv),
        "brier": float(brier_score_loss(yv, pv)),
        "log_loss": float(log_loss(yv, pv, labels=[0, 1])),
        "base_rate": float(yv.mean()),
    }


def run_risk_prediction(config: ProjectConfig) -> dict[str, Any]:
    from .diagnostics import _ensure_symbols, _load_symbol

    _ensure_symbols(config, ["^VIX"])
    prices = load_adj_close(config)
    vix = _load_symbol(config, "^VIX")
    qqq = prices["QQQ"]
    spy = prices["SPY"]
    btc = prices["BTC-USD"]
    cal = prices[["QQQ", "SHY", "SPY"]].dropna().index

    sma0 = int(config.raw["rules"]["sma_window"])
    mom0 = int(config.raw["rules"]["momentum_window"])
    cutoff = pd.Timestamp(config.raw["oos"]["cutoff_date"])
    # Discovery sample for fitting comparisons ends at cutoff
    audit_start = pd.Timestamp(config.raw["data"]["audit_start"])

    btc_sig = risk_on_signal(btc, sma_window=sma0, momentum_window=mom0)
    btc_sig = btc_sig.reindex(cal.union(btc_sig.dropna().index)).sort_index().ffill().reindex(cal)
    first = btc_sig.dropna().index.min()
    effective = max(audit_start, pd.Timestamp(first))

    qqq_r = qqq.reindex(cal).pct_change()
    # Predictors at t
    sig = btc_sig.map({True: 1.0, False: 0.0, pd.NA: np.nan}).astype(float)
    vix_z = vix.reindex(cal).ffill()
    vix_z = (vix_z - vix_z.mean()) / vix_z.std(ddof=1)
    rv20_trail = qqq_r.rolling(20).std(ddof=1) * np.sqrt(252)
    qqq_tr = risk_on_signal(qqq, sma_window=sma0, momentum_window=mom0).reindex(cal).map(
        {True: 1.0, False: 0.0, pd.NA: np.nan}
    ).astype(float)
    spy_tr = risk_on_signal(spy, sma_window=sma0, momentum_window=mom0).reindex(cal).map(
        {True: 1.0, False: 0.0, pd.NA: np.nan}
    ).astype(float)

    # Targets
    rv5 = forward_realized_vol(qqq_r, 5)
    rv20 = forward_realized_vol(qqq_r, 20)
    dvol20 = forward_downside_vol(qqq_r, 20)
    mdd20 = _forward_min_dd(qqq_r, 20)
    dd5pct = (mdd20 <= -0.05).astype(float)

    mask = (cal >= effective) & (cal < cutoff)  # discovery only for IS metrics
    # Also report full-sample expanding OOS that never uses post-cutoff for training beyond cutoff
    mask_all = cal >= effective

    specs = {
        "btc_only": pd.DataFrame({"btc": sig}),
        "vix_only": pd.DataFrame({"vix": vix_z}),
        "rv_only": pd.DataFrame({"rv20": rv20_trail}),
        "vix_rv": pd.DataFrame({"vix": vix_z, "rv20": rv20_trail}),
        "vix_rv_trends": pd.DataFrame(
            {"vix": vix_z, "rv20": rv20_trail, "qqq_tr": qqq_tr, "spy_tr": spy_tr}
        ),
        "full_plus_btc": pd.DataFrame(
            {
                "vix": vix_z,
                "rv20": rv20_trail,
                "qqq_tr": qqq_tr,
                "spy_tr": spy_tr,
                "btc": sig,
            }
        ),
    }

    # Continuous: correlate / simple OLS R² via corr^2 for RV targets
    cont_rows = []
    for horizon_name, target in [("rv5", rv5), ("rv20", rv20), ("dvol20", dvol20)]:
        for spec_name, X in specs.items():
            if "btc" not in X.columns and spec_name != "btc_only":
                # still evaluate
                pass
            frame = pd.concat([target.rename("y"), X], axis=1).loc[mask].dropna()
            if len(frame) < 50:
                continue
            # multivariate R²
            from .hac import ols_newey_west

            Xc = pd.concat([pd.Series(1.0, index=frame.index, name="const"), frame.drop(columns=["y"])], axis=1)
            fit = ols_newey_west(frame["y"], Xc, lags=20)
            cont_rows.append(
                {
                    "target": horizon_name,
                    "spec": spec_name,
                    "r2": fit.get("r2"),
                    "btc_t": (fit.get("t_stat") or {}).get("btc"),
                    "n": fit.get("n"),
                }
            )

    # Classification: P(DD>5% in 20d)
    clf_is = {}
    clf_oos = {}
    for spec_name, X in specs.items():
        _, meta = _fit_predict_logit(X.loc[mask], dd5pct.loc[mask])
        oos = _oos_expanding_auc(X.loc[mask_all & (cal < cutoff)], dd5pct.loc[mask_all & (cal < cutoff)])
        # IS AUC from in-sample proba
        proba, meta2 = _fit_predict_logit(X.loc[mask], dd5pct.loc[mask])
        y_is = dd5pct.loc[mask]
        valid = pd.DataFrame({"y": y_is, "p": proba}).dropna()
        is_metrics = {"ok": False}
        if len(valid) > 50 and valid["y"].nunique() > 1:
            is_metrics = {
                "ok": True,
                "auc": _auc_safe(valid["y"], valid["p"]),
                "brier": float(brier_score_loss(valid["y"], valid["p"])),
                "log_loss": float(log_loss(valid["y"], valid["p"], labels=[0, 1])),
                "base_rate": float(valid["y"].mean()),
                "n": int(len(valid)),
                "coefs": meta2.get("coefs"),
            }
        clf_is[spec_name] = is_metrics
        clf_oos[spec_name] = oos

    # Incremental: full_plus_btc vs vix_rv_trends
    def _inc(a: dict, b: dict, key: str) -> float:
        if not a.get("ok") or not b.get("ok"):
            return float("nan")
        return float(a.get(key, np.nan) - b.get(key, np.nan))

    judgment = "BTC_NO_CLEAR_OOS_RISK_INCREMENT"
    if clf_oos.get("full_plus_btc", {}).get("ok") and clf_oos.get("vix_rv_trends", {}).get("ok"):
        d_auc = _inc(clf_oos["full_plus_btc"], clf_oos["vix_rv_trends"], "auc")
        d_brier = _inc(clf_oos["vix_rv_trends"], clf_oos["full_plus_btc"], "brier")  # lower better
        if d_auc > 0.02 and d_brier > 0:
            judgment = "BTC_ADDS_OOS_DRAWDOWN_CLASSIFICATION_INCREMENT"
        elif d_auc > 0.005:
            judgment = "BTC_MARGINAL_OOS_RISK_INCREMENT"
        else:
            judgment = "BTC_NO_CLEAR_OOS_RISK_INCREMENT_VS_VIX_RV_TREND"

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "discovery_window": [str(effective.date()), str(cutoff.date())],
        "oos_cutoff": str(cutoff.date()),
        "continuous_r2": cont_rows,
        "drawdown_gt5pct_20d_is": clf_is,
        "drawdown_gt5pct_20d_oos_expanding": clf_oos,
        "incremental_oos_auc_full_minus_baselines": {
            "vs_vix_rv_trends": _inc(clf_oos.get("full_plus_btc", {}), clf_oos.get("vix_rv_trends", {}), "auc"),
            "vs_vix_only": _inc(clf_oos.get("full_plus_btc", {}), clf_oos.get("vix_only", {}), "auc"),
            "vs_btc_only": _inc(clf_oos.get("full_plus_btc", {}), clf_oos.get("btc_only", {}), "auc"),
        },
        "judgment": judgment,
        "note": "Discovery metrics use sample before frozen OOS cutoff. Expanding OOS never trains past cutoff.",
    }


def render_risk_pred_md(payload: dict) -> str:
    lines = [
        "# Risk Prediction — BTC vs VIX / RV / Trend",
        "",
        f"## Judgment: `{payload['judgment']}`",
        "",
        f"Discovery window: `{payload['discovery_window'][0]}` → `{payload['discovery_window'][1]}` (OOS cutoff)",
        "",
        "## P(QQQ 20d max DD ≤ −5%) — expanding OOS",
        "",
        "| Spec | AUC | Brier | LogLoss | n |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, m in payload["drawdown_gt5pct_20d_oos_expanding"].items():
        if not m.get("ok"):
            lines.append(f"| {name} | n/a | n/a | n/a | {m.get('n_oos', 0)} |")
            continue
        lines.append(
            f"| {name} | {m['auc']:.3f} | {m['brier']:.4f} | {m['log_loss']:.3f} | {m['n_oos']} |"
        )
    inc = payload["incremental_oos_auc_full_minus_baselines"]
    lines += [
        "",
        f"- ΔAUC (full+BTC − VIX+RV+trends): `{inc.get('vs_vix_rv_trends')}`",
        f"- ΔAUC (full+BTC − VIX only): `{inc.get('vs_vix_only')}`",
        "",
        "## Continuous forward risk R² (discovery IS, HAC)",
        "",
        "| Target | Spec | R² | t_BTC |",
        "|---|---|---:|---:|",
    ]
    for r in payload["continuous_r2"]:
        lines.append(
            f"| {r['target']} | {r['spec']} | {r.get('r2')} | {r.get('btc_t')} |"
        )
    lines += [
        "",
        "If BTC does not improve OOS drawdown classification after VIX+RV+trends, "
        "treat the trading rule as an empirical gate — not a validated risk forecaster.",
        "",
    ]
    return "\n".join(lines)


def write_risk_pred_report(config: ProjectConfig, payload: dict) -> Path:
    import shutil

    import yaml

    md = render_risk_pred_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_risk_prediction"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "risk_prediction_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "risk_prediction.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)
    latest = config.reports_dir / "risk_prediction.md"
    shutil.copy2(run_dir / "risk_prediction.md", latest)
    return latest
