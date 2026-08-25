"""Anchored walk-forward: test blocks never used in prior selection."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .btc_signals import load_btc_weekly_signal
from .config import V2Config
from .data import load_adj_close
from .matrix import _eval_combo
from .simulate import simulate_fixed_pair, slice_period


def run_walkforward(config: V2Config, *, combos: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    matrix = config.raw["matrix"]
    blocks = config.raw["walk_forward_blocks"]
    effective = pd.Timestamp(config.raw["data"]["effective_start"])

    if combos is None:
        combos = [(on, off) for on in matrix["risk_on"] for off in matrix["risk_off"]]

    prices = load_adj_close(config, matrix["risk_on"] + matrix["risk_off"])
    etf_cal = prices.dropna(how="any").index
    risk_on_sig = load_btc_weekly_signal(config, etf_cal)

    block_results: list[dict] = []
    combo_pass_counts: dict[str, int] = {}

    for block in blocks:
        label = block["label"]
        train_end = pd.Timestamp(block["train_end"])
        test_start = pd.Timestamp(block["test_start"])
        test_end = pd.Timestamp(block["test_end"])
        train_start = effective

        rows = []
        for on_sym, off_sym in combos:
            on_px = prices[on_sym]
            off_px = prices[off_sym]
            strat, _ = simulate_fixed_pair(risk_on_sig, on_px, off_px)
            s_train = slice_period(strat, train_start, train_end)
            on_tr = slice_period(on_px.pct_change(fill_method=None), train_start, train_end)
            off_tr = slice_period(off_px.pct_change(fill_method=None), train_start, train_end)
            on_tr = on_tr.reindex(s_train.index).fillna(0.0)
            off_tr = off_tr.reindex(s_train.index).fillna(0.0)

            test_row = _eval_combo(
                on_sym,
                off_sym,
                prices,
                risk_on_sig,
                test_start,
                test_end,
                calibrate_vol_on=s_train,
                calibrate_on_r=on_tr,
                calibrate_off_r=off_tr,
            )
            if "strategy" not in test_row:
                continue
            test_row["block"] = label
            test_row["pass_sharpe_gt_1"] = bool(test_row["strategy"]["sharpe"] > 1.0)
            test_row["pass_active_positive"] = bool(test_row["cum_active"] > 0)
            test_row["pass_both"] = test_row["pass_sharpe_gt_1"] and test_row["pass_active_positive"]
            rows.append(test_row)
            key = test_row["label"]
            if test_row["pass_both"]:
                combo_pass_counts[key] = combo_pass_counts.get(key, 0) + 1

        block_results.append(
            {
                "label": label,
                "train": f"{train_start.date()}→{train_end.date()}",
                "test": f"{test_start.date()}→{test_end.date()}",
                "combos": rows,
            }
        )

    stable = sorted(combo_pass_counts.items(), key=lambda x: (-x[1], x[0]))
    v1_label = "QQQ/SHY"
    v1_pass = combo_pass_counts.get(v1_label, 0)

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "blocks": block_results,
        "stable_ranking": [{"label": k, "pass_blocks": v} for k, v in stable[:15]],
        "v1_reference_pass_blocks": v1_pass,
        "n_blocks": len(blocks),
        "judgment": _wf_judgment(stable, v1_pass, len(blocks)),
    }


def _wf_judgment(stable: list[tuple[str, int]], v1_pass: int, n_blocks: int) -> str:
    if not stable:
        return "INSUFFICIENT_DATA"
    top_label, top_pass = stable[0]
    if top_pass == n_blocks and top_label != "QQQ/SHY":
        return f"POTENTIAL_V2_{top_label}_ALL_BLOCKS_PASS"
    if top_pass >= n_blocks - 1 and top_pass > v1_pass:
        return f"STABLE_IMPROVEMENT_CANDIDATE_{top_label}"
    if v1_pass >= top_pass:
        return "V1_QQQ_SHY_REMAINS_ROBUST_REFERENCE"
    return "MIXED_WF_NO_CLEAR_V2_WINNER"


def render_walkforward_md(payload: dict) -> str:
    lines = [
        "# Anchored Walk-Forward (test blocks only)",
        "",
        f"Judgment: **`{payload['judgment']}`**",
        f"v1 QQQ/SHY pass blocks: `{payload['v1_reference_pass_blocks']}/{payload['n_blocks']}`",
        "",
        "## Stable ranking (Sharpe>1 AND cum active>0 on test)",
        "",
        "| Combo | Pass blocks |",
        "|---|---:|",
    ]
    for row in payload["stable_ranking"]:
        lines.append(f"| {row['label']} | {row['pass_blocks']} |")

    for block in payload["blocks"]:
        lines += [
            "",
            f"## Block `{block['label']}` test `{block['test']}`",
            "",
            "| Combo | Sharpe | MaxDD | Edge Sharpe | Cum active | Pass |",
            "|---|---:|---:|---:|---:|---|",
        ]
        ranked = sorted(
            block["combos"],
            key=lambda x: x.get("strategy", {}).get("sharpe", -999),
            reverse=True,
        )
        for r in ranked[:12]:
            st = r["strategy"]
            e = r["edge_vs_vol_matched"]
            lines.append(
                f"| {r['label']} | {st['sharpe']:.3f} | {100*st['max_dd']:.1f}% | "
                f"{e['sharpe_diff']:.3f} | {100*r['cum_active']:.1f}% | "
                f"{'PASS' if r['pass_both'] else '—'} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_walkforward_report(config: V2Config, payload: dict) -> None:
    import shutil

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_walkforward"
    run_dir.mkdir(parents=True, exist_ok=True)
    md = render_walkforward_md(payload)
    (run_dir / "walkforward_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "walkforward.md").write_text(md)
    latest = config.reports_dir / "walkforward.md"
    shutil.copy2(run_dir / "walkforward.md", latest)
