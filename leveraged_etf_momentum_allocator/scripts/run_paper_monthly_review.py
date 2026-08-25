#!/usr/bin/env python3
"""Monthly forward review for PAPER_V1 — never retunes parameters."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reporting import write_markdown_report


def main() -> int:
    month = sys.argv[1] if len(sys.argv) > 1 else None  # YYYY-MM
    signals = ROOT / "logs" / "paper_signals.csv"
    metrics = ROOT / "logs" / "paper_daily_metrics.csv"
    shadows = ROOT / "logs" / "paper_shadows.csv"
    if not metrics.exists() or not signals.exists():
        raise SystemExit("No paper logs yet — run init_paper_v1 + run_paper_day first")

    m = pd.read_csv(metrics)
    s = pd.read_csv(signals)
    if m.empty:
        raise SystemExit("Empty metrics — no forward days yet")
    m["date"] = pd.to_datetime(m["date"])
    s["date"] = pd.to_datetime(s["date"])
    if month is None:
        month = m["date"].max().strftime("%Y-%m")

    start = pd.Timestamp(month + "-01")
    end = (start + pd.offsets.MonthEnd(0))
    mm = m[(m["date"] >= start) & (m["date"] <= end)]
    ss = s[(s["date"] >= start) & (s["date"] <= end)]
    if mm.empty:
        raise SystemExit(f"No metrics for {month}")

    paper_ret = float(mm["nav"].iloc[-1] / mm["nav"].iloc[0] - 1) if len(mm) > 1 else float(mm["return"].sum())
    maxdd = float(mm["drawdown"].min()) if "drawdown" in mm else float("nan")
    turnover = float(mm["turnover"].sum()) if "turnover" in mm else float("nan")
    branches = ss["branch_id"].value_counts().to_string() if not ss.empty else "n/a"
    targets = ss["raw_target"].value_counts().to_string() if not ss.empty else "n/a"

    shadow_txt = "n/a"
    if shadows.exists():
        sh = pd.read_csv(shadows)
        sh["date"] = pd.to_datetime(sh["date"])
        sh = sh[(sh["date"] >= start) & (sh["date"] <= end)]
        if len(sh) >= 2:
            def _r(col):
                return float(sh[col].iloc[-1] / sh[col].iloc[0] - 1)
            shadow_txt = "\n".join(
                [
                    f"- Paper V1 (SHADOW_C): {_r('SHADOW_C_nav'):.2%}",
                    f"- ORIGINAL full (SHADOW_A): {_r('SHADOW_A_nav'):.2%}",
                    f"- Robust full (SHADOW_B): {_r('SHADOW_B_nav'):.2%}",
                    f"- TQQQ (SHADOW_D): {_r('SHADOW_D_nav'):.2%}",
                    f"- SPY (SHADOW_E): {_r('SHADOW_E_nav'):.2%}",
                ]
            )

    out = ROOT / "reports" / "paper" / f"{month}.md"
    write_markdown_report(
        out,
        f"PAPER_V1 Monthly Review — {month}",
        {
            "Policy": "Do **not** change PAPER_V1 parameters based on this review. Create PAPER_V2 if needed.",
            "Paper V1 Return": f"{paper_ret:.2%}",
            "MaxDD (intra-month from logged drawdown)": f"{maxdd:.2%}",
            "Turnover (sum)": f"{turnover:.4f}",
            "Slippage assumption": "5 bps base case (shadows 0/10/25 bps reporting-only)",
            "Benchmarks / Shadows": shadow_txt,
            "Branch usage": branches,
            "Target usage": targets,
            "Unexpected behavior": "_Manual review — fill if signal/data/execution anomalies observed._",
            "Signal/data errors": "_None logged automatically. Inspect `logs/paper_signals.csv`._",
            "Stop-condition check": "\n".join(
                [
                    "- DATA_FAILURE: review missing ticks / indicator NaNs",
                    "- EXECUTION_FAILURE: review fills vs next-open assumption",
                    "- MODEL_WARNING: rolling underperformance vs SHADOW_D/E — warning only",
                ]
            ),
        },
        status_banner="FORWARD_REVIEW",
    )
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
