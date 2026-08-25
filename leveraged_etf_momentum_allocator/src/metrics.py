"""Performance metrics — aligned with strategy-backtest sibling conventions."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


def _finite(series: pd.Series) -> pd.Series:
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + _finite(returns)).cumprod()
    if equity.empty:
        return float("nan")
    return float((equity / equity.cummax() - 1).min())


def cagr(returns: pd.Series) -> float:
    r = _finite(returns)
    if r.empty:
        return float("nan")
    years = len(r) / 252
    if years <= 0:
        return float("nan")
    return float((1 + r).prod() ** (1 / years) - 1)


def ann_vol(returns: pd.Series) -> float:
    r = _finite(returns)
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(252))


def sharpe(returns: pd.Series, rf_daily: Optional[pd.Series] = None) -> float:
    r = _finite(returns)
    if rf_daily is not None:
        aligned = pd.concat([r.rename("r"), rf_daily.rename("rf")], axis=1).dropna()
        if len(aligned) < 2:
            return float("nan")
        excess = aligned["r"] - aligned["rf"]
        if excess.std(ddof=1) == 0:
            return float("nan")
        return float(excess.mean() / excess.std(ddof=1) * np.sqrt(252))
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252))


def sortino(returns: pd.Series, rf_daily: Optional[pd.Series] = None) -> float:
    r = _finite(returns)
    if rf_daily is not None:
        aligned = pd.concat([r.rename("r"), rf_daily.rename("rf")], axis=1).dropna()
        excess = aligned["r"] - aligned["rf"]
    else:
        excess = r
    downside = excess[excess < 0]
    if len(excess) < 2 or downside.empty or downside.std(ddof=1) == 0:
        return float("nan")
    return float(excess.mean() / downside.std(ddof=1) * np.sqrt(252))


def calmar(returns: pd.Series) -> float:
    dd = max_drawdown(returns)
    if not np.isfinite(dd) or dd == 0:
        return float("nan")
    return float(cagr(returns) / abs(dd))


def win_rate(returns: pd.Series, freq: str = "ME") -> float:
    grouped = _finite(returns).resample(freq).apply(lambda x: (1 + x).prod() - 1)
    if grouped.empty:
        return float("nan")
    return float((grouped > 0).mean())


def annual_returns(returns: pd.Series) -> pd.Series:
    r = _finite(returns)
    return r.resample("YE").apply(lambda x: (1 + x).prod() - 1)


def turnover_stats(trades: pd.DataFrame) -> dict[str, float]:
    if trades is None or trades.empty or "turnover" not in trades.columns:
        return {
            "average_turnover": 0.0,
            "annual_turnover": 0.0,
            "number_of_trades": 0,
            "total_commission": 0.0,
            "total_slippage": 0.0,
        }
    daily = trades.groupby("date")["turnover"].sum()
    span_years = max(
        (pd.to_datetime(daily.index).max() - pd.to_datetime(daily.index).min()).days / 365.25,
        1 / 12,
    )
    return {
        "average_turnover": float(daily.mean()) if len(daily) else 0.0,
        "annual_turnover": float(daily.sum() / span_years),
        "number_of_trades": int(len(trades)),
        "total_commission": float(trades["commission"].sum()) if "commission" in trades else 0.0,
        "total_slippage": float(trades["slippage"].sum()) if "slippage" in trades else 0.0,
    }


def average_holding_period(trades: pd.DataFrame) -> float:
    """Approximate avg holding period in days from round-trip legs."""
    if trades is None or trades.empty:
        return float("nan")
    # Simple heuristic: days between first buy and subsequent sell per ticker
    periods: list[float] = []
    for ticker in trades["ticker"].unique():
        legs = trades.loc[trades["ticker"] == ticker].sort_values("date")
        buy_dates = legs.loc[legs["side"] == "buy", "date"]
        sell_dates = legs.loc[legs["side"] == "sell", "date"]
        for b, s in zip(buy_dates, sell_dates):
            periods.append((pd.Timestamp(s) - pd.Timestamp(b)).days)
    return float(np.mean(periods)) if periods else float("nan")


def compute_metrics(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    rf_daily: Optional[pd.Series] = None,
    label: str = "strategy",
) -> dict[str, Any]:
    """Full metric bundle for gross and net returns."""
    gross = equity["gross_return"]
    net = equity["net_return"]
    turn = turnover_stats(trades)
    ann = annual_returns(net)
    return {
        "label": label,
        "start": str(equity.index.min().date()) if len(equity) else None,
        "end": str(equity.index.max().date()) if len(equity) else None,
        "final_wealth_gross": float(equity["equity_gross"].iloc[-1]) if len(equity) else float("nan"),
        "final_wealth_net": float(equity["equity_net"].iloc[-1]) if len(equity) else float("nan"),
        "total_return_gross": float(equity["equity_gross"].iloc[-1] - 1) if len(equity) else float("nan"),
        "total_return_net": float(equity["equity_net"].iloc[-1] - 1) if len(equity) else float("nan"),
        "cagr_gross": cagr(gross),
        "cagr_net": cagr(net),
        "annualized_volatility": ann_vol(net),
        "sharpe_rf0": sharpe(net),
        "sharpe_with_rf": sharpe(net, rf_daily) if rf_daily is not None else float("nan"),
        "sortino_rf0": sortino(net),
        "sortino_with_rf": sortino(net, rf_daily) if rf_daily is not None else float("nan"),
        "max_drawdown": max_drawdown(net),
        "calmar": calmar(net),
        "monthly_win_rate": win_rate(net, "ME"),
        "annual_win_rate": win_rate(net, "YE"),
        "best_year": float(ann.max()) if len(ann) else float("nan"),
        "worst_year": float(ann.min()) if len(ann) else float("nan"),
        "average_turnover": turn["average_turnover"],
        "annual_turnover": turn["annual_turnover"],
        "number_of_trades": turn["number_of_trades"],
        "average_holding_period_days": average_holding_period(trades),
        "time_in_market": float(equity["exposure"].mean()) if "exposure" in equity else float("nan"),
        "cash_defensive_ratio": float(equity["cash_ratio"].mean()) if "cash_ratio" in equity else float("nan"),
    }


def reconciliation_table(
    local: dict[str, Any],
    targets: dict[str, Any],
    tolerance: dict[str, float],
) -> pd.DataFrame:
    rows = []
    mapping = [
        ("cagr_net", "cagr_pct", "cagr_pp", 100.0),
        ("sharpe_rf0", "sharpe", "sharpe", 1.0),
        ("sortino_rf0", "sortino", "sortino", 1.0),
        ("max_drawdown", "max_drawdown_pct", "max_drawdown_pp", 100.0),
        ("calmar", "calmar", "calmar", 1.0),
    ]
    for local_key, target_key, tol_key, scale in mapping:
        local_val = local.get(local_key, float("nan"))
        target_val = targets.get(target_key, float("nan"))
        if target_key == "max_drawdown_pct":
            target_val = target_val / scale if np.isfinite(target_val) else target_val
        elif target_key == "cagr_pct":
            target_val = target_val / scale if np.isfinite(target_val) else target_val
        diff = local_val - target_val if np.isfinite(local_val) and np.isfinite(target_val) else float("nan")
        tol = tolerance.get(tol_key, float("nan"))
        if tol_key.endswith("_pp"):
            within = abs(diff * scale) <= tol if np.isfinite(diff) else False
        else:
            within = abs(diff) <= tol if np.isfinite(diff) else False
        rows.append(
            {
                "metric": target_key.replace("_pct", "").upper(),
                "quantconnect": target_val * scale if target_key in {"cagr_pct", "max_drawdown_pct"} else target_val,
                "local": local_val * scale if local_key == "cagr_net" and scale == 100 else (
                    local_val * 100 if local_key == "max_drawdown" else local_val
                ),
                "difference": diff * scale if local_key in {"cagr_net", "max_drawdown"} else diff,
                "tolerance": tol,
                "within_tolerance": within,
            }
        )
    return pd.DataFrame(rows)


def sharpe_variants(returns: pd.Series, rf_annual: float = 0.0) -> dict[str, float]:
    """Multiple Sharpe definitions for QC reconciliation audit — do not change primary metric."""
    r = _finite(returns)
    if len(r) < 2:
        return {}
    rf_daily = rf_annual / 252
    excess = r - rf_daily
    daily_rf0 = sharpe(r)
    daily_rf = sharpe(r, pd.Series(rf_daily, index=r.index))
    monthly = r.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    monthly_sharpe = float(monthly.mean() / monthly.std(ddof=1) * np.sqrt(12)) if len(monthly) > 1 and monthly.std(ddof=1) > 0 else float("nan")
    arith = float(r.mean() * 252 / ann_vol(r)) if ann_vol(r) > 0 else float("nan")
    geo_cagr = cagr(r)
    geo_vol = ann_vol(r)
    geo_sharpe = float(geo_cagr / geo_vol) if geo_vol > 0 else float("nan")
    return {
        "daily_sharpe_rf0": daily_rf0,
        "daily_sharpe_with_rf": daily_rf,
        "monthly_sharpe_rf0": monthly_sharpe,
        "arithmetic_annual_return_over_vol": arith,
        "geometric_cagr_over_vol": geo_sharpe,
    }
