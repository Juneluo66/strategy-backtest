#!/usr/bin/env python3
"""Run exact original replication — QC daily semantics + next-open comparison."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest import run_conditional_rotation
from branch_attribution import branch_attribution, target_attribution_summary, uvxy_branch_stats
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from execution import EXECUTION_DOCS, ExecutionMode
from holding_attribution import holding_attribution
from metrics import compute_metrics
from reporting import metrics_table, write_markdown_report


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    cfg.require_original_verification()
    universe = cfg.universe()
    fetch_prices(cfg, symbols=universe, start="2010-01-01", refresh=False)
    opens, closes, _ = load_panels(cfg, universe)

    qc = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.QC_DAILY_SEMANTICS)
    nxt = run_conditional_rotation(opens, closes, cfg, mode=ExecutionMode.NEXT_OPEN_CONSERVATIVE)

    m_qc = compute_metrics(qc["equity"], qc["trades"], label="QC_DAILY")
    m_nxt = compute_metrics(nxt["equity"], nxt["trades"], label="NEXT_OPEN")

    branch = branch_attribution(qc["equity"], qc["signal_log"])
    holding = holding_attribution(qc["equity"], qc["signal_log"], qc["trades"])
    target_time = target_attribution_summary(qc["signal_log"])
    uvxy = uvxy_branch_stats(qc["signal_log"], qc["equity"], qc["trades"])

    payload = {
        "qc": {**{k: qc[k] for k in qc if k not in ("equity", "trades", "signal_log")}, "metrics": m_qc},
        "next_open": {"metrics": m_nxt},
        "uvxy": uvxy,
    }
    out_dir = cfg.reports_dir / "runs" / "exact_replication"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "payload.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    exec_doc = EXECUTION_DOCS[ExecutionMode.QC_DAILY_SEMANTICS]
    sections = {
        "Source": "QuantConnect ConditionalSectorRotation — frozen in configs/original.yaml",
        "Dates": (
            f"- Requested start: {qc['requested_start']}\n"
            f"- Effective start: {qc['effective_start']}\n"
            f"- End: {qc['end']}\n"
            f"- First signal: {qc['first_signal_date']}\n"
            f"- First trade: {qc['first_trade_date']}\n"
            f"- ETF inceptions: {qc['inceptions']}"
        ),
        "Execution Semantics (QC)": "\n".join(f"- {k}: {v}" for k, v in exec_doc.items()),
        "QC Performance": metrics_table(m_qc),
        "Next-Open Performance": metrics_table(m_nxt),
        "Execution Delta": (
            f"CAGR QC: {m_qc['cagr_net']:.2%} vs Next-Open: {m_nxt['cagr_net']:.2%} "
            f"(diff {(m_qc['cagr_net'] - m_nxt['cagr_net'])*100:.1f}pp)"
        ),
        "Decision Stats": (
            f"- Decisions: {qc['decision_count']}\n"
            f"- Target changes: {qc['target_change_count']}\n"
            f"- Actual trades: {qc['actual_trade_count']}"
        ),
        "Time in Target": target_time.to_string(index=False) if not target_time.empty else "N/A",
        "Holding Attribution": holding.to_string(index=False) if not holding.empty else "N/A",
        "Branch Attribution (top 10)": branch.head(10).to_string(index=False) if not branch.empty else "N/A",
        "UVXY Branch": "\n".join(f"- {k}: {v}" for k, v in uvxy.items()),
        "SQQQ Note": "SQQQ is signal-only; never a SetHoldings target in source code.",
    }
    write_markdown_report(cfg.reports_dir / "exact_replication.md", "Exact Replication", sections)
    print(f"QC CAGR: {m_qc['cagr_net']:.2%} | Next-Open CAGR: {m_nxt['cagr_net']:.2%}")
    print(f"Report: {cfg.reports_dir / 'exact_replication.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
