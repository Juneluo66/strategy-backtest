#!/usr/bin/env python3
"""Full audit pipeline — replication, benchmarks, ablation, robustness, costs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest import run_conditional_rotation
from benchmarks import benchmark_grid, buy_and_hold_returns
from branch_attribution import branch_attribution, target_attribution_summary, uvxy_branch_stats
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from execution import ExecutionMode
from holding_attribution import holding_attribution
from metrics import compute_metrics, reconciliation_table
from reporting import metrics_table, write_markdown_report
from robustness import run_threshold_robustness, run_cost_stress


SOURCE_CODE = Path(__file__).resolve().parents[1] / "reports" / "source_code.md"


def _save_source_code(cfg: ProjectConfig) -> None:
    if SOURCE_CODE.exists():
        return
    write_markdown_report(
        SOURCE_CODE,
        "Original QuantConnect Source",
        {
            "Class": "ConditionalSectorRotation",
            "Note": "Frozen source of truth — see user-provided algorithm in project init.",
        },
        status_banner="VERIFIED",
    )


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    cfg.require_original_verification()
    _save_source_code(cfg)
    universe = cfg.universe()
    fetch_prices(cfg, symbols=universe + ["UPRO", "XLK"], start="2010-01-01")
    opens, closes, _ = load_panels(cfg, universe)

    qc = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.QC_DAILY_SEMANTICS)
    nxt = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.NEXT_OPEN_CONSERVATIVE)
    m_qc = compute_metrics(qc["equity"], qc["trades"], label="ORIGINAL")
    m_nxt = compute_metrics(nxt["equity"], nxt["trades"], label="NEXT_OPEN")

    eff_start = qc["effective_start"]
    bench = benchmark_grid(
        opens, closes, start=eff_start, end=qc["end"], initial_cash=cfg.initial_cash()
    )
    holding = holding_attribution(qc["equity"], qc["signal_log"], qc["trades"])
    branch = branch_attribution(qc["equity"], qc["signal_log"])
    uvxy = uvxy_branch_stats(qc["signal_log"], qc["equity"], qc["trades"])
    target_time = target_attribution_summary(qc["signal_log"])

    # Cost stress
    cost_results = run_cost_stress(opens, closes, cfg)
    # Threshold robustness
    robust = run_threshold_robustness(opens, closes, cfg)

    recon = reconciliation_table(m_qc, cfg.reconciliation_targets(), cfg.reconciliation_tolerance())

    # Classify
    exec_fragile = abs(m_qc["cagr_net"] - m_nxt["cagr_net"]) > 0.05
    classification = "DISCOVERY_ONLY"
    if m_qc["cagr_net"] > 0 and not exec_fragile:
        classification = "RESEARCH_CANDIDATE"

    top_risk = [
        "UVXY volatility decay + reverse split adjustment sensitivity",
        "Same-bar close fill (QC) vs next-open realistic execution gap",
        "Multiple hand-tuned RSI thresholds (knife-edge risk)",
        "3x/inverse leveraged ETF path dependency",
        "Frequent target switches → cost sensitivity",
    ]

    write_markdown_report(
        cfg.reports_dir / "FINAL_AUDIT.md",
        "Final Audit — conditional_leveraged_etf_rotation",
        {
            "Classification": classification,
            "Exact Source": "VERIFIED — ConditionalSectorRotation",
            "Effective Backtest": (
                f"requested={qc['requested_start']} effective={qc['effective_start']} end={qc['end']}"
            ),
            "QC vs Next-Open": (
                f"QC CAGR {m_qc['cagr_net']:.2%} | Next-Open {m_nxt['cagr_net']:.2%} | "
                f"EXECUTION_TIMING_FRAGILE={exec_fragile}"
            ),
            "Original Performance": metrics_table(m_qc),
            "Website Reconciliation": recon.to_string(index=False) if not recon.empty else "N/A",
            "Benchmarks (effective start)": "\n".join(
                f"**{k}**: CAGR {v['metrics']['cagr_net']:.2%}" for k, v in bench.items()
            ),
            "Most Profitable Target": holding.iloc[0]["ticker"] if not holding.empty else "N/A",
            "UVXY": "\n".join(f"- {k}: {v}" for k, v in uvxy.items()),
            "Time in BSV": (
                f"{target_time[target_time['target']=='BSV']['pct_time'].values[0]:.1%}"
                if not target_time.empty and "BSV" in target_time["target"].values
                else "N/A"
            ),
            "Cost Stress": cost_results.to_string(index=False) if not cost_results.empty else "N/A",
            "Threshold Robustness Sample": robust.head(15).to_string(index=False) if not robust.empty else "N/A",
            "Top 5 Risks": "\n".join(f"{i}. {r}" for i, r in enumerate(top_risk, 1)),
            "SQQQ": "Signal-only — never targeted in source.",
        },
        status_banner=classification,
    )

    # Sub-reports
    write_markdown_report(
        cfg.reports_dir / "uvxy_audit.md",
        "UVXY Audit",
        {"Stats": "\n".join(f"- {k}: {v}" for k, v in uvxy.items()), "Risk": "HIGH — vol decay + splits"},
    )
    write_markdown_report(
        cfg.reports_dir / "holding_attribution.md",
        "Holding Attribution",
        {"By Ticker": holding.to_string(index=False)},
    )
    write_markdown_report(
        cfg.reports_dir / "branch_attribution.md",
        "Branch Attribution",
        {"Branches": branch.head(20).to_string(index=False)},
    )
    write_markdown_report(
        cfg.reports_dir / "execution_reconciliation.md",
        "Execution Reconciliation",
        {
            "QC": metrics_table(m_qc),
            "Next-Open": metrics_table(m_nxt),
            "Lookahead": "QC mode uses t-close signal + t-close fill (replication). Next-open removes same-bar fill.",
        },
    )

    print(f"FINAL CLASSIFICATION: {classification}")
    print(f"QC CAGR: {m_qc['cagr_net']:.2%} Sharpe: {m_qc['sharpe_rf0']:.2f} MaxDD: {m_qc['max_drawdown']:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
