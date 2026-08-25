#!/usr/bin/env python3
"""Initialize PAPER_V1: hashes, manifest, exposure audit, empty append-only logs."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure import exposure_audit_text, target_weight_for_beta
from paper_trading import SIGNAL_COLUMNS, compute_paper_hashes, load_paper_config
from reporting import write_markdown_report


def main() -> int:
    cfg = load_paper_config(ROOT)
    hashes = compute_paper_hashes(ROOT)
    frozen = cfg["frozen_date"]

    # Guard: do not silently overwrite an existing different manifest
    manifest_path = ROOT / "reports" / "paper_v1_manifest.md"
    hash_store = ROOT / "reports" / "runs" / "paper_v1" / "hashes.json"
    hash_store.parent.mkdir(parents=True, exist_ok=True)
    if hash_store.exists():
        prev = json.loads(hash_store.read_text(encoding="utf-8"))
        if prev.get("composite_sha256") != hashes["composite_sha256"]:
            raise SystemExit(
                "PAPER_V1 hash changed vs stored hashes.json — "
                "do not overwrite PAPER_V1. Create PAPER_V2 instead."
            )
        print("Hashes match existing PAPER_V1 store — refresh docs only.")
    else:
        hash_store.write_text(json.dumps({"frozen_date": frozen, **hashes}, indent=2), encoding="utf-8")

    # Exposure audit
    (ROOT / "reports" / "exposure_definition_audit.md").write_text(
        exposure_audit_text(), encoding="utf-8"
    )

    # Example constructions
    examples = []
    for raw in ("TQQQ", "TECL", "TECS", "SPXL", "BSV", "UVXY"):
        pos = target_weight_for_beta(
            raw,
            target_underlying_beta=float(cfg["exposure"]["target_underlying_beta"]),
            asset_beta=cfg.get("asset_underlying_beta"),
            uvxy_max_weight=float(cfg["exposure"]["uvxy_max_portfolio_weight"]),
            defensive=cfg["exposure"]["defensive_sleeve"],
        )
        examples.append(f"- {raw}: weights={pos['weights']} implied_beta={pos['implied_underlying_beta']} overlay={pos.get('overlay')}")

    write_markdown_report(
        manifest_path,
        "PAPER_V1 Manifest (immutable)",
        {
            "Identity": "\n".join(
                [
                    f"- strategy_version: `{cfg['strategy_version']}`",
                    f"- base_tree: `{cfg['base_tree']}`",
                    f"- frozen_date: `{frozen}`",
                    f"- classification: `{cfg['classification']}`",
                    f"- allow_parameter_changes: `{cfg['allow_parameter_changes']}`",
                    f"- allow_tree_changes: `{cfg['allow_tree_changes']}`",
                    f"- allow_universe_changes: `{cfg['allow_universe_changes']}`",
                ]
            ),
            "Hashes": "\n".join(f"- `{k}`: `{v}`" for k, v in hashes.items()),
            "Signal Parameters": "\n".join(
                [
                    f"- RSI period: {cfg['parameters']['rsi_period']}",
                    f"- SPY SMA: {cfg['parameters']['spy_sma_period']}",
                    f"- QQQ SMA: {cfg['parameters']['qqq_sma_period']}",
                    f"- TQQQ SMA: {cfg['parameters']['tqqq_sma_period']}",
                    f"- thresholds: `{cfg['thresholds']}`",
                    f"- ablations: `{cfg['ablations']}`",
                ]
            ),
            "Exposure": "\n".join(
                [
                    f"- definition: `{cfg['exposure']['definition']}`",
                    f"- target_underlying_beta: **{cfg['exposure']['target_underlying_beta']}**",
                    f"- 3x ETF target weight: **{cfg['exposure']['three_x_etf_target_weight']}**",
                    f"- defensive sleeve: `{cfg['exposure']['defensive_sleeve']}` @ {cfg['exposure']['defensive_weight']}",
                    f"- UVXY max weight: **{cfg['exposure']['uvxy_max_portfolio_weight']}** (`{cfg['exposure']['uvxy_overlay_label']}`)",
                ]
            ),
            "Position Construction Examples": "\n".join(examples),
            "Execution": "\n".join(
                [
                    f"- signal: `{cfg['execution']['signal_timing']}`",
                    f"- fill: `{cfg['execution']['fill_timing']}`",
                    f"- same_close_fill: `{cfg['execution']['same_close_fill']}`",
                    f"- base cost: `{cfg['costs_base']['total_bps']} bps`",
                ]
            ),
            "Versioning Policy": cfg["versioning_policy"],
            "Init Timestamp (local)": str(date.today()),
        },
        status_banner="FROZEN",
    )

    # Append-only log skeleton (header only if missing)
    log_path = ROOT / "logs" / "paper_signals.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        import pandas as pd

        pd.DataFrame(columns=SIGNAL_COLUMNS).to_csv(log_path, index=False)
        print(f"Created empty append-only log: {log_path}")
    else:
        print(f"Existing signal log preserved: {log_path}")

    # State dir
    state_dir = ROOT / "logs" / "paper_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = ROOT / "logs" / "paper_daily_metrics.csv"
    if not metrics_path.exists():
        import pandas as pd

        pd.DataFrame(
            columns=[
                "date",
                "nav",
                "return",
                "drawdown",
                "raw_target",
                "paper_target",
                "branch_id",
                "days_in_position",
                "turnover",
                "vol_20d",
                "vol_60d",
                "sharpe_20d",
                "sharpe_60d",
                "beta_spy",
                "beta_qqq",
                "cost_bps_case",
                "version",
            ]
        ).to_csv(metrics_path, index=False)

    shadows_path = ROOT / "logs" / "paper_shadows.csv"
    if not shadows_path.exists():
        import pandas as pd

        pd.DataFrame(
            columns=[
                "date",
                "SHADOW_A_nav",
                "SHADOW_B_nav",
                "SHADOW_C_nav",
                "SHADOW_D_nav",
                "SHADOW_E_nav",
            ]
        ).to_csv(shadows_path, index=False)

    (ROOT / "reports" / "paper").mkdir(parents=True, exist_ok=True)

    print("PAPER_V1 initialized.")
    print(json.dumps(hashes, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
