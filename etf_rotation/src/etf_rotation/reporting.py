"""Research reports, OOS splits, and serial stress-test summaries."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from etf_rotation.backtest import event_backtest, vector_backtest
from etf_rotation.config import RotationConfig

DISCLAIMER = """# ETF Rotation Research Summary

This is a research-grade free-data approximation of the public v8.0 strategy, not an
exact replication and not investment advice. AkShare history, adjustment methodology,
non-OHLCV coverage, QDII timing, and fill assumptions can differ materially from QMT
production data. Public backtest and short live figures are comparison references only.
Parameters are frozen before the 2025-05-01 out-of-sample window; do not retune on OOS.
"""


def save_result(result: dict[str, object], directory: Path, stem: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in result.items():
        if isinstance(frame, pd.DataFrame):
            frame.to_csv(directory / f"{stem}_{name}.csv", index=False)


def _metric_row(name: str, result: dict[str, object]) -> dict[str, object]:
    return {"variant": name, "engine": result["engine"], **result["metrics"],
            "trades": len(result.get("trades", []))}


def render_summary(results: dict[str, dict[str, object]], output: Path) -> pd.DataFrame:
    rows = [_metric_row(name, result) for name, result in results.items()]
    table = pd.DataFrame(rows)
    vec = table.loc[table.engine.eq("VEC")].set_index("variant")
    evt = table.loc[table.engine.eq("EVT")].set_index("variant")
    gaps = (vec["total_return"] - evt["total_return"]).rename("vec_minus_evt_total_return")
    gap_table = gaps.rename_axis("variant").reset_index()
    body = [DISCLAIMER, "\n## Variant results\n", table.to_markdown(index=False), "\n## VEC−EVT gap\n",
            gap_table.to_markdown(index=False),
            "\nA gap above 5 percentage points is a release blocker requiring signal, execution, or cost audit.\n"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(body), encoding="utf-8")
    gap_table.to_csv(output.with_name("vec_evt_gap.csv"), index=False)
    return table


def oos_metrics(result: dict[str, object], config: RotationConfig) -> pd.DataFrame:
    equity = result["equity"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    rows = []
    for name, mask in {"IS": equity.date <= pd.Timestamp(config.training_end),
                       "OOS": equity.date >= pd.Timestamp(config.oos_start)}.items():
        values = equity.loc[mask, "return"]
        from etf_rotation.backtest import metrics
        rows.append({"partition": name, **metrics(values), "observations": len(values)})
    return pd.DataFrame(rows)


def serial_robustness(scores: pd.DataFrame, prices: dict[str, pd.DataFrame], config: RotationConfig) -> pd.DataFrame:
    """One-at-a-time serial neighbourhood checks; no OOS selection."""
    specs = [("base", {}), ("frequency=3", {"frequency": 3}), ("frequency=10", {"frequency": 10}),
             ("min_hold=5", {"min_hold_days": 5}), ("min_hold=15", {"min_hold_days": 15}),
             ("delta=0.05", {"delta_rank": 0.05}), ("delta=0.15", {"delta_rank": 0.15}),
             ("pos=3", {"position_size": 3}), ("pos=5", {"position_size": 5})]
    rows = []
    for name, changes in specs:
        result = vector_backtest(scores, prices, replace(config, **changes))
        rows.append({"spec": name, **result["metrics"]})
    return pd.DataFrame(rows)


def cost_stress(scores: pd.DataFrame, prices: dict[str, pd.DataFrame],
                config: RotationConfig) -> pd.DataFrame:
    """One-dimensional 2/5/10bp cost stress, held outside parameter selection."""
    rows = []
    for bp in (2, 5, 10):
        result = vector_backtest(scores, prices, replace(config, commission_a_share=bp / 10_000))
        rows.append({"one_way_cost_bp": bp, **result["metrics"]})
    return pd.DataFrame(rows)


def environment_splits(result: dict[str, object]) -> pd.DataFrame:
    """Calendar-regime attribution without using the split to choose parameters."""
    equity = result["equity"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    windows = {
        "2020_pandemic": ("2020-01-01", "2020-12-31"),
        "2021_growth": ("2021-01-01", "2021-12-31"),
        "2022_drawdown": ("2022-01-01", "2022-12-31"),
        "2023_range": ("2023-01-01", "2023-12-31"),
        "2024_small_cap": ("2024-01-01", "2024-12-31"),
        "2025_rotation": ("2025-01-01", "2025-12-31"),
    }
    from etf_rotation.backtest import metrics

    return pd.DataFrame(
        {"environment": name, "observations": len(selected),
         **metrics(selected["return"])}
        for name, (start, end) in windows.items()
        if not (selected := equity.loc[equity.date.between(start, end)]).empty
    )


def rolling_oos_validation(result: dict[str, object], window_days: int = 60) -> pd.DataFrame:
    """Frozen-strategy rolling OOS diagnostics; it never selects a new factor set."""
    equity = result["equity"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    from etf_rotation.backtest import metrics

    rows = []
    for start in range(0, len(equity), window_days):
        selected = equity.iloc[start:start + window_days]
        if len(selected) < window_days:
            continue
        rows.append({
            "start": selected["date"].iloc[0],
            "end": selected["date"].iloc[-1],
            "observations": len(selected),
            **metrics(selected["return"]),
        })
    return pd.DataFrame(rows)


def cost_capacity_stress(scores: pd.DataFrame, prices: dict[str, pd.DataFrame],
                         config: RotationConfig) -> pd.DataFrame:
    """Serial integer-lot capacity stress; VWAP variants remain explicitly unavailable."""
    rows = []
    for capital in (100_000, 500_000, 1_000_000, 5_000_000, 10_000_000):
        for commission_bp in (2, 5, 10):
            for slippage_bp in (0, 5, 10, 20):
                for adv_pct in (0.01, 0.02, 0.03):
                    tested = replace(
                        config, initial_capital=capital, commission_a_share=commission_bp / 10_000,
                        slippage_rate=slippage_bp / 10_000, max_order_adv_pct=adv_pct,
                    )
                    result = event_backtest(scores, prices, tested)
                    trades = result["trades"]
                    rows.append({
                        "initial_capital": capital, "commission_bp": commission_bp,
                        "slippage_bp": slippage_bp, "max_order_adv_pct": adv_pct,
                        "execution_rule": "next_open", "vwap_status": "unavailable_no_minute_data",
                        "open_5m_vwap_status": "unavailable_no_minute_data",
                        "unfilled_orders": int((trades.get("status", pd.Series(dtype=str)) == "unfilled").sum()),
                        **result["metrics"],
                    })
    return pd.DataFrame(rows)
