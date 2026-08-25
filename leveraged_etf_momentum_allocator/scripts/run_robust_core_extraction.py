#!/usr/bin/env python3
"""Phase 5: Strategy simplification / robust core extraction.

Does NOT raise ORIGINAL CAGR. Extracts simpler, more natural, less crisis-dependent
variants while preserving structural edge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest import run_conditional_rotation
from baselines import STANDARDIZED_THRESHOLDS
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from metrics import cagr, calmar, compute_metrics, max_drawdown, sharpe
from original_strategy import load_thresholds, select_target
from overfitting_audit import (
    CRISIS_PERIODS,
    leave_one_crisis_out,
    random_neighborhood_distribution,
    rolling_stability,
    rolling_summary,
    terminal_branch_attribution,
)
from phase5_audit import (
    active_branch_count,
    crisis_behavior_profile,
    crisis_robust_score,
    loo_named,
    prune_candidates_from_attribution,
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

N_RANDOM = 500
RANDOM_SEED = 42


def _m(res: dict) -> dict:
    return compute_metrics(res["equity"], res["trades"], label=res.get("label", ""))


def _sample_thresh(rng: np.random.Generator, base: dict) -> dict:
    """Neighborhood around a candidate's thresholds — no CAGR hunting."""
    uvxy_hi = int(rng.integers(max(60, base.get("uvxy_high", 70) - 5), min(85, base.get("uvxy_high", 70) + 6)))
    uvxy_ext = int(rng.integers(max(uvxy_hi + 1, 75), min(90, uvxy_hi + 12)))
    return {
        "qqq_rsi_overbought": int(rng.integers(75, 86)),
        "spy_rsi_overbought": int(rng.integers(75, 86)),
        "tqqq_rsi_oversold": int(rng.integers(25, 36)),
        "spy_rsi_oversold": int(rng.integers(25, 36)),
        "uvxy_high": uvxy_hi,
        "uvxy_extreme": uvxy_ext,
        "sqqq_rsi_branch_1": int(rng.integers(25, 36)),
        "sqqq_rsi_branch_2": int(rng.integers(28, 38)),
    }


def _sample_params(rng: np.random.Generator) -> dict:
    return {
        "rsi_period": int(rng.integers(8, 13)),
        "spy_sma_period": int(rng.integers(180, 221)),
        "qqq_sma_period": int(rng.integers(15, 26)),
        "tqqq_sma_period": int(rng.integers(15, 26)),
    }


def run_neighborhood(
    opens,
    closes,
    cfg,
    *,
    base_thresh: dict,
    selector,
    label: str,
    orig_cagr: float,
    n: int = N_RANDOM,
    ind_cache: Optional[dict] = None,
) -> dict:
    rng = np.random.default_rng(RANDOM_SEED)
    cache = ind_cache if ind_cache is not None else {}
    cagr_s, sh_s, dd_s, ca_s = [], [], [], []
    print(f"  neighborhood {label}: {n} draws...", flush=True)
    for i in range(n):
        p = _sample_params(rng)
        t = _sample_thresh(rng, base_thresh)
        try:
            res = run_conditional_rotation(
                opens,
                closes,
                cfg,
                parameters_override=p,
                thresholds=t,
                target_selector=selector,
                indicator_cache=cache,
                label=f"{label}_R{i}",
            )
            m = _m(res)
            cagr_s.append(m["cagr_net"])
            sh_s.append(m["sharpe_rf0"])
            dd_s.append(m["max_drawdown"])
            ca_s.append(m["calmar"])
        except (ValueError, KeyError):
            continue
        if (i + 1) % 100 == 0:
            print(f"    {i + 1}/{n}", flush=True)
    return random_neighborhood_distribution(cagr_s, sh_s, dd_s, ca_s, orig_cagr)


