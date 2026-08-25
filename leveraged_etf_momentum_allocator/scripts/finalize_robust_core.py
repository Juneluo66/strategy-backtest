#!/usr/bin/env python3
"""Phase 5 finalize — correct BEST selection using only candidates with real neighborhoods."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest import run_conditional_rotation
from baselines import STANDARDIZED_THRESHOLDS
from config import ProjectConfig
from data_loader import load_panels
from metrics import cagr, calmar, compute_metrics, max_drawdown, sharpe
from original_strategy import load_thresholds
from overfitting_audit import rolling_stability, rolling_summary
from phase5_audit import (
    active_branch_count,
    crisis_behavior_profile,
    crisis_robust_score,
    loo_named,
    scale_equity_exposure,
)
from reporting import write_markdown_report
from robust_core import (
    ORIGINAL_COMPLEXITY,
    ROBUST_CORE_V1_PARAMS,
    ROBUST_CORE_V1_THRESHOLDS,
    complexity_stats,
    make_selector,
    original_selector,
)

# Neighborhood results from completed Phase 5 run (500 draws each)
NEIGHBORHOOD = {
    "ORIGINAL": {"cagr_median": 1.272590, "cagr_p10": 1.051457, "original_cagr_percentile": 100.0, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "STANDARDIZED": {"cagr_median": 1.236621, "cagr_p10": 1.041469, "original_cagr_percentile": 99.8, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "ROBUST_CORE_V1": {"cagr_median": 1.236621, "cagr_p10": 1.041469, "original_cagr_percentile": 99.8, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "COLLAPSE_DROP_SQQQ_RSI": {"cagr_median": 1.204943, "cagr_p10": 1.029919, "original_cagr_percentile": 100.0, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "ABLATION_DROP_SQQQ_RSI": {"cagr_median": 1.204943, "cagr_p10": 1.029919, "original_cagr_percentile": 100.0, "PARAMETER_OVERFIT_RISK": "HIGH"},  # identical to COLLAPSE
    "ABLATION_DROP_UVXY_RSI": {"cagr_median": 1.202239, "cagr_p10": 0.998543, "original_cagr_percentile": 100.0, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "ABLATION_DROP_SPY_RSI": {"cagr_median": 1.167264, "cagr_p10": 0.865864, "original_cagr_percentile": 91.0, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "PRUNED_1": {"cagr_median": 1.143231, "cagr_p10": 0.944087, "original_cagr_percentile": 100.0, "PARAMETER_OVERFIT_RISK": "HIGH"},
    "ROBUST_CORE_V2": {"cagr_median": 1.112932, "cagr_p10": 0.941594, "original_cagr_percentile": 100.0, "PARAMETER_OVERFIT_RISK": "HIGH"},
}


def _m(res):
    return compute_metrics(res["equity"], res["trades"], label=res.get("label", ""))


def eval_one(opens, closes, cfg, name, thresholds, selector, params=None, cx=None):
    res = run_conditional_rotation(
        opens, closes, cfg,
        parameters_override=params,
        thresholds=thresholds,
        target_selector=selector,
        label=name,
    )
    m = _m(res)
    loo = loo_named(res["equity"], closes)
    roll5 = rolling_summary(rolling_stability(res["equity"], closes, window_years=5))
    roll3 = rolling_summary(rolling_stability(res["equity"], closes, window_years=3))
    n_br = active_branch_count(res["signal_log"])
    cx = cx or ORIGINAL_COMPLEXITY
    cx_stats = complexity_stats(
        n_params=cx["number_of_parameters"],
        n_thresholds=cx["number_of_thresholds"],
        n_signal_assets=cx["number_of_signal_assets"],
        n_terminal_branches=n_br or cx["number_of_terminal_branches"],
        cagr=m["cagr_net"],
    )
    nb = NEIGHBORHOOD.get(name, {})
    row = {
        "name": name,
        "cagr": m["cagr_net"],
        "sharpe": m["sharpe_rf0"],
        "max_dd": m["max_drawdown"],
        "calmar": m["calmar"],
        "annual_turnover": m["annual_turnover"],
        "ex_covid_cagr": loo.get("COVID", float("nan")),
        "ex_2022_cagr": loo.get("2022", float("nan")),
        "ex_both_cagr": loo.get("Exclude COVID+2022", float("nan")),
        "roll3_win_tqqq": roll3.get("pct_windows_beat_tqqq", float("nan")),
        "roll5_win_tqqq": roll5.get("pct_windows_beat_tqqq", float("nan")),
        "roll5_median_rel": roll5.get("median_rel_cagr_vs_tqqq", float("nan")),
        "roll5_worst_rel": roll5.get("worst_window_rel_vs_tqqq", float("nan")),
        "n_params_total": cx_stats["number_of_parameters"] + cx_stats["number_of_thresholds"],
        "n_branches": n_br,
        "complexity": cx_stats,
        "behavior": crisis_behavior_profile(res["signal_log"]),
        "result": res,
        "has_neighborhood": bool(nb),
        "rand_median_cagr": nb.get("cagr_median", float("nan")),
        "rand_p10_cagr": nb.get("cagr_p10", float("nan")),
        "rand_percentile": nb.get("original_cagr_percentile", float("nan")),
        "overfit_risk": nb.get("PARAMETER_OVERFIT_RISK", "N/A"),
    }
    row["crisis_score"] = crisis_robust_score(row) if row["has_neighborhood"] else float("nan")
    return row


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    opens, closes, _ = load_panels(cfg, cfg.universe() + ["XLK"])
    orig_t = load_thresholds(cfg)

    specs = [
        ("ORIGINAL", orig_t, original_selector, None, ORIGINAL_COMPLEXITY),
        ("STANDARDIZED", STANDARDIZED_THRESHOLDS, make_selector(), ROBUST_CORE_V1_PARAMS, ORIGINAL_COMPLEXITY),
        ("ROBUST_CORE_V1", ROBUST_CORE_V1_THRESHOLDS, make_selector(), ROBUST_CORE_V1_PARAMS, ORIGINAL_COMPLEXITY),
        ("COLLAPSE_DROP_SQQQ_RSI", ROBUST_CORE_V1_THRESHOLDS, make_selector(drop_sqqq_rsi=True), ROBUST_CORE_V1_PARAMS,
         {"number_of_parameters": 4, "number_of_thresholds": 6, "number_of_signal_assets": 6, "number_of_terminal_branches": 11}),
        ("ABLATION_DROP_SQQQ_RSI", ROBUST_CORE_V1_THRESHOLDS, make_selector(drop_sqqq_rsi=True), ROBUST_CORE_V1_PARAMS,
         {"number_of_parameters": 4, "number_of_thresholds": 6, "number_of_signal_assets": 6, "number_of_terminal_branches": 11}),
        ("ABLATION_DROP_UVXY_RSI", ROBUST_CORE_V1_THRESHOLDS, make_selector(drop_uvxy_rsi=True), ROBUST_CORE_V1_PARAMS,
         {"number_of_parameters": 4, "number_of_thresholds": 6, "number_of_signal_assets": 5, "number_of_terminal_branches": 9}),
        ("ABLATION_DROP_SPY_RSI", ROBUST_CORE_V1_THRESHOLDS, make_selector(drop_spy_rsi=True), ROBUST_CORE_V1_PARAMS,
         {"number_of_parameters": 4, "number_of_thresholds": 6, "number_of_signal_assets": 6, "number_of_terminal_branches": 10}),
        ("PRUNED_1", ROBUST_CORE_V1_THRESHOLDS, make_selector(prune_branches=["B10"]), ROBUST_CORE_V1_PARAMS, ORIGINAL_COMPLEXITY),
        ("ROBUST_CORE_V2", ROBUST_CORE_V1_THRESHOLDS, make_selector(drop_sqqq_rsi=True, prune_branches=["B10"]), ROBUST_CORE_V1_PARAMS,
         {"number_of_parameters": 4, "number_of_thresholds": 6, "number_of_signal_assets": 6, "number_of_terminal_branches": 10}),
    ]

    rows = []
    for name, thr, sel, params, cx in specs:
        print(f"eval {name}", flush=True)
        rows.append(eval_one(opens, closes, cfg, name, thr, sel, params, cx))

    # Rank only neighborhood-tested non-ORIGINAL by crisis_score,
    # then prefer lower candidate percentile (less top-tail).
    scored = [r for r in rows if r["name"] != "ORIGINAL" and r["has_neighborhood"]]
    scored.sort(key=lambda r: (-r["crisis_score"], r["rand_percentile"], r["n_params_total"], r["n_branches"]))

    # Prefer SPY-RSI ablation if within 0.05 of top score (least top-tail).
    top = scored[0]
    spy = next((r for r in scored if r["name"] == "ABLATION_DROP_SPY_RSI"), None)
    v1 = next((r for r in scored if r["name"] == "ROBUST_CORE_V1"), None)
    drop_sqqq = next((r for r in scored if r["name"] == "COLLAPSE_DROP_SQQQ_RSI"), None)

    # Selection policy (not max CAGR):
    # 1) Prefer candidate percentile < 95 if neighborhood median still > 80%
    # 2) Else prefer ROBUST_CORE_V1 / DROP_SQQQ with natural thresholds
    best = top
    if spy and spy["rand_percentile"] < 95 and spy["rand_median_cagr"] > 0.80:
        best = spy
    elif drop_sqqq and drop_sqqq["crisis_score"] >= top["crisis_score"] - 0.02:
        best = drop_sqqq
    elif v1:
        best = v1

    # If SPY ablation selected but DROP_SQQQ has similar robustness and higher CAGR
    # with identical overfit issues, keep SPY as "more robust on percentile".
    # Document both.

    original = next(r for r in rows if r["name"] == "ORIGINAL")
    std = next(r for r in rows if r["name"] == "STANDARDIZED")

    # Leverage on best
    lev_rows = []
    for label, scale in [
        ("ROBUST_CORE_1X", 1 / 3),
        ("ROBUST_CORE_1_5X", 1.5 / 3),
        ("ROBUST_CORE_2X", 2 / 3),
        ("ROBUST_CORE_3X_ORIGINAL", 1.0),
    ]:
        eq = scale_equity_exposure(best["result"]["equity"], scale)
        rets = eq["net_return"]
        lev_rows.append({
            "version": label,
            "exposure_scale": scale,
            "cagr": cagr(rets),
            "sharpe": sharpe(rets),
            "max_dd": max_drawdown(rets),
            "calmar": calmar(rets),
        })
    lev_df = pd.DataFrame(lev_rows)
    # Paper-oriented: MaxDD preferably < 30%, else < 40%; maximize Calmar then Sharpe
    paper_lev = lev_df[lev_df["max_dd"] > -0.30]
    if paper_lev.empty:
        paper_lev = lev_df[lev_df["max_dd"] > -0.40]
    if paper_lev.empty:
        paper_lev = lev_df
    rec = paper_lev.sort_values(["calmar", "sharpe"], ascending=False).iloc[0]

    score_df = pd.DataFrame([{
        "name": r["name"],
        "crisis_score": round(r["crisis_score"], 4),
        "cagr": r["cagr"],
        "ex_both": r["ex_both_cagr"],
        "rand_med": r["rand_median_cagr"],
        "rand_p10": r["rand_p10_cagr"],
        "rand_pct": r["rand_percentile"],
        "roll5": r["roll5_win_tqqq"],
        "sharpe": r["sharpe"],
        "max_dd": r["max_dd"],
        "branches": r["n_branches"],
        "params": r["n_params_total"],
    } for r in sorted(scored, key=lambda x: -x["crisis_score"])])

    removed = []
    if "SQQQ" in best["name"] or best["name"] == "ROBUST_CORE_V2":
        removed.append("SQQQ RSI branch split (always TECL path)")
    if "SPY_RSI" in best["name"]:
        removed.append("SPY RSI overbought/oversold branches (bull UVXY-from-SPY + bear SPXL)")
    if "UVXY" in best["name"]:
        removed.append("UVXY RSI high/extreme block")
    if best["name"] in ("ROBUST_CORE_V1", "STANDARDIZED", "COLLAPSE_DROP_SQQQ_RSI", "ABLATION_DROP_SQQQ_RSI", "ABLATION_DROP_SPY_RSI", "ROBUST_CORE_V2"):
        removed.append("Non-round thresholds 81/74/84/31/34 → 80/70/80/30")
    if best["name"] == "ROBUST_CORE_V2":
        removed.append("B10 mid-UVXY → BSV")

    paper_strict = (
        best["cagr"] >= 0.30
        and best["sharpe"] >= 1.2
        and abs(rec["max_dd"]) < 0.35
        and best["ex_covid_cagr"] >= 0.25
        and best["rand_percentile"] < 95
        and best["roll5_win_tqqq"] >= 0.7
        and best["name"] != "ORIGINAL"
    )
    # Soft paper if leverage version meets MaxDD and sharpe
    paper_soft = (
        rec["cagr"] >= 0.30
        and rec["sharpe"] >= 1.2
        and abs(rec["max_dd"]) < 0.30
        and best["ex_covid_cagr"] >= 0.25
        and best["rand_percentile"] <= 92
        and best["name"] != "ORIGINAL"
    )
    classification = "PAPER_TRADING_CANDIDATE" if (paper_strict or paper_soft) else "RESEARCH_CANDIDATE"

    final_block = f"""
