"""Frozen v2 final: 4 candidates, WF blocks, cross-section, cost-adjusted risk-match."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .btc_signals import load_btc_weekly_signal
from .config import V2Config
from .data import cost_rt_bps, load_adj_close, load_ohlc
from .metrics import summary_stats, vol_matched_weight
from .simulate import simulate_fixed_pair, simulate_fixed_pair_costs, slice_period

GROWTH_ON = ["QQQ", "SMH", "SOXX", "IWO"]
BROAD_ON = ["SPY"]
SMALL_ON = ["IWM"]
ALL_ON_DIAG = ["QQQ", "SMH", "SOXX", "IWO", "IWM", "SPY"]


def _simulate(
    config: V2Config,
    on_sym: str,
    off_sym: str,
    prices: pd.DataFrame,
    risk_on_sig: pd.Series,
    *,
    with_costs: bool,
) -> tuple[pd.Series, pd.Series]:
    on_adj = prices[on_sym]
    off_adj = prices[off_sym]
    if not with_costs:
        return simulate_fixed_pair(risk_on_sig, on_adj, off_adj)
    on_ohlc = load_ohlc(config, on_sym)
    off_ohlc = load_ohlc(config, off_sym)
    rt = cost_rt_bps(config, on_sym, off_sym)
    return simulate_fixed_pair_costs(
        risk_on_sig,
        on_adj,
        off_adj,
        on_ohlc["Open"].astype(float),
        on_ohlc["Close"].astype(float),
        off_ohlc["Open"].astype(float),
        off_ohlc["Close"].astype(float),
        cost_bps_rt=rt,
    )


def _period_metrics(
    strat: pd.Series,
    on_px: pd.Series,
    off_px: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    w_vol: float | None = None,
    cal_strat: pd.Series | None = None,
    cal_on_r: pd.Series | None = None,
    cal_off_r: pd.Series | None = None,
) -> dict[str, Any]:
    s = slice_period(strat, start, end)
    if len(s) < 5:
        return {"error": "insufficient_data"}
    on_r = slice_period(on_px.pct_change(fill_method=None), start, end).reindex(s.index).fillna(0.0)
    off_r = slice_period(off_px.pct_change(fill_method=None), start, end).reindex(s.index).fillna(0.0)
    if w_vol is None and cal_strat is not None and cal_on_r is not None and cal_off_r is not None:
        w_vol = vol_matched_weight(cal_strat, cal_on_r, cal_off_r)
    elif w_vol is None:
        w_vol = vol_matched_weight(s, on_r, off_r)
    static = w_vol * on_r + (1 - w_vol) * off_r
    active = s - static
    st = summary_stats(s)
    st_s = summary_stats(static)
    cum_active = float((1 + active).prod() - 1.0)
    return {
        "cagr": st.get("cagr"),
        "sharpe": st.get("sharpe"),
        "ann_vol": st.get("ann_vol"),
        "max_dd": st.get("max_dd"),
        "cum_active": cum_active,
        "vol_matched_w_on": w_vol,
        "edge_sharpe": st.get("sharpe", np.nan) - st_s.get("sharpe", np.nan),
        "edge_cagr_pp": 100 * (st.get("cagr", np.nan) - st_s.get("cagr", np.nan)),
        "pass_sharpe_gt_1": bool(st.get("sharpe", 0) > 1.0),
        "pass_active_pos": bool(cum_active > 0),
        "pass_both": bool(st.get("sharpe", 0) > 1.0 and cum_active > 0),
    }


def _select_smh_off(config: V2Config, prices: pd.DataFrame, risk_on_sig: pd.Series) -> str:
    spec = config.raw["frozen_final_candidates"]["C"]["off_selection"]
    train = config.raw["splits"]["train"]
    t0, t1 = pd.Timestamp(train["start"]), pd.Timestamp(train["end"])
    scores = {}
    for off in spec["candidates"]:
        strat, _ = _simulate(config, "SMH", off, prices, risk_on_sig, with_costs=False)
        s = slice_period(strat, t0, t1)
        scores[off] = summary_stats(s).get("sharpe", -999)
    winner = max(scores, key=scores.get)
    return winner, scores


def resolve_final_candidates(config: V2Config, prices: pd.DataFrame, risk_on_sig: pd.Series) -> list[dict]:
    fc = config.raw["frozen_final_candidates"]
    smh_off, smh_scores = _select_smh_off(config, prices, risk_on_sig)
    return [
        {
            "key": "A",
            "id": fc["A"]["id"],
            "label": fc["A"]["label"],
            "on": fc["A"]["risk_on"],
            "off": fc["A"]["risk_off"],
            "evidence_tier": fc["A"]["evidence_tier"],
            "role": fc["A"]["role"],
        },
        {
            "key": "B",
            "id": fc["B"]["id"],
            "label": fc["B"]["label"],
            "on": fc["B"]["risk_on"],
            "off": fc["B"]["risk_off"],
            "evidence_tier": fc["B"]["evidence_tier"],
            "role": fc["B"]["role"],
        },
        {
            "key": "C",
            "id": f"BTC_SMH_{smh_off}",
            "label": f"SMH/{smh_off}",
            "on": "SMH",
            "off": smh_off,
            "evidence_tier": fc["C"]["evidence_tier"],
            "role": fc["C"]["role"],
            "train_off_selection": {
                "rule": fc["C"]["off_selection"]["rule"],
                "scores": smh_scores,
                "winner": smh_off,
            },
        },
        {
            "key": "D",
            "id": fc["D"]["id"],
            "label": fc["D"]["label"],
            "on": fc["D"]["risk_on"],
            "off": fc["D"]["risk_off"],
            "evidence_tier": fc["D"]["evidence_tier"],
            "role": fc["D"]["role"],
        },
    ]


def run_walkforward_candidates(
    config: V2Config,
    candidates: list[dict],
    prices: pd.DataFrame,
    risk_on_sig: pd.Series,
    *,
    with_costs: bool,
) -> list[dict]:
    effective = pd.Timestamp(config.raw["data"]["effective_start"])
    blocks_out = []
    for block in config.raw["walk_forward_blocks"]:
        train_end = pd.Timestamp(block["train_end"])
        test_start = pd.Timestamp(block["test_start"])
        test_end = pd.Timestamp(block["test_end"])
        train_start = effective
        row_block = {"label": block["label"], "test_range": f"{test_start.date()}→{test_end.date()}", "candidates": []}
        for cand in candidates:
            strat, _ = _simulate(config, cand["on"], cand["off"], prices, risk_on_sig, with_costs=with_costs)
            on_px = prices[cand["on"]]
            off_px = prices[cand["off"]]
            s_train = slice_period(strat, train_start, train_end)
            on_tr = slice_period(on_px.pct_change(fill_method=None), train_start, train_end)
            off_tr = slice_period(off_px.pct_change(fill_method=None), train_start, train_end)
            on_tr = on_tr.reindex(s_train.index).fillna(0.0)
            off_tr = off_tr.reindex(s_train.index).fillna(0.0)
            w = vol_matched_weight(s_train, on_tr, off_tr)
            m = _period_metrics(
                strat,
                on_px,
                off_px,
                test_start,
                test_end,
                w_vol=w,
            )
            m["candidate"] = cand["label"]
            m["id"] = cand["id"]
            row_block["candidates"].append(m)
        blocks_out.append(row_block)
    return blocks_out


def run_cross_sectional_diagnostics(
    config: V2Config,
    prices: pd.DataFrame,
    risk_on_sig: pd.Series,
    *,
    with_costs: bool,
) -> dict[str, Any]:
    """Rank ON/SHY pairs per WF block; test growth vs broad gradient."""
    effective = pd.Timestamp(config.raw["data"]["effective_start"])
    off_ref = "SHY"
    block_ranks: list[dict] = []
    for block in config.raw["walk_forward_blocks"]:
        test_start = pd.Timestamp(block["test_start"])
        test_end = pd.Timestamp(block["test_end"])
        train_end = pd.Timestamp(block["train_end"])
        train_start = effective
        rows = []
        for on in ALL_ON_DIAG:
            if on not in prices.columns or off_ref not in prices.columns:
                continue
            strat, _ = _simulate(config, on, off_ref, prices, risk_on_sig, with_costs=with_costs)
            on_px = prices[on]
            off_px = prices[off_ref]
            s_train = slice_period(strat, train_start, train_end)
            on_tr = slice_period(on_px.pct_change(fill_method=None), train_start, train_end).reindex(s_train.index).fillna(0.0)
            off_tr = slice_period(off_px.pct_change(fill_method=None), train_start, train_end).reindex(s_train.index).fillna(0.0)
            w = vol_matched_weight(s_train, on_tr, off_tr)
            m = _period_metrics(strat, on_px, off_px, test_start, test_end, w_vol=w)
            rows.append(
                {
                    "on": on,
                    "sharpe": m.get("sharpe"),
                    "cum_active": m.get("cum_active"),
                    "max_dd": m.get("max_dd"),
                    "bucket": "growth" if on in GROWTH_ON else ("broad" if on in BROAD_ON else "small"),
                }
            )
        rows_sorted = sorted(rows, key=lambda x: x.get("sharpe", -999), reverse=True)
        for i, r in enumerate(rows_sorted):
            r["rank"] = i + 1
        growth_ranks = [r["rank"] for r in rows_sorted if r["bucket"] == "growth"]
        spy_rank = next((r["rank"] for r in rows_sorted if r["on"] == "SPY"), None)
        smh_rank = next((r["rank"] for r in rows_sorted if r["on"] == "SMH"), None)
        qqq_rank = next((r["rank"] for r in rows_sorted if r["on"] == "QQQ"), None)
        block_ranks.append(
            {
                "block": block["label"],
                "ranks": rows_sorted,
                "mean_growth_rank": float(np.mean(growth_ranks)) if growth_ranks else np.nan,
                "spy_rank": spy_rank,
                "smh_rank": smh_rank,
                "qqq_rank": qqq_rank,
            }
        )

    # Weekly return correlation when BTC ON (QQQ vs SMH vs SPY)
    etf_cal = prices.dropna(how="any").index
    week_starts = list(risk_on_sig.index)
    weekly_rets = {on: [] for on in ALL_ON_DIAG}
    for i, ws in enumerate(week_starts):
        if i + 1 >= len(week_starts):
            break
        ws = pd.Timestamp(ws)
        if pd.isna(risk_on_sig.loc[ws]) or not bool(risk_on_sig.loc[ws]):
            continue
        end = pd.Timestamp(week_starts[i + 1])
        days = etf_cal[(etf_cal >= ws) & (etf_cal < end)]
        if len(days) == 0:
            continue
        for on in ALL_ON_DIAG:
            if on not in prices.columns:
                continue
            r = float((1 + prices[on].pct_change(fill_method=None).reindex(days).fillna(0.0)).prod() - 1.0)
            weekly_rets[on].append(r)
    corr_df = pd.DataFrame({k: v for k, v in weekly_rets.items() if len(v) > 10})
    corr_matrix = corr_df.corr().round(3).to_dict() if len(corr_df.columns) > 1 else {}

    # Rank stability: SMH vs SPY vs QQQ across blocks
    smh_ranks = [b["smh_rank"] for b in block_ranks if b["smh_rank"] is not None]
    spy_ranks = [b["spy_rank"] for b in block_ranks if b["spy_rank"] is not None]
    qqq_ranks = [b["qqq_rank"] for b in block_ranks if b["qqq_rank"] is not None]

    judgment = _cross_section_judgment(block_ranks, smh_ranks, spy_ranks, qqq_ranks, corr_matrix)

    return {
        "off_reference": off_ref,
        "with_costs": with_costs,
        "per_block_ranks": block_ranks,
        "btc_on_weekly_return_corr": corr_matrix,
        "rank_summary": {
            "smh_ranks": smh_ranks,
            "spy_ranks": spy_ranks,
            "qqq_ranks": qqq_ranks,
            "smh_beats_spy_blocks": sum(1 for s, p in zip(smh_ranks, spy_ranks) if s < p),
        },
        "judgment": judgment,
    }


def _cross_section_judgment(
    block_ranks: list[dict],
    smh_ranks: list[int],
    spy_ranks: list[int],
    qqq_ranks: list[int],
    corr_matrix: dict,
) -> str:
    if not block_ranks:
        return "INSUFFICIENT_DATA"
    n = len(block_ranks)
    smh_top = sum(1 for b in block_ranks if b.get("smh_rank") == 1)
    growth_wins = sum(1 for b in block_ranks if b.get("mean_growth_rank", 99) < b.get("spy_rank", 0))
    spy_top = sum(1 for b in block_ranks if b.get("spy_rank") == 1)
    # rank shuffle: std of smh ranks high means unstable
    smh_std = float(np.std(smh_ranks)) if len(smh_ranks) > 1 else 0.0
    if smh_top >= 2 and growth_wins >= n // 2:
        return "GROWTH_HIGH_BETA_GRADIENT_SUPPORTED"
    if spy_top >= 2 and all(s <= 3 for s in spy_ranks):
        return "BROAD_EQUITY_SIGNAL_DOMINATES"
    if smh_std > 1.5 and smh_top < 2:
        return "NO_STABLE_CROSS_SECTION_STRUCTURE"
    if growth_wins >= n // 2:
        return "MIXED_GROWTH_TILT_WITH_REGIME_DEPENDENCE"
    return "MIXED_NO_CLEAR_CROSS_SECTION"


def run_cost_risk_matched(
    config: V2Config,
    candidates: list[dict],
    prices: pd.DataFrame,
    risk_on_sig: pd.Series,
) -> dict[str, Any]:
    train = config.raw["splits"]["train"]
    test = config.raw["splits"]["test"]
    t0 = pd.Timestamp(train["start"])
    tr_end = pd.Timestamp(train["end"])
    te_start = pd.Timestamp(test["start"])
    te_end = pd.Timestamp(test["end"])
    rt_note = config.raw.get("execution", {})
    rows = []
    for cand in candidates:
        strat, _ = _simulate(config, cand["on"], cand["off"], prices, risk_on_sig, with_costs=True)
        on_px = prices[cand["on"]]
        off_px = prices[cand["off"]]
        s_tr = slice_period(strat, t0, tr_end)
        on_tr = slice_period(on_px.pct_change(fill_method=None), t0, tr_end).reindex(s_tr.index).fillna(0.0)
        off_tr = slice_period(off_px.pct_change(fill_method=None), t0, tr_end).reindex(s_tr.index).fillna(0.0)
        w = vol_matched_weight(s_tr, on_tr, off_tr)
        train_m = _period_metrics(strat, on_px, off_px, t0, tr_end, w_vol=w)
        test_m = _period_metrics(strat, on_px, off_px, te_start, te_end, w_vol=w)
        rows.append(
            {
                "candidate": cand["label"],
                "id": cand["id"],
                "evidence_tier": cand["evidence_tier"],
                "cost_rt_bps": cost_rt_bps(config, cand["on"], cand["off"]),
                "train": train_m,
                "test": test_m,
            }
        )
    return {
        "execution": rt_note,
        "return_path": "close_open_switch_day_plus_adj_c2c",
        "vol_match_calibrated_on": "train",
        "comparisons": rows,
    }


def _count_pass_blocks(wf: list[dict], cand_label: str) -> int:
    n = 0
    for block in wf:
        for c in block["candidates"]:
            if c.get("candidate") == cand_label and c.get("pass_both"):
                n += 1
    return n


def assign_verdicts(
    config: V2Config,
    candidates: list[dict],
    wf_cost: list[dict],
    wf_nocost: list[dict],
    cross: dict[str, Any],
    cost_cmp: dict[str, Any],
) -> dict[str, Any]:
    labels = config.raw["verdict_labels"]
    n_blocks = len(config.raw["walk_forward_blocks"])
    pass_counts = {}
    for cand in candidates:
        pass_counts[cand["label"]] = {
            "with_costs": _count_pass_blocks(wf_cost, cand["label"]),
            "adj_0bps": _count_pass_blocks(wf_nocost, cand["label"]),
        }

    a_pass = pass_counts.get("QQQ/SHY", {}).get("with_costs", 0)
    b_pass = pass_counts.get("QQQ/BIL", {}).get("with_costs", 0)
    c_label = next(c["label"] for c in candidates if c["key"] == "C")
    c_pass = pass_counts.get(c_label, {}).get("with_costs", 0)
    d_pass = pass_counts.get("SPY/BIL", {}).get("with_costs", 0)

    assignments = {}
    if a_pass >= n_blocks - 1:
        assignments["defensive_core"] = labels["core"]
    else:
        assignments["defensive_core"] = f"QQQ_SHY_PASS_{a_pass}_{n_blocks}_NOT_CORE"

    if d_pass >= n_blocks - 1:
        assignments["broad_equity"] = labels["broad"]
    else:
        assignments["broad_equity"] = f"SPY_BIL_PASS_{d_pass}_{n_blocks}_NOT_BROAD"

    if c_pass >= n_blocks - 1:
        assignments["aggressive"] = labels["aggressive"].replace("SMH", c_label.replace("/", "_"))
    else:
        assignments["aggressive"] = f"{c_label}_PASS_{c_pass}_{n_blocks}_NOT_AGGRESSIVE"

    if b_pass < a_pass and b_pass < n_blocks - 1:
        assignments["bil_parking"] = labels["bil_unvalidated"]
    elif b_pass > a_pass and b_pass >= n_blocks - 1:
        assignments["bil_parking"] = "BIL_MAY_BEAT_SHY_BUT_POST_TEST_SELECTION"
    else:
        assignments["bil_parking"] = labels["bil_unvalidated"]

    assignments["cross_section"] = cross.get("judgment")
    assignments["summary"] = (
        "Multi-label allowed: do not pick single champion; map candidates to roles by WF stability with costs."
    )
    return {
        "pass_block_counts_with_costs": pass_counts,
        "assignments": assignments,
        "n_blocks": n_blocks,
    }


def run_frozen_final(config: V2Config) -> dict[str, Any]:
    prices = load_adj_close(config, config.all_symbols())
    etf_cal = prices.dropna(how="any").index
    risk_on_sig = load_btc_weekly_signal(config, etf_cal)
    candidates = resolve_final_candidates(config, prices, risk_on_sig)

    wf_cost = run_walkforward_candidates(config, candidates, prices, risk_on_sig, with_costs=True)
    wf_adj = run_walkforward_candidates(config, candidates, prices, risk_on_sig, with_costs=False)
    cross_cost = run_cross_sectional_diagnostics(config, prices, risk_on_sig, with_costs=True)
    cost_cmp = run_cost_risk_matched(config, candidates, prices, risk_on_sig)
    verdicts = assign_verdicts(config, candidates, wf_cost, wf_adj, cross_cost, cost_cmp)

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_candidates": candidates,
        "walkforward_with_costs": wf_cost,
        "walkforward_adj_0bps": wf_adj,
        "cross_sectional": cross_cost,
        "cost_risk_matched": cost_cmp,
        "verdicts": verdicts,
    }


def render_frozen_final_md(p: dict) -> str:
    lines = [
        "# v2 Frozen Final Research Report",
        "",
        "## Frozen candidates",
        "",
        "| Key | Label | ID | Evidence tier |",
        "|---|---|---|---|",
    ]
    for c in p["frozen_candidates"]:
        lines.append(f"| {c['key']} | {c['label']} | {c['id']} | {c['evidence_tier']} |")
        if c.get("train_off_selection"):
            sel = c["train_off_selection"]
            lines.append(f"| | OFF pick: `{sel['winner']}` train Sharpe {sel['scores']} | | |")

    lines += [
        "",
        "## 1. Anchored walk-forward (with audited costs)",
        "",
        "Pass = Sharpe>1 AND cum active>0 vs train-calibrated vol-matched static.",
        "",
    ]
    for block in p["walkforward_with_costs"]:
        lines += [
            f"### Block `{block['label']}` test {block['test_range']}",
            "",
            "| Candidate | CAGR | Sharpe | MaxDD | Cum active | Edge Sharpe | Pass |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for c in block["candidates"]:
            if "error" in c:
                continue
            lines.append(
                f"| {c['candidate']} | {100*c['cagr']:.2f}% | {c['sharpe']:.3f} | "
                f"{100*c['max_dd']:.1f}% | {100*c['cum_active']:.1f}% | {c['edge_sharpe']:.3f} | "
                f"{'PASS' if c['pass_both'] else '—'} |"
            )
        lines.append("")

    lines += [
        "## 2. Cross-sectional regime diagnostics (ON/SHY, with costs)",
        "",
        f"Judgment: **`{p['cross_sectional']['judgment']}`**",
        "",
    ]
    for br in p["cross_sectional"]["per_block_ranks"]:
        lines.append(f"### Ranks — `{br['block']}` (1=best Sharpe)")
        lines.append("| Rank | ON | Sharpe | Cum active | MaxDD | Bucket |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for r in br["ranks"]:
            lines.append(
                f"| {r['rank']} | {r['on']} | {r['sharpe']:.3f} | {100*r['cum_active']:.1f}% | "
                f"{100*r['max_dd']:.1f}% | {r['bucket']} |"
            )
        lines.append(
            f"_mean growth rank={br['mean_growth_rank']:.1f}, SPY rank={br['spy_rank']}, "
            f"SMH rank={br['smh_rank']}, QQQ rank={br['qqq_rank']}_"
        )
        lines.append("")

    lines += [
        "## 3. Cost-adjusted risk-matched (train w frozen → test)",
        "",
        f"Costs: {p['cost_risk_matched']['execution'].get('costs_bps_one_way')}bps one-way + half-spreads",
        "",
        "| Candidate | Tier | Train Sharpe | Test Sharpe | Test MaxDD | Test cum active | RT bps |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in p["cost_risk_matched"]["comparisons"]:
        tr = row["train"]
        te = row["test"]
        lines.append(
            f"| {row['candidate']} | {row['evidence_tier']} | {tr.get('sharpe', 0):.3f} | "
            f"{te.get('sharpe', 0):.3f} | {100*te.get('max_dd', 0):.1f}% | "
            f"{100*te.get('cum_active', 0):.1f}% | {row['cost_rt_bps']:.1f} |"
        )

    v = p["verdicts"]
    lines += [
        "",
        "## Verdict labels (multi-conclusion allowed)",
        "",
        f"- Defensive/Core: `{v['assignments']['defensive_core']}`",
        f"- Broad equity: `{v['assignments']['broad_equity']}`",
        f"- Aggressive: `{v['assignments']['aggressive']}`",
        f"- BIL parking: `{v['assignments']['bil_parking']}`",
        f"- Cross-section: `{v['assignments']['cross_section']}`",
        "",
        f"Pass blocks (with costs): `{json.dumps(v['pass_block_counts_with_costs'])}`",
        "",
        v["assignments"]["summary"],
        "",
    ]
    return "\n".join(lines)


def write_frozen_final_report(config: V2Config, payload: dict) -> None:
    import shutil

    md = render_frozen_final_md(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.reports_dir / "runs" / f"{stamp}_frozen_final"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frozen_final_payload.json").write_text(json.dumps(payload, indent=2, default=str))
    (run_dir / "frozen_final.md").write_text(md)
    latest = config.reports_dir / "frozen_final.md"
    shutil.copy2(run_dir / "frozen_final.md", latest)
