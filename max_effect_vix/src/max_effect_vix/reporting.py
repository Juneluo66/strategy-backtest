"""Build the historical-S&P500 validation report artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .status import SIZE_BLOCKED, research_status


def write_pit_validation_report(
    directory: Path,
    *,
    metrics: dict,
    fama_macbeth_summary: dict,
    factor_result: dict,
    membership_audit: pd.DataFrame,
    exit_events: pd.DataFrame,
    ic_table: pd.DataFrame,
    limitations: list[str],
) -> Path:
    status = research_status(historical_membership=True)
    payload = {
        "status": status,
        "metrics": metrics,
        "fama_macbeth": fama_macbeth_summary,
        "factor_regression": {
            "alpha": factor_result.get("alpha"),
            "alpha_annualized": factor_result.get("alpha_annualized"),
            "t_stat": factor_result.get("t_stat"),
            "n": factor_result.get("n"),
            "qmj_status": factor_result.get("qmj_status"),
            "loadings": factor_result.get("loadings", {}),
        },
        "limitations": limitations,
    }
    (directory / "validation_metrics.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    membership_audit.to_csv(directory / "coverage_audit.csv", index=False)
    exit_events.to_csv(directory / "index_exit_events.csv", index=False)
    ic_table.to_csv(directory / "ic_by_month.csv", index=False)
    pd.DataFrame([{"gate": key, "value": value} for key, value in status.items()]).to_csv(
        directory / "validation_status.csv", index=False
    )

    mean_ic = float(ic_table["ic"].mean()) if not ic_table.empty else float("nan")
    lines = [
        "# MAX anomaly historical S&P500 validation",
        "",
        "## Status labels",
        "",
        f"- `DATA_TIER`: `{status['DATA_TIER']}`",
        f"- `SURVIVORSHIP_BIAS`: `{status['SURVIVORSHIP_BIAS']}`",
        f"- `PIT_VALIDATED`: `{status['PIT_VALIDATED']}`",
        f"- `SIZE_NEUTRAL`: `{status['SIZE_NEUTRAL']}`",
        f"- `DELISTING_RETURN`: `{status['DELISTING_RETURN']}`",
        "",
        "## 1. Data source",
        "",
        "Wikipedia historical S&P 500 constituent changes + Yahoo Finance adjusted OHLCV.",
        "Kenneth French factors used when downloadable; otherwise factor regression is marked unavailable.",
        "",
        "## 2. Universe construction",
        "",
        "Membership at each formation date is reconstructed by reversing recorded Wikipedia",
        "add/remove events from the current constituent snapshot. The Wikipedia change table",
        "is incomplete, so this only reduces current-constituent backfill bias.",
        "",
        f"Membership audit rows: {len(membership_audit)}.",
        "",
        "## 3. PIT handling",
        "",
        "`PIT_VALIDATED` is false. No point-in-time market caps, no CRSP security master,",
        "and no full-market investable universe.",
        "",
        "## 4. Delisting handling",
        "",
        "Index exits are retained through the exit date, then forced liquidated with an",
        "`INDEX_EXIT` audit row. True CRSP delisting returns are unavailable;",
        "last traded prices may act only as `DELIST_PROXY` and are labeled as such.",
        f"Recorded index-exit events: {len(exit_events)}.",
        "",
        "## 5. Signal definition",
        "",
        "MAX5 = mean of the top 5 daily returns over the prior 21 completed trading days.",
        "Vol/beta residualization uses only pre-formation price history.",
        "",
        "## 6. Portfolio construction",
        "",
        "Lowest MAX decile, capped at 25 names, equal weight. Signal at prior close;",
        "execution at next session open.",
        "",
        "## 7. Transaction cost",
        "",
        "Default 5 bp one-way on measured turnover, plus financing/borrow assumptions from frozen config.",
        "",
        "## 8. Turnover",
        "",
        f"- one_way_turnover: {metrics.get('one_way_turnover', float('nan'))}",
        f"- annualized_turnover: {metrics.get('annualized_turnover', float('nan'))}",
        "",
        "## 9. Factor exposures",
        "",
        f"- Gross Sharpe: {metrics.get('gross_sharpe', float('nan'))}",
        f"- After-cost Sharpe: {metrics.get('net_sharpe', float('nan'))}",
        f"- Mean monthly Spearman IC: {mean_ic}",
        f"- Fama-MacBeth MAX slope: {fama_macbeth_summary.get('mean_max_slope')} (t={fama_macbeth_summary.get('t_stat')})",
        f"- Size in Fama-MacBeth: `{fama_macbeth_summary.get('size_status', SIZE_BLOCKED)}`",
        f"- Factor alpha (monthly): {factor_result.get('alpha')} (t={factor_result.get('t_stat')})",
        f"- Factor loadings: {factor_result.get('loadings')}",
        f"- QMJ: {factor_result.get('qmj_status')}",
        "",
        "## 10. Limitations",
        "",
    ]
    for item in limitations:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Gate decision",
            "",
            "Independent-alpha claim requires PIT market caps, full delisting returns, and",
            "`PIT_VALIDATED=true`. This run cannot clear that gate.",
            "",
        ]
    )
    path = directory / "max_anomaly_pit_validation.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
