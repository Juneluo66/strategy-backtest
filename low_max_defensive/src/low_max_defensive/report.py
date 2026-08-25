"""Markdown research report writer."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _fmt(x, nd=3):
    try:
        if pd.isna(x):
            return "NA"
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def write_reports(
    path_main: Path,
    path_run: Path,
    payload: dict,
    benchmarks: pd.DataFrame,
    exclusion: pd.DataFrame,
    anatomy: pd.DataFrame,
    residual: pd.DataFrame,
    regimes: pd.DataFrame,
    crisis: pd.DataFrame,
) -> None:
    lines = [
        "# Low-MAX Defensive Research",
        "",
        "## Scope",
        "",
        "Parent project `max_effect_vix` conclusion remains frozen: "
        f"**{payload['parent_conclusion']}**.",
        "",
        "This branch does **not** re-test the MAX anomaly / short high-MAX alpha claim.",
        "Questions: long-only defensive usefulness, high-MAX as exclusion filter, "
        "and whether MAX is merely a low-vol/beta proxy.",
        "",
        "### Frozen definition (from parent PURCHASE_GATE / config_snapshot)",
        "",
        f"- MAX{payload['frozen']['top_returns']}, lookback {payload['frozen']['lookback']}",
        f"- Low-MAX: decile {payload['frozen']['decile']}, cap {payload['frozen']['cap']}",
        f"- Costs: {payload['frozen']['one_way_bps']} bp one-way; next-open execution; monthly rebalance",
        f"- Eval window: {payload['eval_window']['start']} → {payload['eval_window']['end']}",
        "",
        "### Data status",
        "",
    ]
    for k, v in payload["data_status"].items():
        lines.append(f"- `{k}`: `{v}`")
    lines.extend(["", "No paid data purchased. Style ETFs only if free Yahoo bars exist (no inception backfill).", ""])
    for note in payload.get("style_notes", []):
        lines.append(f"- {note}")

    lines.extend(["", "## Phase 1 — Benchmark comparison", "", "| Label | Net CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | β | Down β | Worst month | Ann. TO | Cost drag |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for _, r in benchmarks.iterrows():
        lines.append(
            f"| {r['label']} | {_fmt(r['net_cagr'],4)} | {_fmt(r['volatility'])} | {_fmt(r['net_sharpe'])} | "
            f"{_fmt(r['sortino'])} | {_fmt(r['max_drawdown'])} | {_fmt(r['calmar'])} | {_fmt(r['beta_spy'])} | "
            f"{_fmt(r['downside_beta'])} | {_fmt(r['worst_month'])} | {_fmt(r['annualized_turnover'])} | {_fmt(r['cost_drag_cagr'],4)} |"
        )
    lines.extend(["", "### Low-MAX vs SPY relative", ""])
    low = benchmarks.loc[benchmarks["label"] == "LOW_MAX"].iloc[0]
    lines.extend(
        [
            f"- Excess CAGR: {_fmt(low['excess_cagr'],4)}",
            f"- Tracking error: {_fmt(low['tracking_error'])}",
            f"- Information ratio: {_fmt(low['information_ratio'])}",
            f"- Upside capture: {_fmt(low['upside_capture'])}",
            f"- Downside capture: {_fmt(low['downside_capture'])}",
            "",
            "### Value checklist vs SPY",
            "",
        ]
    )
    for k, v in payload["value_vs_spy"].items():
        lines.append(f"- `{k}`: **{v}**")

    lines.extend(["", "## Phase 2 — High-MAX exclusion grid (pre-specified 10/20/30)", "", f"Flag: **{payload['exclusion_flag']}**", "", "| Label | Net CAGR | Sharpe | Sortino | MaxDD | Vol | β | Down β | Ann. TO | ΔCAGR | ΔSharpe | ΔMaxDD | ΔVol | ΔTO |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for _, r in exclusion.iterrows():
        lines.append(
            f"| {r['label']} | {_fmt(r['net_cagr'],4)} | {_fmt(r['net_sharpe'])} | {_fmt(r['sortino'])} | "
            f"{_fmt(r['max_drawdown'])} | {_fmt(r['volatility'])} | {_fmt(r['beta_spy'])} | {_fmt(r['downside_beta'])} | "
            f"{_fmt(r['annualized_turnover'])} | {_fmt(r.get('delta_cagr'),4)} | {_fmt(r.get('delta_sharpe'))} | "
            f"{_fmt(r.get('delta_max_dd'))} | {_fmt(r.get('delta_vol'))} | {_fmt(r.get('delta_turnover'))} |"
        )

    lines.extend(["", "## Phase 3 — Low-MAX anatomy", "", "Size / valuation / quality / sector: **BLOCKED_BY_PIT_DATA** (not fabricated).", "", "| Trait | Mean diff (Low-MAX − universe) | Median diff | Pct months Low-MAX lower |", "|---|---:|---:|---:|"])
    for _, r in anatomy.iterrows():
        lines.append(
            f"| {r['trait']} | {_fmt(r['mean_diff'],4)} | {_fmt(r['median_diff'],4)} | {_fmt(r['pct_months_low_max_lower'])} |"
        )
    lines.append("")
    lines.append("FF3 loadings from parent gate remain indirect evidence only (not stock-level PIT exposures).")

    lines.extend(["", "## Phase 4 — Residual / incremental value", "", f"Flag: **{payload['residual_flag']}**", "", "| Control | Variant | Δ/level CAGR | Sharpe | MaxDD |", "|---|---|---:|---:|---:|"])
    for _, r in residual.iterrows():
        lines.append(
            f"| {r['control']} | {r['variant']} | {_fmt(r['net_cagr'],4)} | {_fmt(r['net_sharpe'])} | {_fmt(r['max_drawdown'])} |"
        )

    lines.extend(["", "## Phase 5 — Regime stability", "", f"Flag: **{payload['regime_flag']}**", "", "| Regime | Strategy | Net CAGR | Sharpe | MaxDD | β | Ann. TO |", "|---|---|---:|---:|---:|---:|---:|"])
    for _, r in regimes.iterrows():
        lines.append(
            f"| {r['regime']} | {r['label']} | {_fmt(r['net_cagr'],4)} | {_fmt(r['net_sharpe'])} | "
            f"{_fmt(r['max_drawdown'])} | {_fmt(r['beta_spy'])} | {_fmt(r['annualized_turnover'])} |"
        )

    lines.extend(["", "## Phase 6 — Crisis / downside (auto-detected SPY stress windows)", ""])
    if crisis.empty:
        lines.append("No stress windows detected.")
    else:
        lines.extend(
            [
                "| Window | Type | Strategy | Crisis return | MaxDD | Downside capture | Recovery days |",
                "|---|---|---|---:|---:|---:|---:|",
            ]
        )
        for _, r in crisis.iterrows():
            lines.append(
                f"| {r['window']} | {r['type']} | {r['strategy']} | {_fmt(r['crisis_return'],4)} | "
                f"{_fmt(r['max_drawdown'])} | {_fmt(r['downside_capture'])} | {_fmt(r['recovery_days_from_trough'],0)} |"
            )

    lines.extend(
        [
            "",
            "## Phase 7 — Decision gate",
            "",
            f"### Classification: **{payload['decision']}**",
            "",
            "Rationale:",
            "",
        ]
    )
    for item in payload["rationale"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "### Multi-factor follow-on",
            "",
            "Allowed only if classification is `USEFUL_AS_RISK_FILTER`, `PROMISING_LONG_ONLY_SIGNAL`, "
            "or `NEEDS_PAID_PIT_VALIDATION` (which presupposes B/C-class free evidence). "
            "Otherwise **stop researching MAX** — do not launch `low_lottery_quality_value_momentum`.",
            "",
        ]
    )
    text = "\n".join(lines)
    path_main.write_text(text, encoding="utf-8")
    path_run.write_text(text, encoding="utf-8")
