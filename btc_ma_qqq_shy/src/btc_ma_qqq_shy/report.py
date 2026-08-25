"""Write markdown + JSON audit artifacts."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import ProjectConfig
from .metrics import occupancy, relative_to, summary_stats


def _pct(x: float | None, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and (x != x)):
        return "n/a"
    return f"{100.0 * float(x):.{digits}f}%"


def _num(x: float | None, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and (x != x)):
        return "n/a"
    return f"{float(x):.{digits}f}"


def build_payload(config: ProjectConfig, bt: dict) -> dict[str, Any]:
    ra = bt["returns_audit"]
    stats = {
        "strategy": summary_stats(ra["strategy"]),
        "SPY": summary_stats(ra["SPY"]),
        "QQQ": summary_stats(ra["QQQ"]),
        "SHY": summary_stats(ra["SHY"]),
    }
    rel = {
        "vs_SPY": relative_to(ra["strategy"], ra["SPY"]),
        "vs_QQQ": relative_to(ra["strategy"], ra["QQQ"]),
    }
    occ = occupancy(bt["position_audit"], config.raw["data"]["risk_on"], config.raw["data"]["risk_off"])

    # Claim checks (email): better max DD and risk-adjusted vs SPY and QQQ
    s, spy, qqq = stats["strategy"], stats["SPY"], stats["QQQ"]
    claim = {
        "max_dd_better_than_SPY": s.get("max_drawdown", 0) > spy.get("max_drawdown", 0),  # less negative
        "max_dd_better_than_QQQ": s.get("max_drawdown", 0) > qqq.get("max_drawdown", 0),
        "sharpe_better_than_SPY": s.get("sharpe", 0) > spy.get("sharpe", 0),
        "sharpe_better_than_QQQ": s.get("sharpe", 0) > qqq.get("sharpe", 0),
        "sortino_better_than_SPY": s.get("sortino", 0) > spy.get("sortino", 0),
        "sortino_better_than_QQQ": s.get("sortino", 0) > qqq.get("sortino", 0),
        "calmar_better_than_SPY": s.get("calmar", 0) > spy.get("calmar", 0),
        "calmar_better_than_QQQ": s.get("calmar", 0) > qqq.get("calmar", 0),
    }
    claim["email_claim_drawdown_and_risk_adj_vs_both"] = all(
        [
            claim["max_dd_better_than_SPY"],
            claim["max_dd_better_than_QQQ"],
            claim["sharpe_better_than_SPY"],
            claim["sharpe_better_than_QQQ"],
        ]
    )

    return {
        "config": config.raw,
        "audit_start": str(bt["audit_start"].date()),
        "audit_start_requested": str(bt["audit_start_requested"].date()),
        "btc_price_start": str(bt["btc_price_start"].date()),
        "first_signal_date": str(bt["first_signal_date"].date()),
        "switch_count_audit": bt["switch_count_audit"],
        "occupancy": occ,
        "stats": stats,
        "relative": rel,
        "claim_checks": claim,
        "judgment": (
            "EMAIL_CLAIM_SUPPORTED_ON_THIS_SAMPLE"
            if claim["email_claim_drawdown_and_risk_adj_vs_both"]
            else "EMAIL_CLAIM_NOT_FULLY_SUPPORTED_ON_THIS_SAMPLE"
        ),
        "notes": [
            "DISCOVERY_SAMPLE / EMAIL_CLAIM_AUDIT — not pre-registered OOS.",
            "Signal: BTC-USD > SMA50 and 20d return > 0; weekly last-session check.",
            "Execution: next session after week-end decision (no same-bar fill).",
            "Yahoo BTC-USD history begins ~2014-09-17; SMA50 delays first usable signal.",
            "Costs: 0 bps in base case (see frozen.yaml).",
            "No IBKR / production / other-strategy changes.",
        ],
    }


def render_markdown(payload: dict) -> str:
    st = payload["stats"]
    cl = payload["claim_checks"]
    lines = [
        "# BTC MA / Momentum → QQQ / SHY — Email Claim Audit",
        "",
        "## Scope",
        "",
        f"- Requested from: `{payload['audit_start_requested']}` (email 'since 2014')",
        f"- Effective window: `{payload['audit_start']}` → `{st['strategy'].get('end')}` "
        f"(BTC Yahoo start `{payload['btc_price_start']}`, first SMA/mom signal `{payload['first_signal_date']}`)",
        f"- Classification: `{payload['config']['labels']['classification']}`",
        f"- Judgment: **`{payload['judgment']}`**",
        f"- Switches (audit): `{payload['switch_count_audit']}`",
        f"- Occupancy QQQ/SHY: `{_pct(payload['occupancy'].get('pct_qqq'))}` / `{_pct(payload['occupancy'].get('pct_shy'))}`",
        "",
        "## Rules (frozen)",
        "",
        "- Weekly last trading session: if BTC-USD > 50DMA **and** 20-day momentum > 0 → hold **QQQ**, else **SHY**.",
        "- Position applies from the **next** session (no same-bar fill).",
        "- Benchmarks: SPY, QQQ. Email claim: since 2014, better drawdown & risk-adjusted returns vs both.",
        "",
        "## Absolute performance (audit window)",
        "",
        "| Series | CAGR | Vol | Sharpe | Sortino | Calmar | Max DD | Final NAV |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("strategy", "SPY", "QQQ", "SHY"):
        s = st[name]
        lines.append(
            f"| {name} | {_pct(s.get('cagr'))} | {_pct(s.get('ann_vol'))} | {_num(s.get('sharpe'))} | "
            f"{_num(s.get('sortino'))} | {_num(s.get('calmar'))} | {_pct(s.get('max_drawdown'))} | {_num(s.get('final_nav'), 3)} |"
        )
    lines += [
        "",
        "## Relative (Metric C style nav_s/nav_b)",
        "",
    ]
    for k, v in payload["relative"].items():
        lines.append(
            f"- **{k}**: rel CAGR `{_pct(v.get('relative_cagr'))}`, final rel `{_num(v.get('final_relative_nav'))}`, "
            f"rel maxDD `{_pct(v.get('relative_max_dd'))}`, IR `{_num(v.get('information_ratio'))}`"
        )
    lines += [
        "",
        "## Email claim checks",
        "",
        f"- Max DD better than SPY: `{cl['max_dd_better_than_SPY']}`",
        f"- Max DD better than QQQ: `{cl['max_dd_better_than_QQQ']}`",
        f"- Sharpe better than SPY: `{cl['sharpe_better_than_SPY']}`",
        f"- Sharpe better than QQQ: `{cl['sharpe_better_than_QQQ']}`",
        f"- Sortino better than SPY/QQQ: `{cl['sortino_better_than_SPY']}` / `{cl['sortino_better_than_QQQ']}`",
        f"- Calmar better than SPY/QQQ: `{cl['calmar_better_than_SPY']}` / `{cl['calmar_better_than_QQQ']}`",
        f"- **Claim (DD + Sharpe vs both): `{cl['email_claim_drawdown_and_risk_adj_vs_both']}`**",
        "",
        "## Notes",
        "",
    ]
    for n in payload["notes"]:
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines)


def write_report(config: ProjectConfig, bt: dict) -> Path:
    payload = build_payload(config, bt)
    md = render_markdown(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_email_claim_audit"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "audit_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "email_claim_audit.md").write_text(md)
    with (run_dir / "config_snapshot.yaml").open("w") as f:
        yaml.safe_dump(config.raw, f, sort_keys=False)

    # equity / positions
    eq = (1.0 + bt["returns_audit"]["strategy"]).cumprod()
    eq.to_frame("nav").to_csv(run_dir / "equity_strategy.csv")
    bt["position_audit"].to_csv(run_dir / "positions.csv", header=["asset"])

    # promote latest
    latest = config.reports_dir / "email_claim_audit.md"
    shutil.copy2(run_dir / "email_claim_audit.md", latest)
    status = "\n".join(
        [
            "# BTC MA QQQ/SHY — Status",
            "",
            f"- Latest run: `{run_dir.name}`",
            f"- Judgment: **{payload['judgment']}**",
            f"- Report: `reports/email_claim_audit.md`",
            "- No IBKR / production changes",
            "",
        ]
    )
    (config.reports_dir / "PROJECT_STATUS.md").write_text(status)
    return latest
