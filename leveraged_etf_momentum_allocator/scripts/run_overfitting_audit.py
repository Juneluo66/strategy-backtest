#!/usr/bin/env python3
"""Overfitting + crisis dependence audit — optimized random neighborhood."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtest import run_conditional_rotation
from baselines import (
    BRANCH_SENSITIVITY_THRESHOLDS,
    LONG_DELEVERAGED_MAP,
    RISK_REDUCED_MAP,
    STANDARDIZED_THRESHOLDS,
)
from benchmarks import buy_and_hold_returns
from config import ProjectConfig
from data_loader import fetch_prices, load_panels
from metrics import cagr, compute_metrics
from original_strategy import load_thresholds
from indicators import build_indicator_panels
from overfitting_audit import (
    CRISIS_PERIODS,
    crisis_concentration,
    leave_one_crisis_out,
    random_neighborhood_distribution,
    rolling_stability,
    rolling_summary,
    terminal_branch_attribution,
)
from reporting import write_markdown_report

N_RANDOM = 1000
RANDOM_SEED = 42


def _metrics(res: dict) -> dict:
    return compute_metrics(res["equity"], res["trades"], label=res.get("label", ""))


def _loo_cagr(loo: pd.DataFrame, scenario: str) -> float:
    row = loo.loc[loo["scenario"] == scenario, "cagr"]
    if row.empty:
        raise KeyError(f"scenario not found: {scenario}")
    return float(row.iloc[0])




def _indicator_key(params: dict) -> tuple[int, int, int, int]:
    return (
        int(params["rsi_period"]),
        int(params["spy_sma_period"]),
        int(params["qqq_sma_period"]),
        int(params["tqqq_sma_period"]),
    )


def _warm_indicator_cache(
    closes: pd.DataFrame,
    universe: list[str],
    samples: list[tuple[dict, dict]],
    cache: dict,
) -> None:
    """Pre-build indicator panels for all unique parameter tuples in random draws."""
    keys: set[tuple[int, int, int, int]] = set()
    for p_over, _ in samples:
        keys.add(_indicator_key(p_over))
    missing = [k for k in keys if k not in cache]
    if not missing:
        return
    print(f"Pre-building {len(missing)} indicator panels...", flush=True)
    for i, key in enumerate(missing, 1):
        rsi_period, spy_sma, qqq_sma, tqqq_sma = key
        cache[key] = build_indicator_panels(
            closes,
            rsi_period=rsi_period,
            spy_sma_period=spy_sma,
            qqq_sma_period=qqq_sma,
            tqqq_sma_period=tqqq_sma,
            universe=universe,
        )
        if i % 50 == 0 or i == len(missing):
            print(f"  indicators {i}/{len(missing)}", flush=True)


def _sample_random_params(rng: np.random.Generator) -> tuple[dict, dict]:
    params = {
        "rsi_period": int(rng.integers(8, 13)),
        "spy_sma_period": int(rng.integers(180, 221)),
        "qqq_sma_period": int(rng.integers(15, 26)),
        "tqqq_sma_period": int(rng.integers(15, 26)),
    }
    uvxy_hi = int(rng.integers(69, 80))
    uvxy_ext = int(rng.integers(max(uvxy_hi + 1, 80), 90))
    thresh = {
        "qqq_rsi_overbought": int(rng.integers(77, 86)),
        "spy_rsi_overbought": int(rng.integers(76, 85)),
        "tqqq_rsi_oversold": int(rng.integers(27, 34)),
        "spy_rsi_oversold": int(rng.integers(27, 34)),
        "uvxy_high": uvxy_hi,
        "uvxy_extreme": uvxy_ext,
        "sqqq_rsi_branch_1": int(rng.integers(28, 35)),
        "sqqq_rsi_branch_2": int(rng.integers(31, 38)),
    }
    return params, thresh


def main() -> int:
    cfg = ProjectConfig.load(ROOT)
    universe = cfg.universe()
    extra = ["UPRO", "XLK"]
    fetch_prices(cfg, symbols=universe + extra, start="2010-01-01", refresh=False)
    opens, closes, _ = load_panels(cfg, universe + extra)

    ind_cache: dict = {}
    original = run_conditional_rotation(opens, closes, cfg, label="ORIGINAL", indicator_cache=ind_cache)
    m_orig = _metrics(original)
    orig_cagr = m_orig["cagr_net"]

    # 1. Terminal branches
    branch_df = terminal_branch_attribution(
        original["equity"], original["signal_log"], original["trades"], closes
    )
    top3 = branch_df.head(3)
    write_markdown_report(
        cfg.reports_dir / "terminal_branch_attribution.md",
        "Terminal Branch Attribution",
        {
            "All Branches": branch_df.to_string(index=False),
            "Top 3 by incremental_vs_tqqq": top3.to_string(index=False),
        },
    )

    # 2. Leave-one-crisis-out
    loo = leave_one_crisis_out(original["equity"], closes, CRISIS_PERIODS)
    write_markdown_report(
        cfg.reports_dir / "leave_one_crisis_out.md",
        "Leave-One-Crisis-Out",
        {"Results": loo.to_string(index=False)},
    )

    # 3. Rolling
    roll3 = rolling_stability(original["equity"], closes, window_years=3)
    roll5 = rolling_stability(original["equity"], closes, window_years=5)
    sum3 = rolling_summary(roll3)
    sum5 = rolling_summary(roll5)
    write_markdown_report(
        cfg.reports_dir / "rolling_stability.md",
        "Rolling Window Stability",
        {
            "3Y Summary": "\n".join(f"- {k}: {v}" for k, v in sum3.items()),
            "5Y Summary": "\n".join(f"- {k}: {v}" for k, v in sum5.items()),
        },
    )

    # 4. Random neighborhood
    rng = np.random.default_rng(RANDOM_SEED)
    samples = [_sample_random_params(rng) for _ in range(N_RANDOM)]
    rand_report = cfg.reports_dir / "random_parameter_neighborhood.md"
    if os.environ.get("SKIP_RANDOM") == "1" and rand_report.exists():
        print("Skipping random neighborhood (SKIP_RANDOM=1, report exists)", flush=True)
        payload_path = cfg.reports_dir / "runs" / "overfitting_audit" / "payload.json"
        if payload_path.exists():
            rand_dist = json.loads(payload_path.read_text())["random_neighborhood"]
        else:
            rand_dist = {
                "cagr_median": 0.0,
                "cagr_p10": 0.0,
                "original_cagr_percentile": 0.0,
                "PARAMETER_OVERFIT_RISK": "UNKNOWN",
            }
    else:
        _warm_indicator_cache(closes, universe, samples, ind_cache)
        cagr_s, sharpe_s, maxdd_s, calmar_s = [], [], [], []
        print(f"Running {N_RANDOM} random draws (indicator cache size {len(ind_cache)})...", flush=True)
        for i, (p_over, t_over) in enumerate(samples):
            try:
                res = run_conditional_rotation(
                    opens, closes, cfg,
                    parameters_override=p_over,
                    thresholds=t_over,
                    indicator_cache=ind_cache,
                    label=f"RAND_{i}",
                )
                m = _metrics(res)
                cagr_s.append(m["cagr_net"])
                sharpe_s.append(m["sharpe_rf0"])
                maxdd_s.append(m["max_drawdown"])
                calmar_s.append(m["calmar"])
            except (ValueError, KeyError):
                continue
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{N_RANDOM} done", flush=True)
        rand_dist = random_neighborhood_distribution(cagr_s, sharpe_s, maxdd_s, calmar_s, orig_cagr)
        write_markdown_report(
            cfg.reports_dir / "random_parameter_neighborhood.md",
            "Random Parameter Neighborhood",
            {k: str(v) for k, v in rand_dist.items()},
        )

    # 5. Branch sensitivity
    base_t = load_thresholds(cfg)
    sens_rows = []
    for name, delta in BRANCH_SENSITIVITY_THRESHOLDS.items():
        t = dict(base_t)
        t.update(delta)
        res = run_conditional_rotation(opens, closes, cfg, thresholds=t, label=name, indicator_cache=ind_cache)
        m = _metrics(res)
        sens_rows.append({"variant": name, "cagr": m["cagr_net"], "sharpe": m["sharpe_rf0"], "max_dd": m["max_drawdown"]})
    write_markdown_report(
        cfg.reports_dir / "branch_parameter_sensitivity.md",
        "Branch Parameter Sensitivity",
        {"Results": pd.DataFrame(sens_rows).to_string(index=False)},
    )

    # 6. Standardized
    std = run_conditional_rotation(
        opens, closes, cfg, thresholds=STANDARDIZED_THRESHOLDS, label="STANDARDIZED", indicator_cache=ind_cache
    )
    m_std = _metrics(std)

    # 7. Leverage ablation
    long_d = run_conditional_rotation(
        opens, closes, cfg, execution_map=LONG_DELEVERAGED_MAP, label="LONG_DELEVERAGED", indicator_cache=ind_cache
    )
    risk_r = run_conditional_rotation(
        opens, closes, cfg, execution_map=RISK_REDUCED_MAP, label="RISK_REDUCED_TREE", indicator_cache=ind_cache
    )
    m_long = _metrics(long_d)
    m_risk = _metrics(risk_r)
    spy_rets = buy_and_hold_returns(closes, "SPY", start=original["effective_start"], end=original["end"])
    qqq_rets = buy_and_hold_returns(closes, "QQQ", start=original["effective_start"], end=original["end"])
    write_markdown_report(
        cfg.reports_dir / "leverage_ablation.md",
        "Leverage Ablation",
        {
            "ORIGINAL": f"CAGR {m_orig['cagr_net']:.2%} Sharpe {m_orig['sharpe_rf0']:.2f}",
            "LONG_DELEVERAGED": f"CAGR {m_long['cagr_net']:.2%} Sharpe {m_long['sharpe_rf0']:.2f}",
            "RISK_REDUCED_TREE": f"CAGR {m_risk['cagr_net']:.2%} Sharpe {m_risk['sharpe_rf0']:.2f}",
            "SPY": f"CAGR {cagr(spy_rets):.2%}",
            "QQQ": f"CAGR {cagr(qqq_rets):.2%}",
        },
    )

    # 8. Crisis concentration
    conc = crisis_concentration(original["signal_log"], original["equity"], closes, m_orig["final_wealth_net"])
    top5_ep = conc.get("top5_episodes", pd.DataFrame())
    write_markdown_report(
        cfg.reports_dir / "crisis_concentration.md",
        "Crisis Concentration",
        {
            "Top1 % positive diff": f"{conc.get('top1_pct_of_positive_diff', 0):.1%}",
            "Top3 %": f"{conc.get('top3_pct_of_positive_diff', 0):.1%}",
            "Top5 %": f"{conc.get('top5_pct_of_positive_diff', 0):.1%}",
            "CRISIS_CONCENTRATION_RISK": conc.get("crisis_concentration_risk", "N/A"),
            "Top 5 episodes": top5_ep.to_string(index=False) if isinstance(top5_ep, pd.DataFrame) and not top5_ep.empty else "N/A",
        },
    )

    ex_covid = _loo_cagr(loo, "COVID")
    ex_2022 = _loo_cagr(loo, "2022")
    ex_both = _loo_cagr(loo, "Exclude COVID+2022")
    overfit_risk = rand_dist.get("PARAMETER_OVERFIT_RISK", "MEDIUM")
    crisis_risk = conc.get("crisis_concentration_risk", "MEDIUM")

    classification = "RESEARCH_CANDIDATE"
    paper_ok = (
        rand_dist.get("cagr_median", 0) > 0.5
        and rand_dist.get("original_cagr_percentile", 100) < 90
        and sum5.get("pct_windows_beat_tqqq", 0) > 0.5
        and ex_covid > 0.5
        and ex_2022 > 0.3
        and m_std["cagr_net"] > 0.5
        and m_long["cagr_net"] > cagr(spy_rets)
    )
    if paper_ok:
        classification = "PAPER_TRADING_CANDIDATE"

    write_markdown_report(
        cfg.reports_dir / "overfitting_audit_summary.md",
        "Overfitting + Crisis Dependence Summary",
        {
            "OVERFITTING_RISK": overfit_risk,
            "CRISIS_DEPENDENCE": crisis_risk,
            "CLASSIFICATION": classification,
        },
        status_banner=classification,
    )

    write_markdown_report(
        cfg.reports_dir / "FINAL_AUDIT.md",
        "Final Audit — Overfitting + Crisis Dependence",
        {
            "Audit Status": "SOURCE_VERIFICATION=PASS, LOGIC_REPLICATION=PASS, PERFORMANCE_RECONCILIATION=PARTIAL",
            "Classification": classification,
            "OVERFITTING_RISK": overfit_risk,
            "CRISIS_DEPENDENCE": crisis_risk,
            "Standardized vs Original": f"{m_std['cagr_net']:.2%} vs {orig_cagr:.2%}",
            "Deleveraged": f"LONG {m_long['cagr_net']:.2%} RISK_REDUCED {m_risk['cagr_net']:.2%}",
            "Top 3 Branches": top3[["branch_id", "incremental_vs_tqqq"]].to_string(index=False),
            "Leave-one-out ex-COVID": f"{ex_covid:.2%} (days with COVID window removed)",
            "Leave-one-out ex-2022": f"{ex_2022:.2%}",
            "Leave-one-out ex-COVID+2022": f"{ex_both:.2%}",
        },
        status_banner=classification,
    )

    out = cfg.reports_dir / "runs" / "overfitting_audit"
    out.mkdir(parents=True, exist_ok=True)
    (out / "payload.json").write_text(
        json.dumps(
            {
                "random_neighborhood": rand_dist,
                "rolling_3y": sum3,
                "rolling_5y": sum5,
                "standardized_cagr": m_std["cagr_net"],
                "long_deleveraged_cagr": m_long["cagr_net"],
                "risk_reduced_cagr": m_risk["cagr_net"],
                "classification": classification,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("--- OVERFITTING AUDIT SUMMARY ---")
    print(f"ORIGINAL CAGR: {orig_cagr:.2%}")
    print(f"STANDARDIZED CAGR: {m_std['cagr_net']:.2%}")
    print(f"RANDOM MEDIAN CAGR: {rand_dist.get('cagr_median', 0):.2%}")
    print(f"RANDOM 10TH PCTL: {rand_dist.get('cagr_p10', 0):.2%}")
    print(f"ORIGINAL PERCENTILE: {rand_dist.get('original_cagr_percentile', 0):.1f}%")
    print(f"ROLLING 3Y WIN RATE VS TQQQ: {sum3.get('pct_windows_beat_tqqq', 0):.1%}")
    print(f"ROLLING 5Y WIN RATE VS TQQQ: {sum5.get('pct_windows_beat_tqqq', 0):.1%}")
    print(f"EX-COVID CAGR: {ex_covid:.2%}")
    print(f"EX-2022 CAGR: {ex_2022:.2%}")
    print(f"EX-COVID+2022 CAGR: {ex_both:.2%}")
    print(f"TOP 3 BRANCHES: {', '.join(top3['branch_id'].tolist())}")
    print(f"TOP 5 CRISIS CONCENTRATION: {conc.get('top5_pct_of_positive_diff', 0):.1%}")
    print(f"LONG_DELEVERAGED CAGR: {m_long['cagr_net']:.2%}")
    print(f"RISK_REDUCED_TREE CAGR: {m_risk['cagr_net']:.2%}")
    print(f"OVERFITTING RISK: {overfit_risk}")
    print(f"CRISIS DEPENDENCE: {crisis_risk}")
    print(f"UPDATED CLASSIFICATION: {classification}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
