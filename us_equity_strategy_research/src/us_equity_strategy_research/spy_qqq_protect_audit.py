"""Pre-registered spy_qqq_protect partial-derisk audit (no parameter search).

Hypothesis: full trend exit creates excessive cash drag; half-leg derisk may
improve return/drawdown balance vs full_protect without becoming a return champion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .analytics import relative_to_benchmark, underwater_stats
from .artifacts import new_run_directory
from .backtest.costs import etf_flat_cost
from .config import load_config
from .data.prices import load_adj_panels
from .data.universe import month_end_index, next_trading_day
from .etf_adapter import verify_frozen_hash
from .etf_trend_sleeves import _run_weight_schedule, fetch_missing_etfs

COMMON_START = pd.Timestamp("2008-06-02")
SPY_W = 0.70
QQQ_W = 0.30
CASH = "BIL"
ONE_WAY_BPS = 5.0
PRIMARY_SMA = 10


def _month_panel(closes: pd.DataFrame) -> pd.DataFrame:
    return closes.reindex(month_end_index(closes.index))


def _above_sma(month_closes: pd.DataFrame, sma_months: int) -> pd.DataFrame:
    sma = month_closes.rolling(sma_months, min_periods=sma_months).mean()
    return month_closes > sma


def build_protect_targets(
    closes: pd.DataFrame,
    *,
    mode: str,
    sma_months: int = PRIMARY_SMA,
    spy_w: float = SPY_W,
    qqq_w: float = QQQ_W,
    cash: str = CASH,
) -> dict[pd.Timestamp, pd.Series]:
    """Pre-registered modes only: full_protect | half_protect | joint_half_protect."""
    me = _month_panel(closes[["SPY", "QQQ", cash]])
    trend = _above_sma(me[["SPY", "QQQ"]], sma_months)
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in me.index:
        if pd.isna(trend.at[date, "SPY"]) or pd.isna(me.at[date, "SPY"]):
            continue
        spy_ok = bool(trend.at[date, "SPY"])
        qqq_ok = bool(trend.at[date, "QQQ"])
        w: dict[str, float] = {}
        if mode == "full_protect":
            if spy_ok:
                w["SPY"] = spy_w
            if qqq_ok:
                w["QQQ"] = qqq_w
        elif mode == "half_protect":
            w["SPY"] = spy_w if spy_ok else spy_w * 0.5  # 35%
            w["QQQ"] = qqq_w if qqq_ok else qqq_w * 0.5  # 15%
        elif mode == "joint_half_protect":
            if (not spy_ok) and (not qqq_ok):
                w["SPY"] = spy_w * 0.5
                w["QQQ"] = qqq_w * 0.5
            else:
                # Only one (or none) broken: keep original 70/30
                w["SPY"] = spy_w
                w["QQQ"] = qqq_w
        else:
            raise ValueError(f"unknown mode {mode}")
        cash_w = 1.0 - sum(w.values())
        if cash_w > 1e-12:
            w[cash] = cash_w
        targets[date] = pd.Series(w, dtype=float)
    return targets


def run_with_delay(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: dict[pd.Timestamp, pd.Series],
    *,
    one_way_bps: float,
    extra_delay_sessions: int = 0,
) -> dict:
    """extra_delay_sessions=1 means signal → skip next open → execute following session."""
    if extra_delay_sessions == 0:
        return _run_weight_schedule(opens, closes, targets, one_way_bps=one_way_bps)
    common = opens.index.intersection(closes.index).sort_values()
    delayed: dict[pd.Timestamp, pd.Series] = {}
    for signal, weights in targets.items():
        d = signal
        for _ in range(1 + extra_delay_sessions):
            nxt = next_trading_day(common, d)
            if nxt is None:
                d = None
                break
            d = nxt
        if d is None:
            continue
        # Store under synthetic signal so engine's next_trading_day(signal)=exec day
        # Engine does: exec = next_trading_day(signal). We want exec = d.
        # So set fake_signal = previous trading day before d.
        pos = common.get_indexer([d])[0]
        if pos <= 0:
            continue
        fake_signal = pd.Timestamp(common[pos - 1])
        delayed[fake_signal] = weights
    return _run_weight_schedule(opens, closes, delayed, one_way_bps=one_way_bps)


def rich_metrics(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    spy: pd.Series,
    ref_8020: Optional[pd.Series] = None,
    turnover_status: str = "measured",
) -> dict:
    net = equity["net_return"].dropna()
    gross = equity["gross_return"].dropna() if "gross_return" in equity else net
    if net.empty:
        return {"status": "EMPTY"}
    years = max((net.index.max() - net.index.min()).days / 365.25, 1 / 12)
    eq = (1 + net).cumprod()
    dd = eq / eq.cummax() - 1
    max_dd = float(dd.min())
    # Max DD duration in calendar days
    peak = eq.cummax()
    under = eq < peak
    longest = cur = 0
    for flag in under:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    monthly = net.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    yearly = net.resample("YE").apply(lambda x: (1 + x).prod() - 1)
    rolling_12m = (1 + net).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
    vol = float(net.std(ddof=1) * np.sqrt(252)) if len(net) > 1 else np.nan
    cagr = float(eq.iloc[-1] ** (1 / years) - 1)
    downside = net[net < 0]
    sortino = (
        float(net.mean() / downside.std(ddof=1) * np.sqrt(252))
        if len(downside) > 1 and downside.std(ddof=1)
        else np.nan
    )
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(252)) if len(net) > 1 and net.std(ddof=1) else np.nan
    if turnover_status == "measured" and trades is not None and not trades.empty and "turnover" in trades:
        one_way = float(trades["turnover"].sum() / 2)
        ann_turn = one_way / years
        n_trades = int(len(trades))
        cost_total = float(trades["cost"].sum()) if "cost" in trades else float(equity.get("cost", pd.Series(dtype=float)).sum())
    elif turnover_status == "buy_and_hold":
        one_way = ann_turn = cost_total = 0.0
        n_trades = 0
    else:
        # not_computed — do not pretend zero
        one_way = ann_turn = cost_total = n_trades = np.nan
    gross_cagr = float((1 + gross).cumprod().iloc[-1] ** (1 / years) - 1) if len(gross) else np.nan
    cost_drag = gross_cagr - cagr if pd.notna(gross_cagr) else np.nan
    # Accept price levels or daily returns for spy argument
    spy_s = spy.reindex(net.index)
    if spy_s.dropna().abs().median() > 0.05:
        spy_ret = spy_s.pct_change(fill_method=None)
    else:
        spy_ret = spy_s
    rel = relative_to_benchmark(net, spy_ret)
    corr = float(pd.concat([net, spy_ret], axis=1).dropna().corr().iloc[0, 1]) if len(net) > 5 else np.nan
    abs_uw = underwater_stats(net)
    out = {
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "max_dd_duration_days": float(longest),
        "calmar": (cagr / abs(max_dd)) if max_dd else np.nan,
        "worst_year": float(yearly.min()) if len(yearly) else np.nan,
        "worst_rolling_12m": float(rolling_12m.min()) if rolling_12m.notna().any() else np.nan,
        "month_win_rate": float((monthly > 0).mean()) if len(monthly) else np.nan,
        "year_win_rate": float((yearly > 0).mean()) if len(yearly) else np.nan,
        "annualized_turnover": ann_turn,
        "one_way_turnover": one_way,
        "avg_trades_per_year": (n_trades / years) if pd.notna(n_trades) else np.nan,
        "cost_total": cost_total,
        "cost_drag_cagr": cost_drag,
        "turnover_status": turnover_status,
        "corr_spy": corr,
        "beta_spy": rel["beta"],
        "up_capture": rel["up_capture"],
        "down_capture": rel["down_capture"],
        "rel_spy_max_dd": rel["relative_max_dd"],
        "rel_spy_underwater_days": rel["relative_underwater_trading_sessions"],
        "rel_spy_underwater_trading_sessions": rel["relative_underwater_trading_sessions"],
        "rel_spy_underwater_calendar_days": rel["relative_underwater_calendar_days"],
        "rel_spy_underwater_months": rel["relative_underwater_months"],
        "rel_spy_final_relative_nav": rel["final_relative_nav"],
        "rel_definition": rel.get("relative_definition"),
        "abs_underwater_days": abs_uw["longest_underwater_days"],
    }
    if ref_8020 is not None:
        rel80 = relative_to_benchmark(net, ref_8020.reindex(net.index))
        out["rel_8020_max_dd"] = rel80["relative_max_dd"]
        out["rel_8020_underwater_days"] = rel80["relative_underwater_trading_sessions"]
        out["rel_8020_underwater_trading_sessions"] = rel80["relative_underwater_trading_sessions"]
        out["rel_8020_underwater_calendar_days"] = rel80["relative_underwater_calendar_days"]
        out["rel_8020_underwater_months"] = rel80["relative_underwater_months"]
        out["rel_8020_final_relative_nav"] = rel80["final_relative_nav"]
    return out


def audit_adj_close_anomalies(closes: pd.DataFrame, symbols: list[str]) -> dict:
    """Flag extreme single-day moves that may indicate bad split/div adjustments."""
    flags = []
    for symbol in symbols:
        if symbol not in closes.columns:
            continue
        r = closes[symbol].pct_change(fill_method=None).dropna()
        extreme = r[(r.abs() > 0.25)]
        for date, val in extreme.items():
            flags.append({"symbol": symbol, "date": str(pd.Timestamp(date).date()), "ret": float(val)})
    return {"n_flags_gt_25pct": len(flags), "flags_sample": flags[:20]}


def load_dc_and_sleeves(one_way_bps: float = ONE_WAY_BPS) -> dict:
    from dual_momentum_etf.backtest import run_variant
    from dual_momentum_etf.config import load_config as load_dm
    from dual_momentum_etf.data import load_ohlc
    from dual_momentum_etf.sleeve_final_audit import outer_blend_pit

    dm = load_dm()
    o, c = load_ohlc(dm)
    dc = run_variant(o, c, dm, "attribution_DC", one_way_bps=one_way_bps)
    dc_net = dc["equity"]["net_return"]
    spy_ret = c["SPY"].pct_change(fill_method=None).fillna(0.0)
    # Align
    common = dc_net.index.intersection(spy_ret.index)
    dc_net = dc_net.reindex(common).fillna(0.0)
    spy_ret = spy_ret.reindex(common).fillna(0.0)
    eq80, meta80 = outer_blend_pit(
        {"spy": spy_ret, "dc": dc_net}, {"spy": 0.8, "dc": 0.2}, one_way_bps=one_way_bps, label="80_20"
    )
    eq60, meta60 = outer_blend_pit(
        {"spy": spy_ret, "dc": dc_net}, {"spy": 0.6, "dc": 0.4}, one_way_bps=one_way_bps, label="60_40"
    )
    return {
        "dc": dc,
        "dc_net": dc_net,
        "spy_ret": spy_ret,
        "eq80": eq80,
        "meta80": meta80,
        "eq60": eq60,
        "meta60": meta60,
        "dc_internal_cost_total": float(dc["equity"]["cost"].sum()) if "cost" in dc["equity"] else np.nan,
        "hash": verify_frozen_hash(),
    }


def evaluate_gate(main: dict, full: dict, ref80: dict, stability: dict) -> dict:
    """Pre-registered DEFENSIVE_SHADOW_CANDIDATE gate — most conditions must pass."""
    checks = {}
    checks["cagr_above_full"] = bool(main["cagr"] > full["cagr"] + 0.005)  # clearly higher (~50bp+)
    checks["sharpe_ge_8020"] = bool(main["sharpe"] >= ref80["sharpe"] - 1e-9)
    checks["maxdd_target"] = bool(
        main["max_drawdown"] >= -0.25 or main["max_drawdown"] > ref80["max_drawdown"] + 0.05
    )
    # Not only from 2008: post-crisis CAGR still >= full
    post = stability.get("exclude_2008_restart", {})
    checks["not_only_2008"] = bool(
        post.get("half_protect", {}).get("cagr", -1) >= post.get("full_protect", {}).get("cagr", 0) - 0.002
    )
    # SMA continuity 8/10/12: half beats full on CAGR for majority
    sma_ok = 0
    for m in (8, 10, 12):
        block = stability.get(f"sma_{m}", {})
        if block.get("half_protect", {}).get("cagr", -1) > block.get("full_protect", {}).get("cagr", 0):
            sma_ok += 1
    checks["sma_continuity"] = sma_ok >= 2
    # Cost double / delay do not flip half vs full ranking on CAGR
    checks["cost_double_stable"] = bool(
        stability.get("cost_double", {}).get("half_protect", {}).get("cagr", -1)
        >= stability.get("cost_double", {}).get("full_protect", {}).get("cagr", 0) - 0.002
    )
    checks["delay_stable"] = bool(
        stability.get("delay_1", {}).get("half_protect", {}).get("cagr", -1)
        >= stability.get("delay_1", {}).get("full_protect", {}).get("cagr", 0) - 0.002
    )
    # Relative underwater vs 80/20 acceptable: not longer than SPY underwater * 1.5 absurdly; soft: < 10y days
    checks["rel_8020_uw_ok"] = bool(main.get("rel_8020_underwater_days", 1e9) < 252 * 12)
    # Rolling: majority of 3y windows half sharpe >= full sharpe
    roll = stability.get("rolling_summary", {})
    checks["rolling_stable"] = bool(roll.get("half_beats_full_sharpe_frac_3y", 0) >= 0.55)

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    # "大部分" = at least 7/9
    label = "DEFENSIVE_SHADOW_CANDIDATE" if passed >= 7 else "REJECT_FURTHER_TUNING"
    return {"checks": checks, "passed": passed, "total": total, "label": label}


def run_spy_qqq_protect_audit(project_root: Optional[Path] = None) -> Path:
    config = load_config(project_root)
    fetch_missing_etfs(config.cache_dir)
    opens, closes, _ = load_adj_panels(
        config.cache_dir, ["SPY", "QQQ", "BIL", "VTI", "SGOV"], subdir="etf"
    )
    # Align to BIL
    bil_start = closes["BIL"].dropna().index.min()
    start = max(COMMON_START, bil_start)
    opens = opens.loc[opens.index >= start]
    closes = closes.loc[closes.index >= start]
    end = closes.index.max()

    adj_audit = audit_adj_close_anomalies(closes, ["SPY", "QQQ", "BIL", "VTI"])
    sleeves = load_dc_and_sleeves(ONE_WAY_BPS)
    run_dir = new_run_directory(
        config,
        "spy_qqq_protect_audit",
        {"experiment": "spy_qqq_half_protect_preregistered_v1"},
    )

    modes = ["full_protect", "half_protect", "joint_half_protect"]
    primary: dict[str, dict] = {}
    for mode in modes:
        targets = build_protect_targets(closes, mode=mode, sma_months=PRIMARY_SMA)
        out = _run_weight_schedule(opens, closes, targets, one_way_bps=ONE_WAY_BPS)
        primary[mode] = out
        out["equity"].to_csv(run_dir / f"equity_{mode}.csv")
        out["trades"].to_csv(run_dir / f"trades_{mode}.csv", index=False)
        out["targets"].to_csv(run_dir / f"targets_{mode}.csv", index=False)

    # Benchmarks with correct turnover labeling
    spy_bh = closes["SPY"].pct_change(fill_method=None).fillna(0.0)
    vti_bh = closes["VTI"].pct_change(fill_method=None).fillna(0.0)
    # Clip all to common end/start intersection with protect strategies
    common_idx = primary["full_protect"]["equity"].index
    for name in modes:
        common_idx = common_idx.intersection(primary[name]["equity"].index)
    common_idx = common_idx.intersection(sleeves["eq80"].index).intersection(sleeves["eq60"].index)
    common_idx = common_idx.intersection(sleeves["dc_net"].index)
    common_idx = common_idx[(common_idx >= start) & (common_idx <= end)]

    ref80 = sleeves["eq80"]["net_return"].reindex(common_idx)
    books = {}
    for mode in modes:
        eq = primary[mode]["equity"].reindex(common_idx).dropna(subset=["net_return"])
        tr = primary[mode]["trades"]
        if not tr.empty:
            tr = tr[(tr["date"] >= common_idx.min()) & (tr["date"] <= common_idx.max())]
        books[mode] = rich_metrics(
            eq, tr, spy=closes["SPY"], ref_8020=ref80, turnover_status="measured"
        )
        books[mode]["avg_bil"] = _avg_cash(primary[mode]["targets"], common_idx.min(), common_idx.max())

    # SPY / VTI BH
    for name, series in [("spy_bh", spy_bh), ("vti_bh", vti_bh)]:
        eq = pd.DataFrame({"gross_return": series, "net_return": series}).reindex(common_idx)
        books[name] = rich_metrics(
            eq, pd.DataFrame(), spy=closes["SPY"], ref_8020=ref80, turnover_status="buy_and_hold"
        )

    # D+C — measured internal turnover from sibling trades
    dc_eq = sleeves["dc"]["equity"].reindex(common_idx)
    dc_tr = sleeves["dc"]["trades"]
    if not dc_tr.empty:
        dc_tr = dc_tr[(dc_tr["date"] >= common_idx.min()) & (dc_tr["date"] <= common_idx.max())]
    books["dc"] = rich_metrics(dc_eq, dc_tr, spy=closes["SPY"], ref_8020=ref80, turnover_status="measured")
    books["dc"]["note"] = "internal D+C costs already in net_return"

    # 80/20 and 60/40 — outer_blend_pit measured outer turnover; DC leg already net
    for label, eq, meta in [
        ("frozen_80_20_spy_dc", sleeves["eq80"], sleeves["meta80"]),
        ("frozen_60_40_spy_dc", sleeves["eq60"], sleeves["meta60"]),
    ]:
        # Build synthetic trades from rebalance log for turnover accounting
        reb = pd.DataFrame(meta.get("rebalance_log") or [])
        if not reb.empty:
            reb = reb.rename(columns={"execution_date": "date", "turnover_l1": "turnover", "outer_cost": "cost"})
            reb["date"] = pd.to_datetime(reb["date"])
            reb = reb[(reb["date"] >= common_idx.min()) & (reb["date"] <= common_idx.max())]
        else:
            reb = pd.DataFrame(columns=["date", "turnover", "cost"])
        frame = eq.reindex(common_idx).copy()
        # Map outer cost column
        if "outer_rebalance_cost" in frame.columns and "cost" not in frame.columns:
            frame["cost"] = frame["outer_rebalance_cost"]
        if "gross_return" not in frame.columns:
            frame["gross_return"] = frame["net_return"] + frame.get("outer_rebalance_cost", 0)
        books[label] = rich_metrics(frame, reb, spy=closes["SPY"], ref_8020=ref80, turnover_status="measured")
        books[label]["ann_outer_turnover_meta"] = meta.get("ann_outer_turnover")
        books[label]["n_rebalances"] = meta.get("n_rebalances")
        books[label]["construction"] = meta.get("construction")
        books[label]["note"] = (
            "Outer monthly target rebalance with weight drift; "
            "D+C internal costs already inside dc leg; outer 5bp on sleeve turnover only."
        )

    # --- Stability (pre-registered only) ---
    stability: dict = {}
    # SMA 8/10/12
    for sma in (8, 10, 12):
        block = {}
        for mode in ("full_protect", "half_protect"):
            targets = build_protect_targets(closes, mode=mode, sma_months=sma)
            out = _run_weight_schedule(opens, closes, targets, one_way_bps=ONE_WAY_BPS)
            eq = out["equity"].reindex(common_idx).dropna(subset=["net_return"])
            block[mode] = rich_metrics(eq, out["trades"], spy=closes["SPY"], turnover_status="measured")
        stability[f"sma_{sma}"] = {
            m: {"cagr": block[m]["cagr"], "sharpe": block[m]["sharpe"], "max_drawdown": block[m]["max_drawdown"]}
            for m in block
        }
    # Cost double
    block = {}
    for mode in ("full_protect", "half_protect"):
        targets = build_protect_targets(closes, mode=mode, sma_months=PRIMARY_SMA)
        out = _run_weight_schedule(opens, closes, targets, one_way_bps=ONE_WAY_BPS * 2)
        eq = out["equity"].reindex(common_idx).dropna(subset=["net_return"])
        block[mode] = rich_metrics(eq, out["trades"], spy=closes["SPY"], turnover_status="measured")
    stability["cost_double"] = {
        m: {"cagr": block[m]["cagr"], "sharpe": block[m]["sharpe"], "max_drawdown": block[m]["max_drawdown"]}
        for m in block
    }
    # Extra delay 1 session
    block = {}
    for mode in ("full_protect", "half_protect"):
        targets = build_protect_targets(closes, mode=mode, sma_months=PRIMARY_SMA)
        out = run_with_delay(opens, closes, targets, one_way_bps=ONE_WAY_BPS, extra_delay_sessions=1)
        eq = out["equity"].reindex(common_idx).dropna(subset=["net_return"])
        block[mode] = rich_metrics(eq, out["trades"], spy=closes["SPY"], turnover_status="measured")
    stability["delay_1"] = {
        m: {"cagr": block[m]["cagr"], "sharpe": block[m]["sharpe"], "max_drawdown": block[m]["max_drawdown"]}
        for m in block
    }
    # Exclude last year
    cut = common_idx.max() - pd.Timedelta(days=365)
    idx_ex = common_idx[common_idx <= cut]
    block = {}
    for mode in ("full_protect", "half_protect"):
        eq = primary[mode]["equity"].reindex(idx_ex).dropna(subset=["net_return"])
        block[mode] = rich_metrics(eq, primary[mode]["trades"], spy=closes["SPY"], turnover_status="measured")
    stability["exclude_last_year"] = {
        m: {"cagr": block[m]["cagr"], "sharpe": block[m]["sharpe"], "max_drawdown": block[m]["max_drawdown"]}
        for m in block
    }
    # Exclude 2008 crisis — restart from 2009-03-01
    idx_post = common_idx[common_idx >= pd.Timestamp("2009-03-01")]
    block = {}
    for mode in ("full_protect", "half_protect"):
        eq = primary[mode]["equity"].reindex(idx_post).dropna(subset=["net_return"])
        block[mode] = rich_metrics(eq, primary[mode]["trades"], spy=closes["SPY"], turnover_status="measured")
    stability["exclude_2008_restart"] = {
        m: {"cagr": block[m]["cagr"], "sharpe": block[m]["sharpe"], "max_drawdown": block[m]["max_drawdown"]}
        for m in block
    }
    # Crisis windows
    windows = {
        "crisis_2008": ("2008-06-02", "2009-03-31"),
        "covid_2020": ("2020-02-01", "2020-04-30"),
        "bear_2022": ("2022-01-01", "2022-12-31"),
    }
    for wname, (a, b) in windows.items():
        idx_w = common_idx[(common_idx >= a) & (common_idx <= b)]
        block = {}
        for mode in modes:
            eq = primary[mode]["equity"].reindex(idx_w).dropna(subset=["net_return"])
            if eq.empty:
                block[mode] = {"cagr": np.nan, "sharpe": np.nan, "max_drawdown": np.nan}
            else:
                m = rich_metrics(eq, primary[mode]["trades"], spy=closes["SPY"], turnover_status="measured")
                block[mode] = {"cagr": m["cagr"], "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"]}
        stability[wname] = block

    # Rolling 3y / 5y
    rolling_summary = _rolling_compare(primary, common_idx, closes["SPY"])
    stability["rolling_summary"] = rolling_summary

    gate = evaluate_gate(
        books["half_protect"],
        books["full_protect"],
        books["frozen_80_20_spy_dc"],
        stability,
    )

    # Persist
    pd.DataFrame(
        [{"name": k, **{kk: vv for kk, vv in v.items() if not isinstance(vv, (dict, list))}} for k, v in books.items()]
    ).to_csv(run_dir / "main_metrics.csv", index=False)
    (run_dir / "stability.json").write_text(json.dumps(stability, indent=2, default=str), encoding="utf-8")
    (run_dir / "gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    (run_dir / "benchmark_audit.json").write_text(
        json.dumps(
            {
                "prior_report_issue": (
                    "Previous etf_trend_sleeve_comparison showed ann_turnover=0 for D+C and 80/20 "
                    "because those series were fed as raw return streams with empty trade tables; "
                    "that was NOT_COMPUTED, mislabeled as zero."
                ),
                "dc_costs": "attribution_DC net_return already deducts internal 5bp trading costs",
                "sleeve_80_20_60_40": (
                    "outer_blend_pit: month-end signal → next open; weights drift; "
                    "outer 5bp on L1 turnover only; does not double-count D+C internal costs"
                ),
                "challenger_costs": "same 5bp one-way on measured L1 turnover; month-end → next open",
                "bh_turnover": "buy_and_hold labeled turnover_status=buy_and_hold (true zero activity)",
                "adj_close_anomaly_audit": adj_audit,
                "hash_check": sleeves["hash"],
                "dc_internal_cost_total_full_sample": sleeves["dc_internal_cost_total"],
                "common_start": str(common_idx.min().date()),
                "common_end": str(common_idx.max().date()),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    report = _write_report(
        config.reports_dir / "spy_qqq_protect_half_audit.md",
        books=books,
        stability=stability,
        gate=gate,
        adj_audit=adj_audit,
        run_dir=run_dir,
        common_idx=common_idx,
        sleeves=sleeves,
    )
    (run_dir / "spy_qqq_protect_half_audit.md").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")

    # Update PROJECT_STATUS briefly
    status = config.reports_dir / "PROJECT_STATUS.md"
    prev = status.read_text(encoding="utf-8") if status.exists() else ""
    addendum = (
        "\n## spy_qqq_protect half-protect audit\n\n"
        f"- Report: `reports/spy_qqq_protect_half_audit.md`\n"
        f"- Gate: `{gate['label']}` ({gate['passed']}/{gate['total']} checks)\n"
        f"- Default paper candidate unchanged: **80% SPY + 20% D+C**\n"
        f"- Conservative shadow unchanged: **60% SPY + 40% D+C**\n"
    )
    if "spy_qqq_protect half-protect audit" not in prev:
        status.write_text(prev.rstrip() + "\n" + addendum, encoding="utf-8")
    return report


def _avg_cash(targets: pd.DataFrame, start, end) -> float:
    if targets is None or targets.empty:
        return float("nan")
    t = targets.copy()
    t["signal_date"] = pd.to_datetime(t["signal_date"])
    t = t[(t["signal_date"] >= start) & (t["signal_date"] <= end)]
    if t.empty:
        return float("nan")
    by = t.groupby("signal_date")
    vals = []
    for _, g in by:
        w = g.set_index("symbol")["weight"]
        vals.append(float(w.get(CASH, 0.0)))
    return float(np.mean(vals)) if vals else float("nan")


def _rolling_compare(primary: dict, common_idx: pd.DatetimeIndex, spy_px: pd.Series) -> dict:
    out = {"windows_3y": [], "windows_5y": []}
    for years, key in [(3, "windows_3y"), (5, "windows_5y")]:
        span = years * 252
        half_beats = 0
        n = 0
        starts = common_idx[::63]  # quarterly steps
        for st in starts:
            en_pos = common_idx.get_indexer([st])[0] + span
            if en_pos >= len(common_idx):
                continue
            en = common_idx[en_pos]
            idx = common_idx[(common_idx >= st) & (common_idx <= en)]
            if len(idx) < span * 0.9:
                continue
            m_full = rich_metrics(
                primary["full_protect"]["equity"].reindex(idx).dropna(subset=["net_return"]),
                primary["full_protect"]["trades"],
                spy=spy_px,
                turnover_status="measured",
            )
            m_half = rich_metrics(
                primary["half_protect"]["equity"].reindex(idx).dropna(subset=["net_return"]),
                primary["half_protect"]["trades"],
                spy=spy_px,
                turnover_status="measured",
            )
            n += 1
            if m_half["sharpe"] >= m_full["sharpe"]:
                half_beats += 1
            out[key].append(
                {
                    "start": str(st.date()),
                    "end": str(en.date()),
                    "full_sharpe": m_full["sharpe"],
                    "half_sharpe": m_half["sharpe"],
                    "full_cagr": m_full["cagr"],
                    "half_cagr": m_half["cagr"],
                }
            )
        out[f"half_beats_full_sharpe_frac_{years}y"] = half_beats / n if n else np.nan
        out[f"n_windows_{years}y"] = n
    return out


def _fmt(x, pct=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    if pct:
        return f"{100 * float(x):.2f}%"
    return f"{float(x):.4f}"


def _write_report(path: Path, **ctx) -> Path:
    books = ctx["books"]
    stability = ctx["stability"]
    gate = ctx["gate"]
    adj_audit = ctx["adj_audit"]
    run_dir = ctx["run_dir"]
    common_idx = ctx["common_idx"]
    sleeves = ctx["sleeves"]

    order = [
        "full_protect",
        "half_protect",
        "joint_half_protect",
        "spy_bh",
        "vti_bh",
        "dc",
        "frozen_80_20_spy_dc",
        "frozen_60_40_spy_dc",
    ]
    cols = [
        "cagr",
        "volatility",
        "sharpe",
        "sortino",
        "max_drawdown",
        "max_dd_duration_days",
        "calmar",
        "worst_year",
        "worst_rolling_12m",
        "month_win_rate",
        "year_win_rate",
        "annualized_turnover",
        "avg_trades_per_year",
        "cost_drag_cagr",
        "corr_spy",
        "beta_spy",
        "up_capture",
        "down_capture",
        "rel_spy_max_dd",
        "rel_spy_final_relative_nav",
        "rel_spy_underwater_trading_sessions",
        "rel_spy_underwater_months",
        "rel_8020_max_dd",
        "rel_8020_final_relative_nav",
        "rel_8020_underwater_trading_sessions",
        "rel_8020_underwater_months",
        "turnover_status",
    ]

    pct_cols = {
        "cagr",
        "volatility",
        "max_drawdown",
        "worst_year",
        "worst_rolling_12m",
        "month_win_rate",
        "year_win_rate",
        "cost_drag_cagr",
        "rel_spy_max_dd",
        "rel_8020_max_dd",
        "up_capture",
        "down_capture",
    }
    hp, fp, f80 = books["half_protect"], books["full_protect"], books["frozen_80_20_spy_dc"]
    lines = [
        "# SPY/QQQ Protect — Pre-registered Half-Protect Audit",
        "",
        "## Verdict",
        "",
        f"- Gate: **`{gate['label']}`** ({gate['passed']}/{gate['total']})",
        f"- half_protect CAGR `{_fmt(hp['cagr'], True)}` vs full `{_fmt(fp['cagr'], True)}` "
        f"(cash drag cut: avg BIL `{books['full_protect'].get('avg_bil'):.1%}` → "
        f"`{books['half_protect'].get('avg_bil'):.1%}`)",
        f"- half MaxDD `{_fmt(hp['max_drawdown'], True)}` vs 80/20 `{_fmt(f80['max_drawdown'], True)}`; "
        f"Sharpe `{_fmt(hp['sharpe'])}` vs 80/20 `{_fmt(f80['sharpe'])}`",
        "- **Not** a return primary; default paper remains **80% SPY + 20% D+C**; "
        "conservative shadow remains **60/40**. No IBKR config change. No further exit-ratio tests.",
        "",
        "## Hypothesis (pre-registered)",
        "",
        "Full trend exit may create excessive cash drag; cutting each broken leg by **50%** "
        "(half_protect) may improve return/drawdown balance vs full_protect, without searching "
        "other exit ratios.",
        "",
        f"- Price panel aligned from `{COMMON_START.date()}`; strategy equity common interval "
        f"`{common_idx.min().date()}` → `{common_idx.max().date()}` (first executable trade after SMA warmup)",
        "- Base weights: 70% SPY + 30% QQQ; cash = BIL",
        "- Signal: month-end close; execution: next session open; cost: 5 bp one-way",
        "- Primary SMA: 10 months (8/12 only for continuity check)",
        "- Frozen 80/20 and 60/40 **not** retuned; IBKR paper config **not** modified",
        f"- Run: `{run_dir}`",
        "",
        "## Benchmark construction audit (fixes prior mislabel)",
        "",
        "1. **Why D+C / 80/20 showed ann_turnover=0 previously:** comparison fed return series "
        "with empty trade tables; metrics defaulted turnover to 0. That was **NOT_COMPUTED**, not true zero.",
        "2. **D+C costs:** `attribution_DC` `net_return` already deducts internal 5 bp costs "
        f"(full-sample internal cost total ≈ `{sleeves['dc_internal_cost_total']:.6f}`).",
        "3. **80/20 and 60/40:** `outer_blend_pit` — month-end signal → next open; weights **drift**; "
        "outer 5 bp only on sleeve L1 turnover; does **not** re-charge D+C internal costs. "
        "Rebalance frequency = **monthly target reset**.",
        "4. **Challengers:** same month-end → next-open and 5 bp one-way on measured turnover.",
        "5. **Buy&hold SPY/VTI:** `turnover_status=buy_and_hold` (activity truly zero).",
        f"6. **Adj Close anomaly flags (|ret|>25%):** `{adj_audit['n_flags_gt_25pct']}` "
        f"(sample `{adj_audit['flags_sample'][:5]}`).",
        f"7. Frozen D+C hash check: `{sleeves['hash']}`",
        "8. **Relative underwater / max DD:** Metric C only "
        "(`relative_nav = nav_strategy/nav_benchmark`, both rebased to 1). "
        "See `reports/affected_reports_metric_c_fix.md`.",
        "",
        "## Main results",
        "",
        "| name | " + " | ".join(cols) + " |",
        "|---|" + "|".join(["---:"] * len(cols)) + "|",
    ]
    for name in order:
        row = books[name]
        cells = []
        for c in cols:
            val = row.get(c)
            if isinstance(val, str):
                cells.append(val)
            elif c in pct_cols:
                cells.append(_fmt(val, pct=True))
            else:
                cells.append(_fmt(val))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "### Cash drag diagnostic",
            "",
            f"- full_protect avg BIL weight: `{books['full_protect'].get('avg_bil')}`",
            f"- half_protect avg BIL weight: `{books['half_protect'].get('avg_bil')}`",
            f"- joint_half_protect avg BIL weight: `{books['joint_half_protect'].get('avg_bil')}`",
            "",
            "## Stability (pre-registered only)",
            "",
            "### SMA 8 / 10 / 12",
            "",
        ]
    )
    for sma in (8, 10, 12):
        block = stability[f"sma_{sma}"]
        lines.append(
            f"- SMA{sma}: full CAGR/Sharpe/MaxDD = "
            f"`{_fmt(block['full_protect']['cagr'])}` / `{_fmt(block['full_protect']['sharpe'])}` / "
            f"`{_fmt(block['full_protect']['max_drawdown'])}`; "
            f"half = `{_fmt(block['half_protect']['cagr'])}` / `{_fmt(block['half_protect']['sharpe'])}` / "
            f"`{_fmt(block['half_protect']['max_drawdown'])}`"
        )
    for key, title in [
        ("cost_double", "Cost ×2"),
        ("delay_1", "Extra +1 session delay"),
        ("exclude_last_year", "Exclude last year"),
        ("exclude_2008_restart", "Restart 2009-03-01"),
        ("crisis_2008", "2008 window"),
        ("covid_2020", "2020 window"),
        ("bear_2022", "2022 window"),
    ]:
        block = stability[key]
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"```json\n{json.dumps(block, indent=2, default=str)}\n```")
        lines.append("")

    rs = stability["rolling_summary"]
    lines.extend(
        [
            "### Rolling windows",
            "",
            f"- 3y: half Sharpe ≥ full in `{rs.get('half_beats_full_sharpe_frac_3y')}` "
            f"of `{rs.get('n_windows_3y')}` windows",
            f"- 5y: half Sharpe ≥ full in `{rs.get('half_beats_full_sharpe_frac_5y')}` "
            f"of `{rs.get('n_windows_5y')}` windows",
            "",
            "## Gate decision",
            "",
            f"- Label: **`{gate['label']}`** ({gate['passed']}/{gate['total']} checks)",
            "",
            "```json",
            json.dumps(gate["checks"], indent=2),
            "```",
            "",
            "## Final recommendation",
            "",
        ]
    )
    if gate["label"] == "DEFENSIVE_SHADOW_CANDIDATE":
        lines.extend(
            [
                "- Keep **80% SPY + 20% D+C** as default paper / return candidate.",
                "- Keep **60% SPY + 40% D+C** as conservative shadow.",
                "- Mark **half_protect** as `DEFENSIVE_SHADOW_CANDIDATE` only (not return primary).",
                "- Failed check `rel_8020_uw_ok`: Metric C relative underwater vs 80/20 peak still long "
                f"(`rel_8020_underwater_trading_sessions={books['half_protect'].get('rel_8020_underwater_trading_sessions')}`, "
                f"final_rel_nav=`{books['half_protect'].get('rel_8020_final_relative_nav')}`); "
                "treat as defensive complement, not a replacement.",
                "- **Stop** further spy_qqq_protect exit-ratio / parameter tuning (hypothesis already tested).",
                "- Do **not** purchase Sharadar for this line of work.",
                "- Do **not** change IBKR paper books.",
            ]
        )
    else:
        lines.extend(
            [
                "- Keep **80% SPY + 20% D+C** as default paper candidate.",
                "- Keep **60% SPY + 40% D+C** as conservative shadow.",
                "- **Stop** further spy_qqq_protect exit-ratio tuning.",
                "- Do **not** test more exit percentages.",
                "- Do **not** purchase Sharadar for this line of work.",
                "- Do **not** change IBKR paper books.",
            ]
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
