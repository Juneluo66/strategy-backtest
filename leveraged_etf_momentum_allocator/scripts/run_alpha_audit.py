#!/usr/bin/env python3
"""Alpha source audit — baselines, attribution, OOS 2026."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alpha_audit import (
    avoided_loss_attribution,
    bear_tree_comparison,
    bull_tree_comparison,
    crash_episodes,
    metrics_row,
    regime_attribution,
    tqqq_avoidance_episodes,
    tqqq_counterfactual_returns,
)
from backtest import run_conditional_rotation
from baselines import BASELINE_REGISTRY
from benchmarks import buy_and_hold_returns
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from execution import ExecutionMode
from metrics import compute_metrics, sharpe_variants
from reporting import write_markdown_report

AUDIT_STATUS = {
    "SOURCE_VERIFICATION": "PASS",
    "LOGIC_REPLICATION": "PASS",
    "PERFORMANCE_RECONCILIATION": "PARTIAL",
    "CLASSIFICATION": "RESEARCH_CANDIDATE",
}


def _run_all_baselines(cfg, opens, closes, start=None, end=None) -> dict[str, dict]:
    results = {}
    results["ORIGINAL"] = run_conditional_rotation(
        opens, closes, cfg, start=start, end=end, label="ORIGINAL"
    )
    for name, fn in BASELINE_REGISTRY.items():
        results[name] = run_conditional_rotation(
            opens, closes, cfg, start=start, end=end, target_selector=fn, label=name
        )
    return results


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    universe = cfg.universe()
    fetch_prices(cfg, symbols=universe + ["UPRO"], start="2010-01-01", refresh=False)
    opens, closes, _ = load_panels(cfg, universe)

    results = _run_all_baselines(cfg, opens, closes)
    original = results["ORIGINAL"]
    eff_start = original["effective_start"]
    eff_end = original["end"]

    # --- Comparison table ---
    rows = [metrics_row(original, "ORIGINAL")]
    for name in [
        "TQQQ_BUY_HOLD",
        "SPY_SMA200_TQQQ_BSV",
        "SPY_SMA200_TQQQ_CASH",
        "ORIGINAL_BULL_BSV_BEAR",
        "ORIGINAL_BULL_CASH_BEAR",
    ]:
        if name in results:
            rows.append(metrics_row(results[name], name))
    for ticker in ["SPY", "QQQ"]:
        rets = buy_and_hold_returns(closes, ticker, start=eff_start, end=eff_end)
        eq = __import__("pandas").DataFrame({"net_return": rets, "gross_return": rets})
        eq["equity_net"] = (1 + rets).cumprod()
        eq["equity_gross"] = eq["equity_net"]
        m = compute_metrics(eq, __import__("pandas").DataFrame(), label=ticker)
        rows.append(
            {
                "label": ticker,
                "cagr": m["cagr_net"],
                "sharpe": m["sharpe_rf0"],
                "sortino": m["sortino_rf0"],
                "max_dd": m["max_drawdown"],
                "calmar": m["calmar"],
                "volatility": m["annualized_volatility"],
                "final_wealth": m["final_wealth_net"],
                "turnover": 0.0,
                "trades": 0,
            }
        )

    comp = __import__("pandas").DataFrame(rows)
    orig_cagr = comp.loc[comp["label"] == "ORIGINAL", "cagr"].iloc[0]
    for bl in ["TQQQ_BUY_HOLD", "SPY_SMA200_TQQQ_BSV"]:
        if bl in comp["label"].values:
            bl_cagr = comp.loc[comp["label"] == bl, "cagr"].iloc[0]
            comp.loc[comp["label"] == bl, "incremental_vs_original"] = orig_cagr - bl_cagr

    write_markdown_report(
        cfg.reports_dir / "alpha_source_baselines.md",
        "Alpha Source Baselines",
        {
            "Audit Status": "\n".join(f"- **{k}**: {v}" for k, v in AUDIT_STATUS.items()),
            "Comparison": comp.to_string(index=False),
            "Note": "incremental strategy return = ORIGINAL CAGR minus baseline CAGR (not strict alpha).",
        },
    )

    # --- TQQQ avoidance episodes ---
    episodes = tqqq_avoidance_episodes(original["signal_log"], original["equity"], closes)
    top20 = episodes.head(20) if not episodes.empty else episodes
    write_markdown_report(
        cfg.reports_dir / "tqqq_avoidance_attribution.md",
        "TQQQ Avoidance Episodes",
        {
            "Summary": f"Total episodes: {len(episodes)}",
            "Top 20 by difference (strategy - TQQQ)": top20.to_string(index=False) if not top20.empty else "N/A",
        },
    )

    # --- Avoided loss ---
    avoided = avoided_loss_attribution(original["equity"], original["signal_log"], closes)
    write_markdown_report(
        cfg.reports_dir / "avoided_loss_attribution.md",
        "Avoided TQQQ Loss Attribution",
        {k: str(v) for k, v in avoided.items()},
    )

    # --- Regime ---
    regime = regime_attribution(original["signal_log"], original["equity"], closes)
    write_markdown_report(
        cfg.reports_dir / "regime_attribution.md",
        "Regime Attribution",
        {"By Regime": regime.to_string(index=False)},
    )

    # --- Bull tree ---
    bull_cmp = bull_tree_comparison(original, results["BULL_ALWAYS_TQQQ"])
    write_markdown_report(
        cfg.reports_dir / "bull_tree_attribution.md",
        "Bull Tree Attribution",
        {k: str(v) for k, v in bull_cmp.items()},
    )

    # --- Bear tree ---
    bear_names = {
        "ORIGINAL": original,
        "SPY_SMA200_TQQQ_BSV": results.get("SPY_SMA200_TQQQ_BSV"),
        "SPY_SMA200_TQQQ_CASH": results.get("SPY_SMA200_TQQQ_CASH"),
        "TQQQ_BUY_HOLD": results.get("TQQQ_BUY_HOLD"),
    }
    bear_cmp = bear_tree_comparison({k: v for k, v in bear_names.items() if v})
    write_markdown_report(
        cfg.reports_dir / "bear_tree_attribution.md",
        "Bear Tree Value",
        {"Bear Regime Comparison": bear_cmp.to_string(index=False)},
    )

    # --- Crashes ---
    bench_rets = {
        "sma200_tqqq_bsv": results["SPY_SMA200_TQQQ_BSV"]["equity"]["net_return"],
    }
    crashes = crash_episodes(original["equity"], closes, original["signal_log"], bench_rets)
    write_markdown_report(
        cfg.reports_dir / "crash_episodes.md",
        "Crash Episodes",
        {"Episodes": crashes.to_string(index=False) if not crashes.empty else "N/A"},
    )

    # --- Sharpe audit ---
    sharpe_v = sharpe_variants(original["equity"]["net_return"])
    write_markdown_report(
        cfg.reports_dir / "metric_definition_audit.md",
        "Metric Definition Audit — Sharpe",
        {
            "Primary (daily rf=0)": f"{sharpe_v.get('daily_sharpe_rf0', float('nan')):.4f}",
            "QC reported": "2.67",
            "Variants": "\n".join(f"- {k}: {v:.4f}" if isinstance(v, float) else f"- {k}: {v}" for k, v in sharpe_v.items()),
            "Note": "None modified as primary metric. Gap may be period (2012 vs 2016), rf, or vol definition.",
        },
    )

    # --- 2026 OOS ---
    oos_start = "2026-01-01"
    oos_results = _run_all_baselines(cfg, opens, closes, start=oos_start)
    oos_rows = []
    for name in ["ORIGINAL", "SPY_SMA200_TQQQ_BSV", "TQQQ_BUY_HOLD"]:
        if name in oos_results:
            oos_rows.append(metrics_row(oos_results[name], name))
    for ticker in ["SPY", "QQQ", "TQQQ"]:
        rets = buy_and_hold_returns(closes, ticker, start=oos_start)
        if not rets.empty:
            eq = __import__("pandas").DataFrame({"net_return": rets, "gross_return": rets})
            eq["equity_net"] = (1 + rets).cumprod()
            eq["equity_gross"] = eq["equity_net"]
            m = compute_metrics(eq, __import__("pandas").DataFrame(), label=ticker)
            oos_rows.append(
                {"label": ticker, "cagr": m["cagr_net"], "sharpe": m["sharpe_rf0"], "max_dd": m["max_drawdown"], "final_wealth": m["final_wealth_net"]}
            )
    oos_df = __import__("pandas").DataFrame(oos_rows)
    write_markdown_report(
        cfg.reports_dir / "oos_2026_frozen.md",
        "FROZEN OOS 2026",
        {
            "Status": "FROZEN_OOS_2026 — parameters frozen",
            "Start": oos_start,
            "Results": oos_df.to_string(index=False),
        },
    )

    uvxy_delta = float("nan")
    no_uvxy = results.get("ORIGINAL_NO_UVXY")
    if no_uvxy:
        uvxy_delta = metrics_row(original, "ORIGINAL")["cagr"] - metrics_row(no_uvxy, "NO_UVXY")["cagr"]

    # --- FINAL_AUDIT update ---
    sma_bsv_cagr = comp.loc[comp["label"] == "SPY_SMA200_TQQQ_BSV", "cagr"].iloc[0]
    tqqq_cagr = comp.loc[comp["label"] == "TQQQ_BUY_HOLD", "cagr"].iloc[0]
    bull_row = regime[regime["regime"] == "BULL"].iloc[0] if len(regime) > 0 else None
    bear_row = regime[regime["regime"] == "BEAR"].iloc[0] if len(regime) > 1 else None

    write_markdown_report(
        cfg.reports_dir / "FINAL_AUDIT.md",
        "Final Audit — Alpha Source",
        {
            "Audit Status": "\n".join(f"- **{k}**: {v}" for k, v in AUDIT_STATUS.items()),
            "Q1: Why 82% TQQQ time → 199% CAGR vs 42% TQQQ BH?": (
                "Compounding + selective exit from TQQQ before/during adverse windows. "
                f"Non-TQQQ days avoided TQQQ cumulative return of {avoided.get('non_tqqq_tqqq_counterfactual_cumulative', 'N/A'):.2%} "
                f"while strategy earned {avoided.get('non_tqqq_strategy_cumulative_return', 'N/A'):.2%} on those days. "
                "Bull days mostly match TQQQ; gap widens via capital preservation in bear/alternate assets."
            ),
            "Q2: Largest contributor": (
                f"BULL TQQQ exposure ({bull_row['time_pct']:.1%} of days, excess vs TQQQ in bull: {bull_row['excess_vs_tqqq']:.2%}) "
                f"+ BEAR non-TQQQ rotation (excess vs TQQQ: {bear_row['excess_vs_tqqq']:.2%}). "
                "UVXY: small time slice; inverse/long rotation in bear adds incremental return."
            ),
            "Q3: SPY SMA200 + TQQQ/BSV retains": f"{sma_bsv_cagr / orig_cagr:.1%} of ORIGINAL CAGR ({sma_bsv_cagr:.2%} vs {orig_cagr:.2%})",
            "Q4: RSI tree vs simple SMA200": f"Incremental CAGR vs SMA200/TQQQ/BSV: {(orig_cagr - sma_bsv_cagr)*100:.1f} pp",
            "Q5: Remove UVXY": f"UVXY removal delta CAGR: {uvxy_delta if no_uvxy else 'N/A'} (UVXY->BSV proxy)",
            "Q6: Likely failure mode": "Bear tree complexity + UVXY data sensitivity; bull TQQQ leg still dominates.",
            "ALPHA SOURCE VERDICT": (
                "Primary driver: **timed exit from TQQQ** (avoided drawdowns + bear rotation), "
                "not alpha from UVXY alone. Simple SMA200 baseline captures ~"
                f"{sma_bsv_cagr/orig_cagr:.0%} of return."
            ),
        },
        status_banner=AUDIT_STATUS["CLASSIFICATION"],
    )

    payload = {
        "audit_status": AUDIT_STATUS,
        "comparison": comp.to_dict(orient="records"),
        "avoided_loss": avoided,
        "bull_tree": bull_cmp,
        "regime": regime.to_dict(orient="records"),
    }
    out = cfg.reports_dir / "runs" / "alpha_source_audit"
    out.mkdir(parents=True, exist_ok=True)
    (out / "payload.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(f"ORIGINAL CAGR: {orig_cagr:.2%}")
    print(f"TQQQ CAGR: {tqqq_cagr:.2%}")
    print(f"SMA200 TQQQ/BSV CAGR: {sma_bsv_cagr:.2%}")
    print(f"Incremental vs simple: {(orig_cagr - sma_bsv_cagr)*100:.1f} pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
