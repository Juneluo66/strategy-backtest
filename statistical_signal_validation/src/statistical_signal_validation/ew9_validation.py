"""Run EW9 statistical validation and write formal report."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

from .ew9_loader import latest_ew9_run, load_ew9_series
from .registry import count_trials, load_registry
from .stats_core import full_relative_battery, multiple_testing_adjustments


ROOT = Path(__file__).resolve().parents[2]


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def run_ew9_validation(project_root: Optional[Path] = None) -> Path:
    root = project_root or ROOT
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = reports / "runs" / f"{stamp}_ew9_statval"
    run_dir.mkdir(parents=True, exist_ok=False)

    registry = load_registry(root)
    trial_info = count_trials(registry)
    n_trials = trial_info["n_trials_total"]

    series = load_ew9_series()
    meta = series.pop("_meta")  # type: ignore

    # Primary comparisons
    results = {}
    # EW9_monthly vs SPY (discovery)
    results["EW9_monthly_vs_SPY"] = full_relative_battery(
        series["EW9_monthly"], series["SPY"], n_trials=n_trials, label="EW9_monthly_vs_SPY"
    )
    # Rebalance premium: monthly vs no-rebalance
    results["EW9_monthly_vs_no_rebalance"] = full_relative_battery(
        series["EW9_monthly"],
        series["no_rebalance_basket"],
        n_trials=n_trials,
        label="EW9_monthly_vs_no_rebalance",
    )
    # vs RSP on same span
    if len(series.get("RSP", pd.Series(dtype=float))) and "EW9_monthly_on_rsp_span" in series:
        results["EW9_monthly_vs_RSP_same_span"] = full_relative_battery(
            series["EW9_monthly_on_rsp_span"],
            series["RSP"],
            n_trials=n_trials,
            label="EW9_monthly_vs_RSP_same_span",
        )
    # Secondary frequencies vs SPY (not promoted)
    for name in ("EW9_quarterly", "EW9_annual"):
        results[f"{name}_vs_SPY"] = full_relative_battery(
            series[name], series["SPY"], n_trials=n_trials, label=f"{name}_vs_SPY"
        )

    # Multiple testing on Newey-West p-values for key hypotheses
    pvals = {
        k: v["newey_west"]["p_value"]
        for k, v in results.items()
        if v.get("newey_west", {}).get("p_value") is not None
    }
    mt = multiple_testing_adjustments(pvals)

    # Load discovery audit facts for judgment context
    ew_run = Path(meta["run_dir"])
    audit = json.loads((ew_run / "audit_payload.json").read_text(encoding="utf-8"))
    gate = audit.get("gate", {})
    pseudo = audit.get("pseudo_oos", {})
    endpoints = audit.get("fixed_endpoints", {})
    french = audit.get("french", {})

    judgment = _judge(results, gate, trial_info, mt)

    payload = {
        "meta": meta,
        "n_trials": n_trials,
        "trial_summary": {
            "n_trials_total": trial_info["n_trials_total"],
            "by_project": trial_info["by_project"],
            "by_status": trial_info["by_status"],
            "ew9_classification": trial_info["ew9_classification"],
        },
        "results": _strip(results),
        "multiple_testing": _strip(mt),
        "discovery_gate": gate,
        "pseudo_oos_win_frac": gate.get("notes", {}).get("pseudo_oos_win_frac"),
        "fixed_endpoints_note": (
            "All 7 fixed endpoints share the 1998 discovery common start; "
            "they are not independent start-date validations."
        ),
        "french_role": "MECHANISM_SUPPORT_not_tradable_OOS",
        "french_summary": {
            "pre_etf_monthly_cagr": (french.get("pre_etf") or {}).get("EW9_monthly", {}).get("cagr"),
            "post_etf_monthly_cagr": (french.get("post_etf") or {}).get("EW9_monthly", {}).get("cagr"),
            "tradable": False,
        },
        "judgment": judgment,
    }

    (run_dir / "ew9_stat_validation.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    (run_dir / "trial_registry_snapshot.yaml").write_text(
        yaml.safe_dump(registry, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    report = _write_report(reports / "statistical_signal_validation_ew9.md", payload, run_dir)
    (run_dir / "statistical_signal_validation_ew9.md").write_text(
        report.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Also write a thin cross-project index
    (reports / "PROJECT_STATUS.md").write_text(
        "\n".join(
            [
                "# Statistical Signal Validation — Status",
                "",
                f"- Latest EW9 run: `{run_dir.name}`",
                f"- Trial registry n_trials: **{n_trials}** (includes failed versions)",
                f"- Judgment: **{judgment['overall']}**",
                "- Report: `reports/statistical_signal_validation_ew9.md`",
                "- No strategy/parameter/IBKR/production changes",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report


def _judge(results: dict, gate: dict, trial_info: dict, mt: dict) -> dict:
    m_spy = results["EW9_monthly_vs_SPY"]
    m_hold = results["EW9_monthly_vs_no_rebalance"]
    m_rsp = results.get("EW9_monthly_vs_RSP_same_span")

    edge_spy = m_spy["relative_nav"]["cagr_edge"]
    boot12_spy = m_spy["bootstrap"]["12m"]["prob_cagr_edge_gt_0"]
    nw_p_spy = m_spy["newey_west"]["p_value"]
    dsr_spy = m_spy["dsr_active"]["dsr"]
    mintrl = m_spy["min_trl_active"]

    edge_hold = m_hold["relative_nav"]["cagr_edge"]
    boot12_hold = m_hold["bootstrap"]["12m"]["prob_cagr_edge_gt_0"]
    nw_p_hold = m_hold["newey_west"]["p_value"]
    dsr_hold = m_hold["dsr_active"]["dsr"]

    rsp_edge = m_rsp["relative_nav"]["cagr_edge"] if m_rsp else np.nan
    boot12_rsp = m_rsp["bootstrap"]["12m"]["prob_cagr_edge_gt_0"] if m_rsp else np.nan
    nw_p_rsp = m_rsp["newey_west"]["p_value"] if m_rsp else np.nan
    dsr_rsp = m_rsp["dsr_active"]["dsr"] if m_rsp else np.nan

    # Noise exclusion thresholds (conservative)
    def noisy(p, boot_p, dsr) -> bool:
        return (not (p is not None and p < 0.05)) or (boot_p is not None and boot_p < 0.95) or (
            dsr is not None and dsr < 0.95
        )

    q1 = {
        "question": "Can EW9 ~0.43pp full-sample CAGR edge vs SPY exclude noise?",
        "cagr_edge": edge_spy,
        "newey_west_p": nw_p_spy,
        "boot12_prob_edge_gt0": boot12_spy,
        "dsr_active": dsr_spy,
        "psr_active": m_spy["psr_active"]["psr"],
        "answer": "NO" if noisy(nw_p_spy, boot12_spy, dsr_spy) else "YES",
        "note": "Discovery sample only; pseudo-OOS 0/5 must override naive full-sample edge.",
    }
    q2 = {
        "question": "Can ~0.65pp rebalance premium vs no-rebalance exclude noise?",
        "cagr_edge": edge_hold,
        "newey_west_p": nw_p_hold,
        "boot12_prob_edge_gt0": boot12_hold,
        "dsr_active": dsr_hold,
        "answer": "NO" if noisy(nw_p_hold, boot12_hold, dsr_hold) else "YES",
    }
    q3 = {
        "question": "Is there independent incremental edge vs RSP?",
        "cagr_edge_same_span": rsp_edge,
        "newey_west_p": nw_p_rsp,
        "boot12_prob_edge_gt0": boot12_rsp,
        "dsr_active": dsr_rsp,
        "answer": (
            "NO_MATERIAL_INDEPENDENT_INCREMENT"
            if (m_rsp is None or abs(rsp_edge) < 0.005 or noisy(nw_p_rsp, boot12_rsp, dsr_rsp))
            else "YES"
        ),
        "note": gate.get("rsp_similarity_note") or gate.get("notes", {}).get("rsp_exposure_warning"),
    }
    years_needed = m_spy["power_years"].get("years_needed")
    q4 = {
        "question": "How many additional years for reasonable power vs SPY?",
        "years_needed_approx": years_needed,
        "observed_years": m_spy["relative_nav"]["years"],
        "min_trl_years_active": mintrl.get("min_trl_years"),
        "min_trl_sufficient": mintrl.get("sufficient"),
        "answer": (
            f"Need ~{years_needed:.0f} years at current IR/TE for 80% power"
            if years_needed is not None and np.isfinite(years_needed)
            else "undefined/infinite at near-zero IR"
        ),
    }
    q5 = {
        "question": "Must we rely on forward evidence only?",
        "answer": "YES",
        "reasons": [
            "EW9 hypothesis is a secondary discovery after sector_momentum audit (DISCOVERY_SAMPLE).",
            "Pseudo-OOS fixed starts beat SPY in 0/5 cases.",
            "Fixed-endpoint 7/7 all share 1998 start (not independent starts).",
            "French support is MECHANISM_SUPPORT only, not tradable OOS.",
            "DSR uses full monorepo trial budget including failures.",
        ],
    }
    q6 = {
        "question": "Any return-type strategy with statistical evidence already?",
        "answer": "NO_STATISTICAL_RETURN_EDGE_CLEARED",
        "notes": [
            "dual_momentum 80/20 remains paper default for process/diversifier thesis, not because DSR clears a return edge vs SPY.",
            "multi_asset trend candidate label is audit-gate based, not this SSV battery.",
            "EW9 is DISCOVERY_ONLY and fails noise-exclusion here.",
            "half_protect is defensive shadow only, not a return primary.",
        ],
    }

    overall = "FORWARD_EVIDENCE_REQUIRED_NO_EW9_RETURN_CLAIM"
    return {
        "overall": overall,
        "n_trials": trial_info["n_trials_total"],
        "q1_cagr_vs_spy": q1,
        "q2_rebalance_premium": q2,
        "q3_vs_rsp": q3,
        "q4_sample_size": q4,
        "q5_forward_only": q5,
        "q6_any_stat_return_strategy": q6,
        "pseudo_oos": gate.get("notes", {}).get("pseudo_oos_win_frac"),
        "gate_label": gate.get("label"),
    }


def _fmt(x, pct=False):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    if pct:
        return f"{100 * float(x):.2f}%"
    return f"{float(x):.4f}"


def _write_report(path: Path, payload: dict, run_dir: Path) -> Path:
    j = payload["judgment"]
    ts = payload["trial_summary"]
    lines = [
        "# Statistical Signal Validation — EW9 Focus",
        "",
        "## Scope",
        "",
        "- Cross-project SSV; **no** strategy/parameter/IBKR/production changes.",
        f"- Discovery sample: `{payload['meta']['discovery_start']}` → `{payload['meta']['discovery_end']}` "
        f"(**{payload['meta']['sample_label']}**)",
        f"- Source audit run: `{payload['meta']['run_dir']}`",
        f"- SSV run: `{run_dir}`",
        "",
        "## Classification (mandatory)",
        "",
        f"- EW9 hypothesis source: `{ts['ew9_classification'].get('overall_hypothesis_source')}`",
        f"- EW9_monthly: `{ts['ew9_classification'].get('EW9_monthly')}`",
        f"- EW9_quarterly: `{ts['ew9_classification'].get('EW9_quarterly')}` "
        "(**not** promoted to primary despite higher discovery CAGR)",
        f"- EW9_annual: `{ts['ew9_classification'].get('EW9_annual')}`",
        f"- Pseudo-OOS: `{payload.get('pseudo_oos_win_frac')}` (enters final judgment)",
        f"- Fixed endpoints: `{payload.get('fixed_endpoints_note')}`",
        f"- French: `{payload.get('french_role')}`",
        "",
        "## Trial registry",
        "",
        f"- **n_trials (incl. failures) = {payload['n_trials']}**",
        f"- By project: `{ts['by_project']}`",
        "",
        f"## Overall judgment: `{j['overall']}`",
        "",
    ]

    def block(title, key):
        r = payload["results"][key]
        rel = r["relative_nav"]
        nw = r["newey_west"]
        b12 = r["bootstrap"]["12m"]
        b3 = r["bootstrap"]["3m"]
        b1 = r["bootstrap"]["1m"]
        lines.extend(
            [
                f"### {title}",
                "",
                f"- CAGR edge: `{_fmt(rel['cagr_edge'], True)}`; relative CAGR `{_fmt(rel['relative_cagr'], True)}`; "
                f"final rel wealth `{_fmt(rel['final_relative_wealth'])}`",
                f"- Arithmetic active mean (ann): `{_fmt(r['arithmetic_active_mean_ann'], True)}`",
                f"- Information ratio: `{_fmt(r['information_ratio'])}`; TE `{_fmt(r['tracking_error_ann'], True)}`",
                f"- Newey-West t: `{_fmt(nw['t_stat'])}` (p=`{_fmt(nw['p_value'])}`, lags={nw['lags']})",
                f"- Bootstrap P(CAGR edge>0): 1m `{_fmt(b1['prob_cagr_edge_gt_0'], True)}`, "
                f"3m `{_fmt(b3['prob_cagr_edge_gt_0'], True)}`, 12m `{_fmt(b12['prob_cagr_edge_gt_0'], True)}`",
                f"- Bootstrap P(final rel>1): 12m `{_fmt(b12['prob_final_rel_gt_1'], True)}`",
                f"- PSR(active): `{_fmt(r['psr_active']['psr'], True)}`; "
                f"DSR(active, n_trials={payload['n_trials']}): `{_fmt(r['dsr_active']['dsr'], True)}`",
                f"- MinTRL(active): `{_fmt(r['min_trl_active']['min_trl_years'])}` years "
                f"(observed `{_fmt(r['min_trl_active']['observed_years'])}`, "
                f"sufficient=`{r['min_trl_active']['sufficient']}`)",
                f"- Skew/kurt/acf1: `{_fmt(r['moments']['skewness'])}` / "
                f"`{_fmt(r['moments']['excess_kurtosis'])}` / `{_fmt(r['moments']['acf1'])}`",
                f"- Effective n: `{_fmt(r['effective_n']['n_eff'])}` (n=`{r['effective_n']['n']}`, "
                f"ρ1=`{_fmt(r['effective_n']['rho1'])}`)",
                f"- Power years (80%): `{_fmt(r['power_years'].get('years_needed'))}`",
                "",
            ]
        )

    lines.append("## Batteries")
    lines.append("")
    block("EW9_monthly vs SPY", "EW9_monthly_vs_SPY")
    block("EW9_monthly vs no-rebalance (rebalance premium)", "EW9_monthly_vs_no_rebalance")
    if "EW9_monthly_vs_RSP_same_span" in payload["results"]:
        block("EW9_monthly vs RSP (same span)", "EW9_monthly_vs_RSP_same_span")
    block("EW9_quarterly vs SPY (secondary; not primary)", "EW9_quarterly_vs_SPY")
    block("EW9_annual vs SPY (secondary; not primary)", "EW9_annual_vs_SPY")

    lines.extend(
        [
            "## Multiple-testing adjustments (Newey-West p-values)",
            "",
            f"```json\n{json.dumps(payload['multiple_testing'], indent=2)}\n```",
            "",
            "## Answers to the six questions",
            "",
            f"1. **CAGR vs SPY noise?** `{j['q1_cagr_vs_spy']['answer']}` — "
            f"edge `{_fmt(j['q1_cagr_vs_spy']['cagr_edge'], True)}`, "
            f"NW p=`{_fmt(j['q1_cagr_vs_spy']['newey_west_p'])}`, "
            f"boot12=`{_fmt(j['q1_cagr_vs_spy']['boot12_prob_edge_gt0'], True)}`, "
            f"DSR=`{_fmt(j['q1_cagr_vs_spy']['dsr_active'], True)}`. "
            f"{j['q1_cagr_vs_spy']['note']}",
            f"2. **Rebalance premium noise?** `{j['q2_rebalance_premium']['answer']}` — "
            f"edge `{_fmt(j['q2_rebalance_premium']['cagr_edge'], True)}`, "
            f"NW p=`{_fmt(j['q2_rebalance_premium']['newey_west_p'])}`, "
            f"boot12=`{_fmt(j['q2_rebalance_premium']['boot12_prob_edge_gt0'], True)}`, "
            f"DSR=`{_fmt(j['q2_rebalance_premium']['dsr_active'], True)}`.",
            f"3. **Independent vs RSP?** `{j['q3_vs_rsp']['answer']}` — "
            f"same-span edge `{_fmt(j['q3_vs_rsp']['cagr_edge_same_span'], True)}` "
            f"({j['q3_vs_rsp'].get('note')}).",
            f"4. **Added sample needed?** {j['q4_sample_size']['answer']} "
            f"(MinTRL sufficient=`{j['q4_sample_size']['min_trl_sufficient']}`).",
            f"5. **Forward evidence only?** `{j['q5_forward_only']['answer']}` — "
            + "; ".join(j["q5_forward_only"]["reasons"]),
            f"6. **Any statistically evidenced return strategy?** `{j['q6_any_stat_return_strategy']['answer']}` — "
            + "; ".join(j["q6_any_stat_return_strategy"]["notes"]),
            "",
            "## Hard constraints",
            "",
            "- No strategy/parameter changes",
            "- No IBKR / production config changes",
            "- Quarterly not promoted to primary on CAGR",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