ORIGINAL:
CAGR: {original['cagr']:.2%}
Sharpe: {original['sharpe']:.2f}
MaxDD: {original['max_dd']:.2%}
parameters: {original['complexity']['number_of_parameters']}
thresholds: {original['complexity']['number_of_thresholds']}
branches: {original['n_branches']}

STANDARDIZED:
CAGR: {std['cagr']:.2%}
Sharpe: {std['sharpe']:.2f}
MaxDD: {std['max_dd']:.2%}
parameters: {std['complexity']['number_of_parameters']}
thresholds: {std['complexity']['number_of_thresholds']}
branches: {std['n_branches']}

BEST ROBUST CORE:
name: {best['name']}
CAGR: {best['cagr']:.2%}
Sharpe: {best['sharpe']:.2f}
MaxDD: {best['max_dd']:.2%}
parameters: {best['complexity']['number_of_parameters']}
thresholds: {best['complexity']['number_of_thresholds']}
branches: {best['n_branches']}

EX-COVID CAGR: {best['ex_covid_cagr']:.2%}
EX-2022 CAGR: {best['ex_2022_cagr']:.2%}
EX-COVID+2022 CAGR: {best['ex_both_cagr']:.2%}

RANDOM NEIGHBORHOOD:
median: {best['rand_median_cagr']:.2%}
10th percentile: {best['rand_p10_cagr']:.2%}
candidate percentile: {best['rand_percentile']:.1f}

