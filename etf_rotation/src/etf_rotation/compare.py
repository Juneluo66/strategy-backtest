"""Daily VEC/EVT reconciliation and public-metric comparison."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_rotation.backtest import metrics
from etf_rotation.config import RotationConfig

PUBLIC_V8 = {
    "oos_total_return": 0.539,
    "max_drawdown": -0.108,
    "sharpe": 1.38,
    "calmar": 7.41,
    "vec_minus_evt_total_return": -0.019,
}


def engine_daily_diff(vec: dict[str, object], evt: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    left = vec["equity"].rename(columns={
        "nav": "vec_nav", "return": "vec_return", "exposure": "vec_exposure",
    })
    right = evt["equity"].rename(columns={
        "nav": "evt_nav", "return": "evt_return", "cash": "evt_cash", "value": "evt_value",
    })
    merged = left.merge(right, on="date", how="outer").sort_values("date")
    merged["nav_difference"] = merged["vec_nav"] - merged["evt_nav"]
    merged["return_difference"] = merged["vec_return"] - merged["evt_return"]
    first = merged.loc[merged["return_difference"].abs() > 1e-12].head(1)
    return merged, first


def write_engine_gap(vec: dict[str, object], evt: dict[str, object], directory: Path) -> None:
    daily, first = engine_daily_diff(vec, evt)
    daily.to_csv(directory / "vec_evt_daily_diff.csv", index=False)
    reason = (
        "No daily divergence detected."
        if first.empty
        else "The first divergence is a candidate for execution audit. "
             "Likely categories are integer lots, residual cash, open-vs-close timing, "
             "fees, or unavailable/failed fills; classify only after inspecting trade logs."
    )
    text = [
        "# VEC vs EVT daily reconciliation",
        "",
        f"{reason}",
        "",
        "## First divergence",
        "",
        first.to_markdown(index=False) if not first.empty else "N/A",
        "",
        (
            "The VEC engine uses float weights; EVT uses 100-share lots and cash. "
            "Any unfilled or partial order must be recorded in EVT trades, not converted to zero-return fills."
        ),
    ]
    (directory / "vec_evt_gap.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def reproduction_comparison(
    vec: dict[str, object], evt: dict[str, object], config: RotationConfig
) -> pd.DataFrame:
    """Compare the public values only against the corresponding frozen OOS partition."""
    oos_start = pd.Timestamp(config.oos_start)
    vec_equity, evt_equity = vec["equity"].copy(), evt["equity"].copy()
    vec_equity["date"], evt_equity["date"] = pd.to_datetime(vec_equity["date"]), pd.to_datetime(evt_equity["date"])
    vec_metrics = metrics(vec_equity.loc[vec_equity.date >= oos_start, "return"])
    evt_metrics = metrics(evt_equity.loc[evt_equity.date >= oos_start, "return"])
    values = [
        ("OOS total return", PUBLIC_V8["oos_total_return"], vec_metrics["total_return"], evt_metrics["total_return"]),
        ("Maximum drawdown", PUBLIC_V8["max_drawdown"], vec_metrics["max_drawdown"], evt_metrics["max_drawdown"]),
        ("Sharpe", PUBLIC_V8["sharpe"], vec_metrics["sharpe"], evt_metrics["sharpe"]),
        ("Calmar", PUBLIC_V8["calmar"], vec_metrics["calmar"], evt_metrics["calmar"]),
        ("VEC minus EVT total return", PUBLIC_V8["vec_minus_evt_total_return"],
         vec_metrics["total_return"] - evt_metrics["total_return"], vec_metrics["total_return"] - evt_metrics["total_return"]),
    ]
    return pd.DataFrame(
        {
            "metric": metric, "public_v8": public, "independent_vec": vector,
            "independent_evt": event, "difference_vs_public_evt": event - public,
            "possible_causes": "Data vendor/adjustment, PIT listing proxy, partial non-OHLCV factors, "
                               "cross-section, T+1 timing, cost, lots/cash, QDII exclusion",
        }
        for metric, public, vector, event in values
    )


def write_reproduction_comparison(
    vec: dict[str, object], evt: dict[str, object], config: RotationConfig, directory: Path
) -> None:
    table = reproduction_comparison(vec, evt, config)
    table.to_csv(directory / "reproduction_comparison.csv", index=False)
    (directory / "reproduction_comparison.md").write_text(
        "# Public v8 comparison\n\n" + table.to_markdown(index=False) +
        "\n\nPublic values are comparison references only. A partial factor set cannot be considered a full v8 replication.\n",
        encoding="utf-8",
    )
