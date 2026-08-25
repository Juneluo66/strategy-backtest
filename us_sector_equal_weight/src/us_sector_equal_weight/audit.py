"""Full pre-registered EW9 equal-weight audit orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .artifacts import new_run_directory
from .attribution import (
    average_weights,
    rebalance_vs_hold_gap,
    sector_return_contributions,
    single_sector_dominance,
    tech_weight_gap,
)
from .backtest import buy_and_hold
from .config import load_config
from .data import audit_prices, fetch_prices, load_ohlc, load_rf_daily, strict_common_index
from .french import run_french_validation
from .gate import evaluate_gate
from .metrics import metric_c_relative_stats, rich_metrics
from .robustness import block_bootstrap_cagr_edge, clip_equity, leave_one_out, rolling_win_rates
from .schedules import (
    SECTORS,
    run_ew9_version,
    run_no_rebalance_basket,
    run_spy_monthly_reset,
)


def _bh_frame(closes: pd.Series) -> pd.DataFrame:
    r = closes.pct_change(fill_method=None).dropna()
    eq = pd.DataFrame({"gross_return": r, "cost": 0.0, "net_return": r})
    eq["equity_net"] = (1 + eq["net_return"]).cumprod()
    eq["equity_gross"] = eq["equity_net"]
    return eq


def _cagr_only(net: pd.Series) -> dict:
    net = net.dropna()
    if net.empty:
        return {"status": "EMPTY", "cagr": np.nan, "max_drawdown": np.nan, "sharpe": np.nan}
    years = max((net.index.max() - net.index.min()).days / 365.25, 1 / 12)
    nav = (1 + net).cumprod()
    return {
        "status": "OK",
        "cagr": float(nav.iloc[-1] ** (1 / years) - 1),
        "final_wealth": float(nav.iloc[-1]),
        "max_drawdown": float((nav / nav.cummax() - 1).min()),
        "start": str(net.index.min().date()),
        "end": str(net.index.max().date()),
    }


def run_full_audit(project_root: Optional[Path] = None, *, refresh: bool = False) -> Path:
    config = load_config(project_root)
    fetch_prices(config, refresh=refresh)
    # Ensure RSP present
    if "RSP" not in config.price_symbols:
        pass
    opens, closes, raw = load_ohlc(
        config, symbols=list(dict.fromkeys(config.sectors + config.benchmarks))
    )
    price_audit = audit_prices(config, opens, closes, raw)

    # Discovery panel: nine sectors + SPY
    common = strict_common_index(closes[config.panel_symbols])
    opens_c = opens.reindex(common)
    closes_c = closes.reindex(common)
    rf, rf_meta = load_rf_daily(config, common)

    run_dir = new_run_directory(config, "full-audit")
    bps = config.one_way_bps

    # --- Discovery sample strategies ---
    discovery = {}
    for version in config.versions:
        out = run_ew9_version(opens_c, closes_c, version, one_way_bps=bps)
        metrics = rich_metrics(
            out["equity"],
            out["trades"],
            spy=closes_c["SPY"],
            rf=rf,
            rf_meta=rf_meta,
        )
        discovery[version] = {"run": out, "metrics": metrics}

    # Benchmarks
    spy_bh = _bh_frame(closes_c["SPY"])
    discovery["spy_bh"] = {
        "run": {"equity": spy_bh, "trades": pd.DataFrame()},
        "metrics": rich_metrics(
            spy_bh, pd.DataFrame(), spy=closes_c["SPY"], rf=rf, rf_meta=rf_meta, turnover_status="buy_and_hold"
        ),
    }
    spy_m = run_spy_monthly_reset(opens_c, closes_c, one_way_bps=bps)
    discovery["spy_monthly_reset"] = {
        "run": spy_m,
        "metrics": rich_metrics(spy_m["equity"], spy_m["trades"], spy=closes_c["SPY"], rf=rf, rf_meta=rf_meta),
    }
    hold = run_no_rebalance_basket(opens_c, closes_c, one_way_bps=bps)
    discovery["ew9_no_rebalance_basket"] = {
        "run": hold,
        "metrics": rich_metrics(hold["equity"], hold["trades"], spy=closes_c["SPY"], rf=rf, rf_meta=rf_meta),
    }

    # RSP from its own start ∩ sectors available
    if "RSP" in closes.columns and closes["RSP"].notna().any():
        rsp_idx = closes.index[closes[["RSP"] + SECTORS].notna().all(axis=1)]
        if len(rsp_idx):
            rsp_bh = _bh_frame(closes.loc[rsp_idx, "RSP"])
            # Align metrics on RSP span vs SPY
            discovery["rsp_bh"] = {
                "run": {"equity": rsp_bh, "trades": pd.DataFrame()},
                "metrics": rich_metrics(
                    rsp_bh,
                    pd.DataFrame(),
                    spy=closes["SPY"],
                    rf=rf.reindex(rsp_bh.index),
                    rf_meta=rf_meta,
                    turnover_status="buy_and_hold",
                ),
            }
            # Also EW monthly on RSP-common span for fair RSP comparison
            o2 = opens.reindex(rsp_idx)
            c2 = closes.reindex(rsp_idx)
            ew_rsp_span = run_ew9_version(o2, c2, "EW9_monthly", one_way_bps=bps)
            discovery["EW9_monthly_on_rsp_span"] = {
                "run": ew_rsp_span,
                "metrics": rich_metrics(
                    ew_rsp_span["equity"],
                    ew_rsp_span["trades"],
                    spy=c2["SPY"],
                    rf=rf.reindex(rsp_idx),
                    rf_meta=rf_meta,
                ),
            }
        else:
            discovery["rsp_bh"] = {"run": None, "metrics": {"status": "EMPTY"}}
    else:
        discovery["rsp_bh"] = {"run": None, "metrics": {"status": "EMPTY"}}

    discovery["sector_cap_weight_proxy"] = {
        "metrics": {
            "status": "NOT_COMPUTED",
            "reason": "No reliable point-in-time sector market-cap weights; refusing to backfill with current weights.",
        }
    }

    # Metric C packs for primary monthly
    m_net = discovery["EW9_monthly"]["run"]["equity"]["net_return"]
    metric_c = {
        "vs_spy": metric_c_relative_stats(m_net, closes_c["SPY"].pct_change(fill_method=None)),
        "vs_no_rebalance": metric_c_relative_stats(
            m_net, discovery["ew9_no_rebalance_basket"]["run"]["equity"]["net_return"]
        ),
        "monthly_vs_quarterly": metric_c_relative_stats(
            m_net, discovery["EW9_quarterly"]["run"]["equity"]["net_return"]
        ),
        "monthly_vs_annual": metric_c_relative_stats(
            m_net, discovery["EW9_annual"]["run"]["equity"]["net_return"]
        ),
    }
    if discovery.get("rsp_bh", {}).get("run") is not None:
        rsp_net = discovery["rsp_bh"]["run"]["equity"]["net_return"]
        # Compare EW on RSP span to RSP
        if "EW9_monthly_on_rsp_span" in discovery:
            metric_c["vs_rsp"] = metric_c_relative_stats(
                discovery["EW9_monthly_on_rsp_span"]["run"]["equity"]["net_return"], rsp_net
            )

    # Attribution
    w = discovery["EW9_monthly"]["run"]["weights"]
    avg_w = average_weights(w)
    contrib = sector_return_contributions(w, closes_c)
    attrib = {
        "avg_weights": avg_w.to_dict(),
        "contributions": contrib.to_dict(),
        "dominance": single_sector_dominance(contrib),
        "tech_gap": tech_weight_gap(avg_w),
        "rebalance_vs_hold": rebalance_vs_hold_gap(
            m_net, discovery["ew9_no_rebalance_basket"]["run"]["equity"]["net_return"]
        ),
        "sample_label": "DISCOVERY_SAMPLE",
    }

    # Pseudo-OOS fixed starts
    pseudo_oos = {}
    for start in config.raw["pseudo_oos_starts"]:
        block = {}
        for version in config.versions:
            eq = clip_equity(discovery[version]["run"]["equity"], start=start)
            block[version] = _cagr_only(eq["net_return"])
        eq_spy = clip_equity(spy_bh, start=start)
        block["spy_bh"] = _cagr_only(eq_spy["net_return"])
        pseudo_oos[start] = block

    # Fixed endpoints from discovery start
    fixed_endpoints = {}
    for ep in config.raw["fixed_endpoints"]:
        end = "latest" if ep == "latest" else ep
        block = {}
        for version in config.versions:
            eq = clip_equity(discovery[version]["run"]["equity"], end=end)
            block[version] = _cagr_only(eq["net_return"])
        block["spy_bh"] = _cagr_only(clip_equity(spy_bh, end=end)["net_return"])
        fixed_endpoints[str(ep)] = block

    # Exclude last N years
    exclude_recent = {}
    for y in config.raw["exclude_last_years"]:
        cut = common.max() - pd.Timedelta(days=365 * int(y))
        block = {}
        for version in config.versions:
            eq = clip_equity(discovery[version]["run"]["equity"], end=cut)
            block[version] = _cagr_only(eq["net_return"])
        block["spy_bh"] = _cagr_only(clip_equity(spy_bh, end=cut)["net_return"])
        exclude_recent[str(y)] = block

    # Cost / delay stress
    cost_stress = {}
    for b in config.raw["cost_stress_bps"]:
        block = {}
        for version in ["EW9_monthly", "EW9_quarterly", "EW9_annual"]:
            out = run_ew9_version(opens_c, closes_c, version, one_way_bps=float(b))
            block[version] = _cagr_only(out["equity"]["net_return"])
        cost_stress[str(float(b))] = block

    delay_stress = {}
    for version in config.versions:
        out = run_ew9_version(
            opens_c, closes_c, version, one_way_bps=bps, execution_delay_sessions=2
        )
        delay_stress[version] = _cagr_only(out["equity"]["net_return"])

    # Rolling
    spy_ret = closes_c["SPY"].pct_change(fill_method=None)
    rolling = {
        f"{y}y": rolling_win_rates(m_net, spy_ret, years=int(y))
        for y in config.raw["rolling_years"]
    }

    loo = leave_one_out(opens_c, closes_c, version="EW9_monthly", one_way_bps=bps)
    boot = block_bootstrap_cagr_edge(m_net, spy_ret)

    # French external
    try:
        french = run_french_validation(config, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        french = {"status": "FAILED", "error": str(exc)}

    payload = {
        "price_audit": price_audit,
        "rf_meta": rf_meta,
        "discovery_label": "DISCOVERY_SAMPLE",
        "discovery_common_start": str(common.min().date()),
        "discovery_common_end": str(common.max().date()),
        "discovery": {
            k: {"metrics": v["metrics"]}
            for k, v in discovery.items()
        },
        "metric_c": {
            k: {kk: vv for kk, vv in d.items() if kk != "frame"}
            for k, d in metric_c.items()
        },
        "attribution": attrib,
        "pseudo_oos": pseudo_oos,
        "fixed_endpoints": fixed_endpoints,
        "exclude_recent": exclude_recent,
        "cost_stress": cost_stress,
        "delay_stress": delay_stress,
        "rolling": rolling,
        "leave_one_out": loo,
        "bootstrap": boot,
        "french": french,
    }
    gate = evaluate_gate(payload, config.raw)
    payload["gate"] = gate

    # Persist
    (run_dir / "audit_payload.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    for version in config.versions:
        discovery[version]["run"]["equity"].to_csv(run_dir / f"equity_{version}.csv")
        discovery[version]["run"]["trades"].to_csv(run_dir / f"trades_{version}.csv", index=False)
    contrib.to_csv(run_dir / "sector_contributions.csv")
    pd.DataFrame(
        [
            {"name": k, **{kk: vv for kk, vv in v["metrics"].items() if not isinstance(vv, (dict, list))}}
            for k, v in discovery.items()
            if isinstance(v.get("metrics"), dict)
        ]
    ).to_csv(run_dir / "main_metrics.csv", index=False)

    report = _write_report(config.reports_dir / "sector_equal_weight_audit.md", payload, run_dir, config)
    (run_dir / "sector_equal_weight_audit.md").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    _write_status(config.reports_dir / "PROJECT_STATUS.md", gate, payload)
    return report


def _fmt(x, pct=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    if pct:
        return f"{100 * float(x):.2f}%"
    if isinstance(x, (bool, np.bool_)):
        return str(bool(x))
    try:
        return f"{float(x):.4f}"
    except Exception:
        return str(x)


def _write_status(path: Path, gate: dict, payload: dict) -> None:
    lines = [
        "# US Sector Equal-Weight — Project Status",
        "",
        f"- Discovery sample: `{payload['discovery_common_start']}` → `{payload['discovery_common_end']}` "
        f"(**DISCOVERY_SAMPLE**)",
        f"- Gate: **`{gate['label']}`** ({gate['passed']}/{gate['total']})",
        f"- Preferred frequency hint: `{gate.get('preferred_frequency_hint')}`",
        "- IBKR: **not modified**",
        "- Sector momentum: **not retuned**; buffer **not** promoted",
        "- Report: `reports/sector_equal_weight_audit.md`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report(path: Path, payload: dict, run_dir: Path, config) -> Path:
    g = payload["gate"]
    d = payload["discovery"]
    lines = [
        "# Sector Equal-Weight (EW9) — Pre-registered Audit",
        "",
        "## Research framing",
        "",
        "- Independent track: **equal-weight rebalancing**, not sector-momentum retuning.",
        "- Forbidden: ranking, Top-N, SMA/trend, BIL sleeve, vol-weight, leverage, XLRE/XLC.",
        f"- ETF common sample `{payload['discovery_common_start']}` → `{payload['discovery_common_end']}` "
        "is labeled **`DISCOVERY_SAMPLE`** (secondary observation from sector_momentum research).",
        "- Leading on discovery alone is **not** independent validation.",
        f"- Run: `{run_dir}`",
        "",
        f"## Gate: `{g['label']}` ({g['passed']}/{g['total']})",
        "",
        "```json",
        json.dumps(g["checks"], indent=2),
        "```",
        "",
        f"- Notes: `{g.get('notes')}`",
        f"- RSP similarity: `{g.get('rsp_similarity_note')}`",
        f"- Frequency hint: `{g.get('preferred_frequency_hint')}`",
        "",
        "## Discovery sample metrics (DISCOVERY_SAMPLE)",
        "",
        "| name | CAGR | Sharpe(rf) | MaxDD | final wealth | ann turnover | cost drag |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    order = [
        "EW9_monthly",
        "EW9_quarterly",
        "EW9_annual",
        "ew9_no_rebalance_basket",
        "spy_bh",
        "spy_monthly_reset",
        "rsp_bh",
        "EW9_monthly_on_rsp_span",
        "sector_cap_weight_proxy",
    ]
    for name in order:
        if name not in d:
            continue
        m = d[name]["metrics"]
        if m.get("status") in {"NOT_COMPUTED", "EMPTY"}:
            lines.append(f"| {name} | {m.get('status')} | — | — | — | — | — |")
            continue
        lines.append(
            f"| {name} | {_fmt(m.get('cagr'), True)} | {_fmt(m.get('sharpe'))} | "
            f"{_fmt(m.get('max_drawdown'), True)} | {_fmt(m.get('final_wealth'))} | "
            f"{_fmt(m.get('annualized_turnover'))} | {_fmt(m.get('cost_drag_cagr'), True)} |"
        )

    lines.extend(["", "## Metric C (formal relative NAV)", ""])
    for key, block in payload["metric_c"].items():
        lines.append(
            f"- **{key}**: final_rel `{_fmt(block.get('final_relative_nav'))}`, "
            f"rel CAGR `{_fmt(block.get('relative_cagr'), True)}`, "
            f"max rel UW `{_fmt(block.get('relative_max_dd'), True)}`, "
            f"UW sessions `{_fmt(block.get('relative_underwater_trading_sessions'))}`, "
            f"UW months `{_fmt(block.get('relative_underwater_months'))}`, "
            f"current `{_fmt(block.get('current_relative_drawdown'), True)}`"
        )

    lines.extend(
        [
            "",
            "## Attribution",
            "",
            f"- Avg weights: `{payload['attribution']['avg_weights']}`",
            f"- Dominance: `{payload['attribution']['dominance']}`",
            f"- Tech/cap-weight: `{payload['attribution']['tech_gap']}`",
            f"- Rebalance vs hold: `{payload['attribution']['rebalance_vs_hold']}`",
            "",
            "## Pseudo-OOS starts (pre-registered; all kept)",
            "",
        ]
    )
    for start, block in payload["pseudo_oos"].items():
        lines.append(
            f"- `{start}`: monthly `{_fmt(block['EW9_monthly'].get('cagr'), True)}` vs SPY "
            f"`{_fmt(block['spy_bh'].get('cagr'), True)}`"
        )

    lines.extend(["", "## Fixed endpoints", ""])
    for ep, block in payload["fixed_endpoints"].items():
        lines.append(
            f"- `{ep}`: monthly `{_fmt(block['EW9_monthly'].get('cagr'), True)}` vs SPY "
            f"`{_fmt(block['spy_bh'].get('cagr'), True)}`"
        )

    lines.extend(["", "## Robustness", ""])
    lines.append(f"- Rolling: `{payload['rolling']}`")
    lines.append(f"- Cost stress: `{payload['cost_stress']}`")
    lines.append(f"- Delay+1 session: `{payload['delay_stress']}`")
    lines.append(f"- Exclude recent years: `{payload['exclude_recent']}`")
    lines.append(f"- Leave-one-out: `{payload['leave_one_out']}`")
    lines.append(f"- Bootstrap: `{payload['bootstrap']}`")

    lines.extend(["", "## French external mechanism validation", ""])
    fr = payload["french"]
    if fr.get("status") == "FAILED":
        lines.append(f"- FAILED: `{fr.get('error')}`")
    else:
        lines.append(f"- Disclaimer: `{fr.get('disclaimer')}`")
        lines.append(f"- Columns: `{fr.get('french_columns_available')}`")
        for label in ("pre_etf", "post_etf", "full"):
            block = fr.get(label, {})
            if not isinstance(block, dict):
                continue
            m = block.get("EW9_monthly", {})
            lines.append(
                f"- `{label}` EW9_monthly CAGR `{_fmt(m.get('cagr'), True)}` "
                f"(tradable=`{m.get('tradable', False)}`)"
            )

    lines.extend(
        [
            "",
            "## Hard constraints respected",
            "",
            "- IBKR not modified",
            "- Sector-momentum buffer not promoted; momentum not retuned",
            "- No claim of guaranteed profits",
            "- Cap-weight proxy NOT_COMPUTED without PIT weights",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