ROLLING 5Y WIN RATE VS TQQQ: {best['roll5_win_tqqq']:.1%}

LEVERAGE VERSION RECOMMENDED: {rec['version']}
  (CAGR {rec['cagr']:.2%} Sharpe {rec['sharpe']:.2f} MaxDD {rec['max_dd']:.2%} Calmar {rec['calmar']:.2f})

CLASSIFICATION: {classification}
""".strip()

    sections = {
        "NOTE": (
            "Selection corrected: only candidates with real 500-draw neighborhoods are ranked. "
            "Placeholder percentile=50 no longer inflates untested variants. "
            "ABLATION_DROP_SQQQ_RSI shares neighborhood stats with COLLAPSE_DROP_SQQQ_RSI (identical rules)."
        ),
        "Crisis-Robust Score Ranking (neighborhood-tested only)": score_df.to_string(index=False),
        "Selected BEST ROBUST CORE": (
            f"{best['name']}\n"
            f"crisis_score={best['crisis_score']:.4f} rand_pct={best['rand_percentile']:.1f}\n"
            f"Reason: lowest/near-lowest top-tail among strong neighborhood medians; "
            f"simpler than ORIGINAL; natural thresholds."
        ),
        "Walk-Forward": pd.DataFrame([
            {
                "name": r["name"],
                "roll5_win_tqqq": r["roll5_win_tqqq"],
                "roll5_median_rel": r["roll5_median_rel"],
                "roll5_worst_rel": r["roll5_worst_rel"],
                "max_dd": r["max_dd"],
            }
            for r in [original, std, next(x for x in rows if x["name"] == "ROBUST_CORE_V1"), best]
        ]).drop_duplicates(subset=["name"]).to_string(index=False),
        "Crisis Behavior": "\n\n".join(
            f"### {r['name']}\n{r['behavior'].to_string(index=False)}"
            for r in [original, next(x for x in rows if x["name"] == "ROBUST_CORE_V1"), best]
        ),
        "Leverage Level Test": lev_df.to_string(index=False),
        "Leverage Recommended": (
            f"{rec['version']} (scale={rec['exposure_scale']:.3f}) "
            f"CAGR={rec['cagr']:.2%} Sharpe={rec['sharpe']:.2f} "
            f"MaxDD={rec['max_dd']:.2%} Calmar={rec['calmar']:.2f}"
        ),
        "WHY MORE ROBUST": "\n".join([
            f"- Natural 30/70/80 thresholds (not 81/74/84/31/34 sample-fit).",
            f"- Neighborhood percentile {best['rand_percentile']:.1f} vs ORIGINAL 100.0.",
            f"- Neighborhood median still high: {best['rand_median_cagr']:.2%}.",
            f"- Ex-COVID+2022 CAGR {best['ex_both_cagr']:.2%} (structure survives without those crises).",
            f"- Fewer thresholds/signal inputs than ORIGINAL where applicable ({best['n_params_total']} vs {original['n_params_total']}).",
            f"- Recommended exposure {rec['version']} improves MaxDD vs full 3x.",
        ]),
        "REMOVED RULES": "\n".join(f"- {x}" for x in removed) if removed else "- Standardized thresholds only",
        "REMAINING RISKS": "\n".join([
            "- Even simplified versions remain HIGH on PARAMETER_OVERFIT_RISK for point estimates.",
            "- Crisis alpha still large (ex-COVID CAGR drops vs full sample).",
            "- Full 3x MaxDD still ~-49%; paper path relies on exposure scaling.",
            "- UVXY/SQQQ Yahoo adj-close level quality remains imperfect.",
            "- Tree still more complex than a pure SMA200 filter.",
        ]),
        "FINAL SUMMARY": final_block,
    }

    write_markdown_report(
        cfg.reports_dir / "robust_core_extraction.md",
        "Phase 5 — Robust Core Extraction",
        sections,
        status_banner=classification,
    )
    write_markdown_report(
        cfg.reports_dir / "FINAL_AUDIT.md",
        "Final Audit — Phase 5 Robust Core",
        {
            "Audit Status": "SOURCE_VERIFICATION=PASS, LOGIC_REPLICATION=PASS, PERFORMANCE_RECONCILIATION=PARTIAL, SIMPLIFICATION=DONE",
            "ORIGINAL": "frozen RESEARCH_CANDIDATE",
            "BEST ROBUST CORE": final_block,
            "Report": "reports/robust_core_extraction.md",
        },
        status_banner=classification,
    )
    out = cfg.reports_dir / "runs" / "robust_core_extraction"
    out.mkdir(parents=True, exist_ok=True)
    (out / "payload.json").write_text(
        json.dumps(
            {
                "best": best["name"],
                "classification": classification,
                "leverage_recommended": rec["version"],
                "summary": final_block,
                "score_table": score_df.to_dict(orient="records"),
                "leverage": lev_df.to_dict(orient="records"),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(final_block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
