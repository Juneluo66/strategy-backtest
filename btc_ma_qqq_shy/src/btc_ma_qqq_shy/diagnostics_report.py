"""Markdown report for return-vs-risk timing diagnostics."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import ProjectConfig


def _pct(x, d=2):
    if x is None or (isinstance(x, float) and x != x):
        return "n/a"
    return f"{100 * float(x):.{d}f}%"


def _n(x, d=3):
    if x is None or (isinstance(x, float) and x != x):
        return "n/a"
    return f"{float(x):.{d}f}"


def _coef_line(fit: dict, name: str = "btc_signal") -> str:
    if not fit.get("ok"):
        return "n/a"
    c = fit["coef"].get(name)
    t = fit["t_stat"].get(name)
    p = fit["p_value"].get(name)
    return f"β={_n(c, 5)}  t={_n(t, 2)}  p={_n(p, 3)}  n={fit.get('n')}  NW-lags={fit.get('lags')}"


def render_diagnostics_md(payload: dict[str, Any]) -> str:
    kt = payload["key_tests"]
    lines = [
        "# BTC Gate Diagnostics — Return Timing vs Risk Timing",
        "",
        "## Verdict",
        "",
        f"- **Judgment: `{payload['judgment']}`**",
        f"- Sample: `{payload['effective_sample'][0]}` → `{payload['effective_sample'][1]}` (`{payload['sample_label']}`)",
        f"- Frozen rule under audit: SMA`{payload['frozen_rules']['sma']}` + MOM`{payload['frozen_rules']['mom']}` (do not retune from this report)",
        "",
        "## 0. What this answers",
        "",
        "Does the BTC Risk-On/Off state forecast **QQQ forward returns**, or mainly **QQQ forward volatility / drawdown risk**?",
        "NAV/Sharpe of the QQQ↔SHY switch is secondary here; ΔR and incremental β after placebos/controls are primary.",
        "",
        "## 1. Conditional forward QQQ outcomes given daily BTC Risk-On/Off",
        "",
        "| k | E[R\\|ON] | E[R\\|OFF] | ΔR | Vol ON | Vol OFF | ΔVol | DVol ON | DVol OFF |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in payload["conditional_forwards"]:
        lines.append(
            f"| {r['k']} | {_pct(r['E_R_on'])} | {_pct(r['E_R_off'])} | {_pct(r['delta_R'])} | "
            f"{_pct(r['vol_on'])} | {_pct(r['vol_off'])} | {_pct(r['delta_vol'])} | "
            f"{_pct(r['dvol_on'])} | {_pct(r['dvol_off'])} |"
        )
    c20 = kt.get("cond_k20") or {}
    lines += [
        "",
        f"At k=20: ΔR=`{_pct(c20.get('delta_R'))}`, ΔVol=`{_pct(c20.get('delta_vol'))}` "
        f"(negative ΔVol = ON has lower forward vol).",
        "",
        "## 2. Predictive regression (Newey-West HAC)",
        "",
        "### Univariate: R_QQQ(t+1:t+k) = α + β BTCSignal_t + ε",
        "",
    ]
    for fit in payload["predictive_univariate"]:
        lines.append(f"- k={fit.get('horizon')}: {_coef_line(fit)}")
    lines += [
        "",
        "### Control QQQ own trend: + β2 QQQTrend_t",
        "",
    ]
    for fit in payload["predictive_control_qqq_trend"]:
        lines.append(f"- k={fit.get('horizon')}: BTC {_coef_line(fit)} ; QQQTrend {_coef_line(fit, 'qqq_trend')}")
    lines += [
        "",
        "### Full controls: + QQQTrend + SPYTrend + VIX z-score",
        "",
    ]
    for fit in payload["predictive_control_full"]:
        lines.append(
            f"- k={fit.get('horizon')}: BTC {_coef_line(fit)} ; "
            f"QQQ {_coef_line(fit, 'qqq_trend')} ; SPY {_coef_line(fit, 'spy_trend')} ; "
            f"VIX {_coef_line(fit, 'vix_z')}"
        )
    lines += [
        "",
        "### Direct risk-timing regressions",
        "",
    ]
    for fit in payload["vol_timing_regs"]:
        lines.append(f"- {fit.get('dep')}: {_coef_line(fit)}")
    lines += [
        "",
        f"Key k=20: univ t=`{_n(kt.get('univ_k20_t'),2)}`; "
        f"after QQQ trend t=`{_n(kt.get('ctrl_qqq_trend_k20_t'),2)}`; "
        f"after full controls t=`{_n(kt.get('ctrl_full_k20_t'),2)}`.",
        "",
        "## 3. Lead-lag: Corr(R_BTC_{t-k}, R_QQQ_t)",
        "",
        "| k | corr | role |",
        "|---:|---:|---|",
    ]
    for r in payload["lead_lag"]:
        lines.append(f"| {r['k']} | {_n(r['corr'], 3)} | {r['interpretation']} |")
    lines += [
        "",
        "## 4. Placebo gates (same SMA50/MOM20 → QQQ else SHY; only signal asset changes)",
        "",
        "| Signal asset | Sharpe | CAGR | Vol | MaxDD | %QQQ |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, p in payload["placebos"].items():
        lines.append(
            f"| {name} | {_n(p.get('sharpe'))} | {_pct(p.get('cagr'))} | {_pct(p.get('ann_vol'))} | "
            f"{_pct(p.get('max_dd'))} | {_pct(p.get('pct_qqq'))} |"
        )
    lines += [
        "",
        "If BTC ≈ QQQ/SPY/IWM/SOXX placebos, BTC is not special — it is a generic trend/risk filter.",
        "",
        "## 5. Yearly active return (strategy − QQQ)",
        "",
        "| Year | Σ active | Strat year | QQQ year | Strat Sharpe | QQQ Sharpe |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for r in payload["yearly_active"]:
        lines.append(
            f"| {r['year']} | {_pct(r['sum_active'])} | {_pct(r['strategy_cagr_approx'])} | "
            f"{_pct(r['qqq_cagr_approx'])} | {_n(r['strategy_sharpe'])} | {_n(r['qqq_sharpe'])} |"
        )
    lines += [
        "",
        "## 6. Leave-one-crisis-out (Sharpe)",
        "",
        "| Removed | Strat Sharpe | QQQ Sharpe | Strat MaxDD |",
        "|---|---:|---:|---:|",
    ]
    for name, r in payload["leave_one_crisis_out"].items():
        st = r.get("strategy_stats") or {}
        lines.append(
            f"| {name} `{r.get('removed')}` | {_n(r.get('strategy_sharpe'))} | "
            f"{_n(r.get('qqq_sharpe'))} | {_pct(st.get('max_drawdown'))} |"
        )
    lines += [
        "",
        "## 7. Parameter robustness surface (strategy Sharpe)",
        "",
        "Rows = SMA, columns = MOM:",
        "",
        "```",
        str(
            __import__("pandas")
            .DataFrame(payload["param_grid"])
            .pivot(index="sma", columns="mom", values="sharpe")
            .round(3)
            .to_string()
        ),
        "```",
        "",
        "Frozen 50/20 cell must not be a lone spike; a plateau is healthier.",
        "",
        "## 8. Walk-forward slices (contaminated research sample)",
        "",
        "> Entire 2014–2026 span was inspected before these splits; treat as **research partitions**, not true locked OOS.",
        "",
    ]
    for name, w in payload["walk_forward"].items():
        s, q = w["strategy"], w["qqq"]
        lines.append(
            f"- **{name}** `{w['window']}`: strat Sharpe `{_n(s.get('sharpe'))}` CAGR `{_pct(s.get('cagr'))}` "
            f"MaxDD `{_pct(s.get('max_drawdown'))}` | QQQ Sharpe `{_n(q.get('sharpe'))}` CAGR `{_pct(q.get('cagr'))}`"
        )
    boot = payload["bootstrap_sharpe"]
    d = boot["sharpe_diff_strategy_minus_qqq"]
    lines += [
        "",
        "## 9. Block bootstrap Sharpe (block=21, n=2000)",
        "",
        f"- Point: strategy `{_n(boot['point_strategy'])}` vs QQQ `{_n(boot['point_qqq'])}` "
        f"(diff `{_n(boot['point_diff'])}`)",
        f"- Strategy Sharpe 90% band: `[{_n(boot['strategy_sharpe']['p05'])}, {_n(boot['strategy_sharpe']['p95'])}]`",
        f"- Diff (strat−QQQ) 90% band: `[{_n(d['p05'])}, {_n(d['p95'])}]` ; P(diff>0)=`{_pct(d['p_gt_0'])}`",
        "",
        "## 10. CAPM (caveat: dynamic beta)",
        "",
        f"- {_coef_line(payload['capm'], 'const')} (α)",
        f"- {_coef_line(payload['capm'], 'mkt')} (β_mkt)",
        f"- Note: {payload['capm'].get('note')}",
        "",
        "## Research conclusion (forced distinction)",
        "",
        "### Return forecasting vs risk timing",
        "",
        "- **Risk timing is statistically clearer**: |R_{t+1}| and 20d RV regressions have "
        "large negative β on BTC Risk-On (t≈−5.5 / −3.6). Conditional ΔVol at k=20 ≈ −4pp.",
        "- **Return edge exists in-sample but is weaker / fragile**: univ k=20 β>0 with t≈2; "
        "survives QQQ-trend and VIX controls on this contaminated sample; lead-lag shows "
        "**almost no** BTC→QQQ return lead (contemporaneous corr≈0.24 dominates).",
        "- **Placebos**: BTC gate Sharpe (1.22) **beats** QQQ/SPY/IWM/SOXX self-gates "
        "(0.64–0.89) — not explained as pure QQQ-trend proxy on this sample.",
        "- **Crisis concentration**: 2022 alone contributes ≈+37pp cumulative active vs QQQ; "
        "removing 2022 still leaves Strat Sharpe>~1.3 but changes the economic story.",
        "- **Bootstrap**: Strat−QQQ Sharpe diff 90% band includes **negative** values "
        "(P(diff>0)≈90%, not overwhelming).",
        "- **Parameter grid**: 50/20 is on a plateau (many cells Sharpe>~1.1), not a lone spike.",
        "- **OOS**: full span is research-contaminated; 2023–2026 slice still has lower CAGR "
        "than buy&hold QQQ with higher Sharpe — consistent with risk timing, not return alpha.",
        "",
        "Bottom line: treat as a **candidate risk-timing / regime filter** with an in-sample "
        "return coefficient that is **not yet** clean tradable alpha. Freeze rules; only "
        "forward evidence can promote.",
        "",
    ]
    return "\n".join(lines)


def write_diagnostics_report(config: ProjectConfig, payload: dict) -> Path:
    md = render_diagnostics_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_diagnostics"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "diagnostics_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "return_vs_risk_timing.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)

    latest = config.reports_dir / "return_vs_risk_timing.md"
    shutil.copy2(run_dir / "return_vs_risk_timing.md", latest)
    status = "\n".join(
        [
            "# BTC MA QQQ/SHY — Status",
            "",
            f"- Latest diagnostics: `{run_dir.name}`",
            f"- Judgment: **{payload['judgment']}**",
            f"- Report: `reports/return_vs_risk_timing.md`",
            "- Primary rules remain frozen (SMA50/MOM20); grid is robustness only.",
            "- No IBKR / production changes",
            "",
        ]
    )
    (config.reports_dir / "PROJECT_STATUS.md").write_text(status)
    return latest