def evaluate_candidate(
    opens,
    closes,
    cfg,
    *,
    name: str,
    thresholds: dict,
    selector,
    params: Optional[dict] = None,
    ind_cache: Optional[dict] = None,
    complexity: Optional[dict] = None,
) -> dict:
    res = run_conditional_rotation(
        opens,
        closes,
        cfg,
        parameters_override=params,
        thresholds=thresholds,
        target_selector=selector,
        indicator_cache=ind_cache,
        label=name,
    )
    m = _m(res)
    loo = loo_named(res["equity"], closes)
    roll3 = rolling_summary(rolling_stability(res["equity"], closes, window_years=3))
    roll5 = rolling_summary(rolling_stability(res["equity"], closes, window_years=5))
    n_br = active_branch_count(res["signal_log"])
    cx = complexity or ORIGINAL_COMPLEXITY
    cx_stats = complexity_stats(
        n_params=cx["number_of_parameters"],
        n_thresholds=cx["number_of_thresholds"],
        n_signal_assets=cx["number_of_signal_assets"],
        n_terminal_branches=n_br or cx["number_of_terminal_branches"],
        cagr=m["cagr_net"],
    )
    branch_df = terminal_branch_attribution(
        res["equity"], res["signal_log"], res["trades"], closes
    )
    behavior = crisis_behavior_profile(res["signal_log"])
    row = {
        "name": name,
        "cagr": m["cagr_net"],
        "sharpe": m["sharpe_rf0"],
        "max_dd": m["max_drawdown"],
        "calmar": m["calmar"],
        "annual_turnover": m["annual_turnover"],
        "n_trades": m["number_of_trades"],
        "ex_covid_cagr": loo.get("COVID", float("nan")),
        "ex_2022_cagr": loo.get("2022", float("nan")),
        "ex_both_cagr": loo.get("Exclude COVID+2022", float("nan")),
        "full_cagr_loo": loo.get("Full sample", m["cagr_net"]),
        "roll3_win_tqqq": roll3.get("pct_windows_beat_tqqq", float("nan")),
        "roll5_win_tqqq": roll5.get("pct_windows_beat_tqqq", float("nan")),
        "roll3_win_spy": roll3.get("pct_windows_beat_spy", float("nan")),
        "roll5_win_spy": roll5.get("pct_windows_beat_spy", float("nan")),
        "roll5_median_rel": roll5.get("median_rel_cagr_vs_tqqq", float("nan")),
        "roll5_worst_rel": roll5.get("worst_window_rel_vs_tqqq", float("nan")),
        "n_params_total": cx_stats["number_of_parameters"] + cx_stats["number_of_thresholds"],
        "n_branches": cx_stats["number_of_terminal_branches"],
        "perf_per_param": cx_stats["performance_per_parameter"],
        "perf_per_branch": cx_stats["performance_per_branch"],
        "complexity": cx_stats,
        "roll3": roll3,
        "roll5": roll5,
        "loo": loo,
        "branch_df": branch_df,
        "behavior": behavior,
        "result": res,
        "metrics": m,
        "thresholds": thresholds,
        "selector": selector,
        "params": params,
        "rand_median_cagr": float("nan"),
        "rand_p10_cagr": float("nan"),
        "rand_percentile": float("nan"),
    }
    row["crisis_score_pre"] = float("nan")
    return row


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    assert cfg.is_frozen() and cfg.is_original_verified(), "ORIGINAL must stay frozen+verified"
    universe = cfg.universe()
    fetch_prices(cfg, symbols=universe + ["XLK"], start="2010-01-01", refresh=False)
    opens, closes, _ = load_panels(cfg, universe + ["XLK"])
    ind_cache: dict = {}

    orig_thresh = load_thresholds(cfg)
    sections: dict[str, str] = {}
    candidates: list[dict] = []

    # ----- 1. ORIGINAL (frozen) -----
    print("Evaluating ORIGINAL...", flush=True)
    original = evaluate_candidate(
        opens, closes, cfg,
        name="ORIGINAL",
        thresholds=orig_thresh,
        selector=original_selector,
        ind_cache=ind_cache,
        complexity=ORIGINAL_COMPLEXITY,
    )
    candidates.append(original)

    # ----- 2. STANDARDIZED / ROBUST_CORE_V1 -----
    print("Evaluating STANDARDIZED / ROBUST_CORE_V1...", flush=True)
    std = evaluate_candidate(
        opens, closes, cfg,
        name="STANDARDIZED",
        thresholds=STANDARDIZED_THRESHOLDS,
        selector=make_selector(),
        params=ROBUST_CORE_V1_PARAMS,
        ind_cache=ind_cache,
        complexity=ORIGINAL_COMPLEXITY,
    )
    candidates.append(std)

    rc1 = evaluate_candidate(
        opens, closes, cfg,
        name="ROBUST_CORE_V1",
        thresholds=ROBUST_CORE_V1_THRESHOLDS,
        selector=make_selector(),
        params=ROBUST_CORE_V1_PARAMS,
        ind_cache=ind_cache,
        complexity=ORIGINAL_COMPLEXITY,
    )
    candidates.append(rc1)

    # ----- 3. Collapse duplicate conditions (one at a time) -----
    print("Collapse experiments...", flush=True)
    collapse_sqqq30 = evaluate_candidate(
        opens, closes, cfg,
        name="COLLAPSE_SQQQ_30",
        thresholds=ROBUST_CORE_V1_THRESHOLDS,
        selector=make_selector(unify_sqqq_30=True),
        params=ROBUST_CORE_V1_PARAMS,
        ind_cache=ind_cache,
        complexity={**ORIGINAL_COMPLEXITY, "number_of_thresholds": 7},
    )
    candidates.append(collapse_sqqq30)

    drop_sqqq = evaluate_candidate(
        opens, closes, cfg,
        name="COLLAPSE_DROP_SQQQ_RSI",
        thresholds=ROBUST_CORE_V1_THRESHOLDS,
        selector=make_selector(drop_sqqq_rsi=True),
        params=ROBUST_CORE_V1_PARAMS,
        ind_cache=ind_cache,
        complexity={
            "number_of_parameters": 4,
            "number_of_thresholds": 6,
            "number_of_signal_assets": 6,
            "number_of_terminal_branches": 12,
        },
    )
    candidates.append(drop_sqqq)

    # ----- 4. Feature ablation (one at a time) -----
    print("Feature ablation...", flush=True)
    ablations = [
        ("ABLATION_DROP_SQQQ_RSI", dict(drop_sqqq_rsi=True), 6, 6),
        ("ABLATION_DROP_UVXY_RSI", dict(drop_uvxy_rsi=True), 6, 5),
        ("ABLATION_DROP_QQQ_SMA20", dict(drop_qqq_sma=True), 7, 6),
        ("ABLATION_DROP_TQQQ_SMA20", dict(drop_tqqq_sma=True), 7, 6),
        ("ABLATION_DROP_QQQ_RSI", dict(drop_qqq_rsi=True), 7, 6),
        ("ABLATION_DROP_SPY_RSI", dict(drop_spy_rsi=True), 6, 6),
    ]
    for name, flags, n_thr, n_sig in ablations:
        print(f"  {name}", flush=True)
        cx = {
            "number_of_parameters": 4 if "SMA" not in name else 3,
            "number_of_thresholds": n_thr,
            "number_of_signal_assets": n_sig,
            "number_of_terminal_branches": 12,
        }
        if "QQQ_SMA" in name or "TQQQ_SMA" in name:
            cx["number_of_parameters"] = 3
        candidates.append(
            evaluate_candidate(
                opens, closes, cfg,
                name=name,
                thresholds=ROBUST_CORE_V1_THRESHOLDS,
                selector=make_selector(**flags),
                params=ROBUST_CORE_V1_PARAMS,
                ind_cache=ind_cache,
                complexity=cx,
            )
        )

    # ----- 5. Tree pruning (one branch at a time) -----
    print("Prune candidates...", flush=True)
    prune_list = prune_candidates_from_attribution(original["branch_df"])
    sections["PRUNE_CANDIDATES"] = (
        pd.DataFrame(prune_list).to_string(index=False) if prune_list else "none"
    )
    # Prefer rare branches: B10, B5, B11 (from prior attribution)
    preferred = []
    for bid in ["B10", "B5", "B11", "B2", "B1"]:
        if any(p["branch_id"] == bid for p in prune_list) or bid in {"B10", "B5", "B11"}:
            preferred.append(bid)
    preferred = preferred[:3]
    for i, bid in enumerate(preferred, 1):
        name = f"PRUNED_{i}"
        print(f"  {name} drop {bid}", flush=True)
        candidates.append(
            evaluate_candidate(
                opens, closes, cfg,
                name=name,
                thresholds=ROBUST_CORE_V1_THRESHOLDS,
                selector=make_selector(prune_branches=[bid]),
                params=ROBUST_CORE_V1_PARAMS,
                ind_cache=ind_cache,
                complexity={**ORIGINAL_COMPLEXITY, "number_of_terminal_branches": 13},
            )
        )
        candidates[-1]["pruned_branch"] = bid

    # Combined mild simplify: std thresholds + drop SQQQ + prune B10
    print("ROBUST_CORE_V2 (std + drop SQQQ RSI + prune B10)...", flush=True)
    rc2 = evaluate_candidate(
        opens, closes, cfg,
        name="ROBUST_CORE_V2",
        thresholds=ROBUST_CORE_V1_THRESHOLDS,
        selector=make_selector(drop_sqqq_rsi=True, prune_branches=["B10"]),
        params=ROBUST_CORE_V1_PARAMS,
        ind_cache=ind_cache,
        complexity={
            "number_of_parameters": 4,
            "number_of_thresholds": 6,
            "number_of_signal_assets": 6,
            "number_of_terminal_branches": 11,
        },
    )
    candidates.append(rc2)

    # ----- Comparison table (pre-neighborhood) -----
    summary_rows = []
    for c in candidates:
        summary_rows.append(
            {
                "name": c["name"],
                "cagr": c["cagr"],
                "sharpe": c["sharpe"],
                "max_dd": c["max_dd"],
                "ex_covid": c["ex_covid_cagr"],
                "ex_2022": c["ex_2022_cagr"],
                "ex_both": c["ex_both_cagr"],
                "roll5_win": c["roll5_win_tqqq"],
                "turnover": c["annual_turnover"],
                "branches": c["n_branches"],
                "params": c["n_params_total"],
            }
        )
    summary_df = pd.DataFrame(summary_rows)
    sections["Candidate Comparison (pre-neighborhood)"] = summary_df.to_string(index=False)

    # ----- 8. Neighborhood on key candidates -----
    # Neighborhood is expensive (~1.5s/draw); cover structural variants only.
    key_names = [
        "ORIGINAL",
        "ROBUST_CORE_V1",
        "ROBUST_CORE_V2",
        "COLLAPSE_DROP_SQQQ_RSI",
        "ABLATION_DROP_UVXY_RSI",
        "PRUNED_1",
    ]
    key = {c["name"]: c for c in candidates if c["name"] in key_names}
    for name, c in key.items():
        dist = run_neighborhood(
            opens, closes, cfg,
            base_thresh=c["thresholds"],
            selector=c["selector"],
            label=name,
            orig_cagr=c["cagr"],
            n=N_RANDOM,
            ind_cache=ind_cache,
        )
        c["rand"] = dist
        c["rand_median_cagr"] = dist["cagr_median"]
        c["rand_p10_cagr"] = dist["cagr_p10"]
        c["rand_percentile"] = dist["original_cagr_percentile"]
        c["crisis_score"] = crisis_robust_score(c)

    # Score all — only overwrite if neighborhood was run
    for c in candidates:
        if "rand" not in c:
            # Do not fake neighborhood stats; leave NaN so ranking excludes them
            c["rand_median_cagr"] = float("nan")
            c["rand_p10_cagr"] = float("nan")
            c["rand_percentile"] = float("nan")
            c["crisis_score"] = float("nan")
        elif "crisis_score" not in c:
            c["crisis_score"] = crisis_robust_score(c)

    scored = sorted(
        [c for c in candidates if c.get("rand") and c["name"] != "ORIGINAL"],
        key=lambda x: (-x.get("crisis_score", -999), x.get("rand_percentile", 100), x["n_params_total"]),
    )
    score_df = pd.DataFrame(
        [
            {
                "name": c["name"],
                "crisis_score": round(c.get("crisis_score", float("nan")), 4),
                "cagr": c["cagr"],
                "ex_both": c["ex_both_cagr"],
                "rand_med": c.get("rand_median_cagr"),
                "rand_p10": c.get("rand_p10_cagr"),
                "rand_pct": c.get("rand_percentile"),
                "roll5": c["roll5_win_tqqq"],
                "sharpe": c["sharpe"],
                "max_dd": c["max_dd"],
                "branches": c["n_branches"],
            }
            for c in scored
        ]
    )
    sections["Crisis-Robust Score Ranking"] = score_df.to_string(index=False)

    # Prefer lower top-tail percentile when neighborhood median stays strong
    best = scored[0] if scored else rc1
    for c in scored:
        if c.get("rand_percentile", 100) < 95 and c.get("rand_median_cagr", 0) > 0.80:
            best = c
            break
    # Prefer named ROBUST_CORE_V1 if close and selected is not SPY-ablation
    for prefer in ("ABLATION_DROP_SPY_RSI", "ROBUST_CORE_V1", "COLLAPSE_DROP_SQQQ_RSI", "STANDARDIZED"):
        match = next((c for c in scored if c["name"] == prefer), None)
        if not match:
            continue
        if prefer == "ABLATION_DROP_SPY_RSI" and match.get("rand_percentile", 100) < 95:
            best = match
            break
        if prefer == "ROBUST_CORE_V1" and best.get("rand_percentile", 0) >= 95:
            best = match
            break

    sections["Selected BEST ROBUST CORE"] = (
        f"{best['name']}\n"
        f"CAGR={best['cagr']:.2%} Sharpe={best['sharpe']:.2f} MaxDD={best['max_dd']:.2%}\n"
        f"ex-COVID={best['ex_covid_cagr']:.2%} ex-both={best['ex_both_cagr']:.2%}\n"
        f"rand median={best.get('rand_median_cagr', float('nan')):.2%} "
        f"p10={best.get('rand_p10_cagr', float('nan')):.2%} "
        f"percentile={best.get('rand_percentile', float('nan')):.1f}\n"
        f"crisis_score={best.get('crisis_score', float('nan')):.4f}"
    )

    # ----- 9. Walk-forward -----
    wf_rows = []
    for name in ["ORIGINAL", "STANDARDIZED", "ROBUST_CORE_V1", best["name"]]:
        c = next(x for x in candidates if x["name"] == name)
        r5 = c["roll5"]
        r3 = c["roll3"]
        # worst MaxDD across rolling windows approx via equity leave-one — use full max_dd
        wf_rows.append(
            {
                "name": name,
                "roll3_win_tqqq": r3.get("pct_windows_beat_tqqq"),
                "roll5_win_tqqq": r5.get("pct_windows_beat_tqqq"),
                "roll3_win_spy": r3.get("pct_windows_beat_spy"),
                "roll5_win_spy": r5.get("pct_windows_beat_spy"),
                "roll5_median_rel": r5.get("median_rel_cagr_vs_tqqq"),
                "roll5_worst_rel": r5.get("worst_window_rel_vs_tqqq"),
                "max_dd": c["max_dd"],
            }
        )
    sections["Walk-Forward Comparison"] = pd.DataFrame(wf_rows).to_string(index=False)

    # ----- 10. Crisis generalization -----
    beh_blocks = []
    for name in ["ORIGINAL", "ROBUST_CORE_V1", best["name"]]:
        c = next(x for x in candidates if x["name"] == name)
        beh_blocks.append(f"### {name}\n{c['behavior'].to_string(index=False)}")
    sections["Crisis Behavior (directional)"] = "\n\n".join(beh_blocks)

    # ----- 11. Leverage versions on best -----
    print("Leverage scaling on best robust core...", flush=True)
    base_eq = best["result"]["equity"]
    lev_rows = []
    for label, scale in [
        ("ROBUST_CORE_1X", 1.0 / 3.0),
        ("ROBUST_CORE_1_5X", 1.5 / 3.0),
        ("ROBUST_CORE_2X", 2.0 / 3.0),
        ("ROBUST_CORE_3X_ORIGINAL", 1.0),
    ]:
        eq = scale_equity_exposure(base_eq, scale)
        rets = eq["net_return"]
        lev_rows.append(
            {
                "version": label,
                "exposure_scale": scale,
                "cagr": cagr(rets),
                "sharpe": sharpe(rets),
                "max_dd": max_drawdown(rets),
                "calmar": calmar(rets),
            }
        )
    lev_df = pd.DataFrame(lev_rows)
    # Recommend best Calmar among versions with MaxDD > -40% if possible, else best Sharpe
    eligible = lev_df[lev_df["max_dd"] > -0.40]
    if eligible.empty:
        eligible = lev_df
    rec = eligible.sort_values(["calmar", "sharpe"], ascending=False).iloc[0]
    sections["Leverage Level Test"] = lev_df.to_string(index=False)
    sections["Leverage Recommended"] = (
        f"{rec['version']} (scale={rec['exposure_scale']:.3f}) "
        f"CAGR={rec['cagr']:.2%} Sharpe={rec['sharpe']:.2f} "
        f"MaxDD={rec['max_dd']:.2%} Calmar={rec['calmar']:.2f}"
    )

    # ----- Ablation / collapse detail tables -----
    abl = summary_df[summary_df["name"].str.startswith("ABLATION") | summary_df["name"].str.startswith("COLLAPSE")]
    sections["Feature Ablation & Collapse"] = abl.to_string(index=False)
    prn = summary_df[summary_df["name"].str.startswith("PRUNED")]
    sections["Pruned Variants"] = prn.to_string(index=False) if not prn.empty else "none"

    # Neighborhood table
    nb_rows = []
    for name, c in key.items():
        d = c.get("rand", {})
        nb_rows.append(
            {
                "name": name,
                "cagr": c["cagr"],
                "median": d.get("cagr_median"),
                "p10": d.get("cagr_p10"),
                "percentile": d.get("original_cagr_percentile"),
                "overfit_risk": d.get("PARAMETER_OVERFIT_RISK"),
            }
        )
    sections["Random Neighborhood (500)"] = pd.DataFrame(nb_rows).to_string(index=False)

    # Classification
    paper_ok = (
        best["cagr"] >= 0.30
        and best["sharpe"] >= 1.2
        and abs(best["max_dd"]) < 0.45  # soft; prefer <30 but allow research
        and best["ex_covid_cagr"] >= 0.25
        and best.get("rand_percentile", 100) < 92
        and best["n_branches"] <= 13
        and best["name"] != "ORIGINAL"
    )
    # Stricter paper if maxdd < 30 and sharpe >= 1.2
    paper_strict = (
        paper_ok
        and abs(best["max_dd"]) < 0.35
        and best["sharpe"] >= 1.2
        and best["roll5_win_tqqq"] >= 0.7
    )
    classification = "PAPER_TRADING_CANDIDATE" if paper_strict else "RESEARCH_CANDIDATE"

    removed = []
    if "DROP_SQQQ" in best["name"] or best["name"] == "ROBUST_CORE_V2":
        removed.append("SQQQ RSI branch split")
    if best["name"] == "ROBUST_CORE_V2":
        removed.append("B10 mid-UVXY branch -> BSV")
    if best["name"].startswith("PRUNED"):
        removed.append(f"pruned {best.get('pruned_branch', '?')} -> BSV")
    if best["name"] in ("ROBUST_CORE_V1", "STANDARDIZED", "ROBUST_CORE_V2"):
        removed.append("non-round thresholds (81/74/84/31/34 -> 80/70/80/30)")

    sections["WHY MORE ROBUST"] = "\n".join(
        [
            f"- Uses natural 30/70/80 thresholds (not sample-fit 81/74/84/31/34).",
            f"- Candidate percentile in neighborhood: {best.get('rand_percentile', float('nan')):.1f} (ORIGINAL was 100).",
            f"- Ex-COVID+2022 CAGR: {best['ex_both_cagr']:.2%} vs ORIGINAL {original['ex_both_cagr']:.2%}.",
            f"- Branches/params: {best['n_branches']}/{best['n_params_total']} vs ORIGINAL {original['n_branches']}/{original['n_params_total']}.",
            f"- Crisis-robust composite score preferred over max CAGR.",
        ]
    )
    sections["REMOVED RULES"] = "\n".join(f"- {x}" for x in removed) if removed else "- Round-number threshold standardization only"
    sections["REMAINING RISKS"] = "\n".join(
        [
            "- Still uses leveraged ETFs at full scale unless leverage version applied.",
            "- Crisis alpha remains material (ex-COVID still drops vs full sample).",
            "- Yahoo adjusted close for UVXY/SQQQ remains imperfect for levels.",
            "- Tree structure still relatively complex vs simple SMA200 filter.",
            "- Not jointly re-optimized; residual branch quirks may remain.",
        ]
    )

    # Final banner block
    o, s, b = original, std, best
    final_block = f"""
ORIGINAL:
CAGR: {o['cagr']:.2%}
Sharpe: {o['sharpe']:.2f}
MaxDD: {o['max_dd']:.2%}
parameters: {o['complexity']['number_of_parameters']}
thresholds: {o['complexity']['number_of_thresholds']}
branches: {o['n_branches']}

STANDARDIZED:
CAGR: {s['cagr']:.2%}
Sharpe: {s['sharpe']:.2f}
MaxDD: {s['max_dd']:.2%}
parameters: {s['complexity']['number_of_parameters']}
thresholds: {s['complexity']['number_of_thresholds']}
branches: {s['n_branches']}

BEST ROBUST CORE:
name: {b['name']}
CAGR: {b['cagr']:.2%}
Sharpe: {b['sharpe']:.2f}
MaxDD: {b['max_dd']:.2%}
parameters: {b['complexity']['number_of_parameters']}
thresholds: {b['complexity']['number_of_thresholds']}
branches: {b['n_branches']}

EX-COVID CAGR: {b['ex_covid_cagr']:.2%}
EX-2022 CAGR: {b['ex_2022_cagr']:.2%}
EX-COVID+2022 CAGR: {b['ex_both_cagr']:.2%}

RANDOM NEIGHBORHOOD:
median: {b.get('rand_median_cagr', float('nan')):.2%}
10th percentile: {b.get('rand_p10_cagr', float('nan')):.2%}
candidate percentile: {b.get('rand_percentile', float('nan')):.1f}

ROLLING 5Y WIN RATE VS TQQQ: {b['roll5_win_tqqq']:.1%}

LEVERAGE VERSION RECOMMENDED: {rec['version']}

CLASSIFICATION: {classification}
""".strip()
    sections["FINAL SUMMARY"] = final_block

    write_markdown_report(
        cfg.reports_dir / "robust_core_extraction.md",
        "Phase 5 — Robust Core Extraction",
        sections,
        status_banner=classification,
    )

    # Update FINAL_AUDIT lightly
    write_markdown_report(
        cfg.reports_dir / "FINAL_AUDIT.md",
        "Final Audit — includes Phase 5 Robust Core",
        {
            "Audit Status": "SOURCE_VERIFICATION=PASS, LOGIC_REPLICATION=PASS, PERFORMANCE_RECONCILIATION=PARTIAL, SIMPLIFICATION=DONE",
            "ORIGINAL Classification": "RESEARCH_CANDIDATE (frozen)",
            "BEST ROBUST CORE": final_block,
            "OVERFITTING_RISK (ORIGINAL)": "HIGH",
            "Phase 5 Report": "reports/robust_core_extraction.md",
        },
        status_banner=classification,
    )

    out = cfg.reports_dir / "runs" / "robust_core_extraction"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "best": best["name"],
        "classification": classification,
        "leverage_recommended": rec["version"],
        "summary": final_block,
        "score_table": score_df.to_dict(orient="records"),
        "leverage": lev_df.to_dict(orient="records"),
    }
    (out / "payload.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Persist robust_core_v1 yaml confirmation
    rc_path = ROOT / "configs" / "robust_core_v1.yaml"
    assert rc_path.exists()

    print("\n" + "=" * 60)
    print(final_block)
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
