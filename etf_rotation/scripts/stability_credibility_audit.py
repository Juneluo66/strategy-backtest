#!/usr/bin/env python3
"""Time-stability and statistical-credibility audit (frozen params; no retune)."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.backtest import metrics, variant_config, vector_backtest
from etf_rotation.config import frozen_config, strategy_definition
from etf_rotation.data import build_pit_universe, cached_prices, universe_definition
from etf_rotation.factors import classify_missing_reasons, cross_sectional_scores, factor_panel
from etf_rotation.non_ohlcv.absence import absence_kind_notes, load_margin_absence_kinds
from etf_rotation.non_ohlcv.loader import load_non_ohlcv_sources
from etf_rotation.strategy import rebalance_dates

OUT = Path("/home/ec2-user/strategy-backtest/etf_rotation/reports/stability_audit")
OUT.mkdir(parents=True, exist_ok=True)
RNG = np.random.default_rng(42)
N_BOOT = 400
BLOCK = 5  # ≈ rebalance frequency


def _ann_years(n_days: int) -> float:
    return n_days / 252.0 if n_days else np.nan


def summarize_equity(equity: pd.DataFrame, config) -> dict:
    if equity is None or equity.empty:
        return {k: np.nan for k in (
            "sample_years", "n_days", "n_rebalances", "annual_return", "sharpe",
            "max_drawdown", "turnover", "total_fees", "cand_mean", "cand_median",
            "cand_p10", "cand_p90", "cand_min", "cand_max",
        )}
    eq = equity.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    m = metrics(eq["return"])
    n_days = int(len(eq))
    # Approximate rebalance count from turnover spikes or frequency grid
    n_reb = max(1, int(np.ceil(n_days / config.frequency)))
    turn = float(eq["turnover"].sum()) if "turnover" in eq else np.nan
    return {
        "sample_years": round(_ann_years(n_days), 2),
        "n_days": n_days,
        "n_rebalances_approx": n_reb,
        "annual_return": m["annual_return"],
        "sharpe": m["sharpe"],
        "max_drawdown": m["max_drawdown"],
        "turnover": turn,
        "total_fees": turn * config.commission_a_share if np.isfinite(turn) else np.nan,
    }


def cand_stats(series: pd.Series) -> dict:
    if series is None or series.empty:
        return {k: np.nan for k in ("cand_mean", "cand_median", "cand_p10", "cand_p90", "cand_min", "cand_max")}
    return {
        "cand_mean": float(series.mean()),
        "cand_median": float(series.median()),
        "cand_p10": float(series.quantile(0.1)),
        "cand_p90": float(series.quantile(0.9)),
        "cand_min": float(series.min()),
        "cand_max": float(series.max()),
    }


def block_bootstrap_metrics(returns: pd.Series, n_boot: int = N_BOOT, block: int = BLOCK) -> dict:
    r = pd.to_numeric(returns, errors="coerce").dropna().to_numpy()
    n = len(r)
    if n < block * 3:
        return {"n": n, "ann_ci": [np.nan, np.nan], "sharpe_ci": [np.nan, np.nan],
                "ann_mean": np.nan, "sharpe_mean": np.nan}
    n_blocks = int(np.ceil(n / block))
    anns, sharpes = [], []
    for _ in range(n_boot):
        starts = RNG.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:n]
        nav = np.cumprod(1 + sample)
        ann = float(nav[-1] ** (252 / n) - 1)
        vol = float(np.std(sample, ddof=1) * np.sqrt(252)) if n > 1 else np.nan
        sharpe = ann / vol if vol and np.isfinite(vol) else np.nan
        anns.append(ann)
        sharpes.append(sharpe)
    return {
        "n": n,
        "ann_mean": float(np.nanmean(anns)),
        "ann_ci": [float(np.nanpercentile(anns, 2.5)), float(np.nanpercentile(anns, 97.5))],
        "sharpe_mean": float(np.nanmean(sharpes)),
        "sharpe_ci": [float(np.nanpercentile(sharpes, 2.5)), float(np.nanpercentile(sharpes, 97.5))],
    }


def block_bootstrap_active(active: pd.Series, n_boot: int = N_BOOT, block: int = BLOCK) -> dict:
    r = pd.to_numeric(active, errors="coerce").dropna().to_numpy()
    n = len(r)
    if n < block * 3:
        return {"n": n, "active_ann_ci": [np.nan, np.nan], "p_active_ann_positive": np.nan,
                "active_ann_mean": np.nan}
    n_blocks = int(np.ceil(n / block))
    anns = []
    for _ in range(n_boot):
        starts = RNG.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:n]
        anns.append(float(np.mean(sample) * 252))
    anns = np.asarray(anns)
    return {
        "n": n,
        "active_ann_mean": float(np.nanmean(anns)),
        "active_ann_ci": [float(np.nanpercentile(anns, 2.5)), float(np.nanpercentile(anns, 97.5))],
        "p_active_ann_positive": float(np.mean(anns > 0)),
    }


def period_returns(equity: pd.DataFrame, freq: int) -> pd.Series:
    eq = equity.sort_values("date").copy()
    eq["date"] = pd.to_datetime(eq["date"])
    out = []
    idx = []
    for i in range(0, max(0, len(eq) - freq + 1), freq):
        chunk = eq.iloc[i:i + freq]
        out.append(float((1 + chunk["return"]).prod() - 1))
        idx.append(chunk["date"].iloc[-1])
    return pd.Series(out, index=pd.DatetimeIndex(idx), name="period_ret")


def longest_negative_streak(flags_positive: list[bool]) -> int:
    worst = cur = 0
    for ok in flags_positive:
        if ok:
            cur = 0
        else:
            cur += 1
            worst = max(worst, cur)
    return worst


def first_median_threshold_start(cand_by_reb: pd.Series, threshold: int) -> pd.Timestamp | None:
    """First date after a trailing ~1y window whose rebalance-candidate median >= threshold."""
    s = cand_by_reb.dropna().sort_index()
    if s.empty:
        return None
    dates = s.index
    for i, dt in enumerate(dates):
        start = dt - pd.Timedelta(days=365)
        window = s.loc[(dates >= start) & (dates <= dt)]
        if len(window) < 40:  # ~1y of 5d rebalances
            continue
        if float(window.median()) >= threshold:
            return pd.Timestamp(dt)
    return None


def market_regime(proxy: pd.DataFrame) -> pd.Series:
    """Bull / bear / sideways from 510300 MA120 + MOM60 (PIT via lag-0 close only as of T)."""
    f = proxy.sort_values("date").copy()
    f["date"] = pd.to_datetime(f["date"]).dt.normalize()
    close = f.set_index("date")["close"]
    ma = close.rolling(120).mean()
    mom = close.pct_change(60)
    regime = pd.Series("sideways", index=close.index, dtype=object)
    regime.loc[(close > ma) & (mom > 0)] = "bull"
    regime.loc[(close < ma) & (mom < 0)] = "bear"
    return regime


def score_frame(frame, factors, signs, icirs, sources):
    scored, _ = cross_sectional_scores(
        frame, factors, signs, icirs, run_mode="research", sources=sources
    )
    return scored


def run_bt(scores, prices, cfg):
    result = vector_backtest(scores, prices, cfg)
    equity = result["equity"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    targets = result["targets"].copy()
    return equity, targets, result


def slice_equity(equity: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    out = equity
    if start is not None:
        out = out.loc[out["date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out.loc[out["date"] <= pd.Timestamp(end)]
    return out.copy()


def main() -> None:
    config = frozen_config()
    prices = cached_prices(config)
    definition = universe_definition(config)
    sources = load_non_ohlcv_sources(config)
    panel = factor_panel(prices, config, sources=sources)
    pit = build_pit_universe(prices, definition, config.lookback)
    listing = {c: pd.to_datetime(f["date"]).min() for c, f in prices.items()}
    cfg_r1 = variant_config(config, "R1")
    cfg_c1 = variant_config(config, "C1")

    raw_dir = sorted((Path(config.cache_dir) / "non_ohlcv" / "raw").glob("*"))[-1]
    absence_kinds = load_margin_absence_kinds(raw_dir)

    # Extra OHLCV factors for baselines
    parts = []
    for code, frame in prices.items():
        f = frame.sort_values("date").copy()
        f["MOM_252D"] = f["close"].pct_change(252)
        f["ret_1d"] = f["close"].pct_change()
        f["vol_20d"] = f["ret_1d"].rolling(20).std()
        f["turnover_proxy"] = f["volume"] / f["volume"].rolling(20).mean()
        # Amihud-like illiquidity (liquidity inverse)
        f["amihud"] = f["ret_1d"].abs() / f["amount"].replace(0, np.nan)
        parts.append(f[["date", "code", "MOM_252D", "vol_20d", "turnover_proxy", "amihud", "volume"]])
    extra = pd.concat(parts, ignore_index=True)
    extra["date"] = pd.to_datetime(extra["date"]).dt.normalize()
    extra["code"] = extra["code"].astype(str).str.zfill(6)
    panel = panel.merge(extra, on=["date", "code"], how="left")

    # PIT share → AUM proxy = total_share * close (only when share available_at <= date via staging merge)
    share_raw = pd.read_parquet(raw_dir / "total_share.parquet")
    share_raw["observation_date"] = pd.to_datetime(share_raw["observation_date"]).dt.normalize()
    share_raw["available_at"] = pd.to_datetime(share_raw["available_at"]).dt.normalize()
    share_raw["code"] = share_raw["code"].astype(str).str.zfill(6)
    # As-of merge: for each panel date, last available share
    panel = panel.sort_values(["code", "date"])
    aum_rows = []
    for code, g in panel.groupby("code", sort=False):
        sh = share_raw.loc[share_raw.code.eq(code), ["available_at", "value"]].sort_values("available_at")
        if sh.empty:
            continue
        merged = pd.merge_asof(
            g[["date", "code", "close"]].sort_values("date"),
            sh.rename(columns={"available_at": "date", "value": "total_share"}),
            on="date",
            direction="backward",
        )
        merged["aum_proxy"] = merged["total_share"] * merged["close"]
        aum_rows.append(merged[["date", "code", "aum_proxy", "total_share"]])
    if aum_rows:
        aum = pd.concat(aum_rows, ignore_index=True)
        panel = panel.merge(aum, on=["date", "code"], how="left")
    else:
        panel["aum_proxy"] = np.nan
        panel["total_share"] = np.nan

    qdii = set(str(c).zfill(6) for c in (definition.get("qdii") if False else []))
    # universe yaml structure
    uni = definition if isinstance(definition, pd.DataFrame) else None
    qdii_codes = set()
    try:
        import yaml
        raw_uni = yaml.safe_load((config.project_root / "configs" / "etf_universe.yaml").read_text())
        qdii_codes = {str(c).zfill(6) for c in raw_uni.get("universe", {}).get("qdii", [])}
    except Exception:
        qdii_codes = set()
    panel["is_qdii"] = panel["code"].isin(qdii_codes).astype(float)
    panel["listing_age_days"] = (
        pd.to_datetime(panel["date"]) - panel["code"].map(listing)
    ).dt.days
    panel["log_amount"] = np.log1p(panel["amount"].clip(lower=0))
    panel["log_aum"] = np.log1p(panel["aum_proxy"].clip(lower=0))
    panel["margin_eligible_flag"] = panel["MARGIN_BUY_RATIO"].notna().astype(float)

    panel2 = panel.merge(pit[["date", "code", "eligible"]], on=["date", "code"], how="left")
    panel2 = panel2.loc[panel2.eligible.fillna(False)].copy()
    panel2["margin_pool"] = panel2["MARGIN_BUY_RATIO"].notna() & panel2["MARGIN_CHG_10D"].notna()

    # Candidate counts on rebalance dates (margin-pool complete scores for ranking size)
    base_dates = pd.DatetimeIndex(sorted(pd.to_datetime(panel2["date"]).unique()))
    reb = rebalance_dates(base_dates, config.frequency)
    pool_counts = (
        panel2.loc[panel2.margin_pool & panel2["date"].isin(reb)]
        .groupby("date")["code"].nunique()
        .rename("n_margin_pool")
    )
    # Also C1-complete ranked count for context
    c1_f, c1_s, c1_i = strategy_definition(config, "composite_1")
    c1_full = score_frame(panel2, c1_f, c1_s, c1_i, sources)
    ranked_counts = (
        c1_full.loc[c1_full["score"].notna() & c1_full["date"].isin(reb)]
        .groupby("date")["code"].nunique()
        .rename("n_ranked_c1")
    )
    cand_for_threshold = ranked_counts  # matches prior audit median=4 story
    start_med10 = first_median_threshold_start(cand_for_threshold, 10)
    start_med20 = first_median_threshold_start(cand_for_threshold, 20)

    windows = {
        "full_original": (None, None),
        "after_med10_1y": (start_med10, None),
        "after_med20_1y": (start_med20, None),
        "from_2020": (pd.Timestamp("2020-01-01"), None),
        "from_2022": (pd.Timestamp("2022-01-01"), None),
        "frozen_oos": (pd.Timestamp(config.oos_start), None),
    }

    # Build strategy score panels once
    restricted = panel2.loc[panel2.margin_pool].copy()
    strategies = {
        "MOM_12m": (panel2, ["MOM_252D"], [1.0], [1.0], cfg_r1, False),
        "equal_weight_pool": (panel2, None, None, None, replace(cfg_r1, use_hysteresis=False), True),
        "mom_plus_shares": (
            panel2, ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D"],
            [1, -1, -1], [1, 2.306, 1.807], cfg_r1, False,
        ),
        "restricted_mom_shares": (
            restricted, ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D"],
            [1, -1, -1], [1, 2.306, 1.807], cfg_r1, False,
        ),
        "restricted_mom_shares_mbr": (
            restricted, ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO"],
            [1, -1, -1, -1], [1, 2.306, 1.807, 5.101], cfg_r1, False,
        ),
        "restricted_mom_shares_both_m": (
            restricted,
            ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO", "MARGIN_CHG_10D"],
            [1, -1, -1, -1, -1], [1, 2.306, 1.807, 5.101, 3.387], cfg_r1, False,
        ),
        "C1_research_partial": (panel2, c1_f, c1_s, c1_i, cfg_c1, False),
    }

    scored: dict[str, pd.DataFrame] = {}
    for name, (frame, factors, signs, icirs, cfg, is_ew) in strategies.items():
        if is_ew:
            s = frame[["date", "code"]].copy()
            s["score"] = 1.0
            s["rank01"] = 0.5
            scored[name] = s
        else:
            scored[name] = score_frame(frame, factors, signs, icirs, sources)

    # Continuous backtests from earliest restricted start for rolling/bootstrap
    common_start = pd.Timestamp("2013-06-14")
    continuous = {}
    for name, (_, _, _, _, cfg, is_ew) in strategies.items():
        s = scored[name]
        s = s.loc[pd.to_datetime(s["date"]) >= common_start]
        use_cfg = cfg
        if is_ew:
            n_max = int(s.groupby("date")["code"].nunique().max())
            use_cfg = replace(cfg, position_size=max(n_max, 2), use_hysteresis=False)
        eq, tgt, _ = run_bt(s, prices, use_cfg)
        continuous[name] = {"equity": eq, "targets": tgt, "cfg": use_cfg}

    # --- Part 1: fixed comparable starts (fresh BT from start) ---
    rows_p1 = []
    for win_name, (w_start, w_end) in windows.items():
        for name, (_, _, _, _, cfg, is_ew) in strategies.items():
            s = scored[name].copy()
            s["date"] = pd.to_datetime(s["date"])
            if w_start is not None:
                s = s.loc[s["date"] >= w_start]
            if w_end is not None:
                s = s.loc[s["date"] <= w_end]
            if s.empty:
                continue
            use_cfg = cfg
            if is_ew:
                n_max = int(s.groupby("date")["code"].nunique().max())
                use_cfg = replace(cfg, position_size=max(n_max, 2), use_hysteresis=False)
            eq, tgt, _ = run_bt(s, prices, use_cfg)
            summ = summarize_equity(eq, use_cfg)
            # candidate distribution on rebalance days inside window
            if name.startswith("restricted") or name.endswith("_mbr") or "both_m" in name:
                cseries = pool_counts
            else:
                cseries = ranked_counts
            cseries = cseries.copy()
            if w_start is not None:
                cseries = cseries.loc[cseries.index >= w_start]
            if w_end is not None:
                cseries = cseries.loc[cseries.index <= w_end]
            # Independent rebalance count from targets
            n_reb = int(len(tgt)) if tgt is not None else summ["n_rebalances_approx"]
            rows_p1.append({
                "window": win_name,
                "start": str(pd.Timestamp(w_start).date()) if w_start is not None else "data_start",
                "strategy": name,
                **summ,
                "n_rebalances": n_reb,
                **cand_stats(cseries),
            })
    p1 = pd.DataFrame(rows_p1)
    p1.to_csv(OUT / "part1_fixed_starts.csv", index=False)

    # --- Part 2: rolling / expanding / yearly / regime windows ---
    eq_map = {k: v["equity"].set_index("date")["return"] for k, v in continuous.items()}
    # Align
    idx = eq_map["MOM_12m"].index
    for k in list(eq_map):
        eq_map[k] = eq_map[k].reindex(idx).fillna(0.0)

    def active(a, b):
        return eq_map[a] - eq_map[b]

    actives = {
        "shares_vs_mom12": active("mom_plus_shares", "MOM_12m"),
        "mbr_vs_rest_shares": active("restricted_mom_shares_mbr", "restricted_mom_shares"),
        "both_m_vs_rest_shares": active("restricted_mom_shares_both_m", "restricted_mom_shares"),
        "c1_vs_mom12": active("C1_research_partial", "MOM_12m"),
        "c1_vs_ew": active("C1_research_partial", "equal_weight_pool"),
    }

    def window_active_stats(series: pd.Series, start, end) -> float:
        sub = series.loc[(series.index >= start) & (series.index <= end)]
        if len(sub) < 20:
            return np.nan
        return float(sub.mean() * 252)

    roll_rows = []
    dates = idx.sort_values()

    def collect_windows(kind: str, spans: list[tuple[pd.Timestamp, pd.Timestamp, str]]):
        for start, end, label in spans:
            row = {"kind": kind, "label": label, "start": str(start.date()), "end": str(end.date()),
                   "n_days": int(((dates >= start) & (dates <= end)).sum())}
            flags = {}
            for aname, series in actives.items():
                val = window_active_stats(series, start, end)
                row[aname] = val
                flags[aname] = bool(val > 0) if np.isfinite(val) else False
            row["flags"] = flags
            roll_rows.append(row)

    # Rolling 2y / 3y (step 63 trading days ≈ quarter)
    for years, step in [(2, 63), (3, 63)]:
        width = int(252 * years)
        spans = []
        for i in range(0, len(dates) - width, step):
            start, end = dates[i], dates[i + width - 1]
            spans.append((start, end, f"{years}y_{start.date()}_{end.date()}"))
        collect_windows(f"roll_{years}y", spans)

    # Expanding
    anchors = dates[252::126]
    spans = [(dates[0], d, f"exp_{d.date()}") for d in anchors]
    collect_windows("expanding", spans)

    # Calendar years
    years = sorted(set(dates.year))
    spans = []
    for y in years:
        sub = dates[dates.year == y]
        if len(sub):
            spans.append((sub[0], sub[-1], str(y)))
    collect_windows("calendar_year", spans)

    # Regime: consecutive segments
    proxy = prices[config.regime_proxy]
    regime = market_regime(proxy).reindex(dates).ffill()
    spans = []
    if regime.notna().any():
        cur = None
        seg_start = None
        for d in dates:
            r = regime.loc[d]
            if cur is None:
                cur, seg_start = r, d
            elif r != cur:
                spans.append((seg_start, d, f"{cur}_{seg_start.date()}"))
                cur, seg_start = r, d
        if cur is not None and seg_start is not None:
            spans.append((seg_start, dates[-1], f"{cur}_{seg_start.date()}"))
        # Keep segments with >= 40 days
        spans = [(a, b, lab) for a, b, lab in spans if ((dates >= a) & (dates <= b)).sum() >= 40]
    collect_windows("regime_segment", spans)

    roll_df = pd.DataFrame([{k: v for k, v in r.items() if k != "flags"} for r in roll_rows])
    roll_df.to_csv(OUT / "part2_rolling_actives.csv", index=False)

    # Summary: positive share, worst window, longest failure streak
    part2_summary = {}
    for kind in roll_df["kind"].unique():
        sub_rows = [r for r in roll_rows if r["kind"] == kind]
        part2_summary[kind] = {}
        for aname in actives:
            finite_rows = [r for r in sub_rows if np.isfinite(r.get(aname, np.nan))]
            if not finite_rows:
                continue
            vals = [r[aname] for r in finite_rows]
            flags = [r["flags"][aname] for r in finite_rows]
            worst_i = int(np.nanargmin(vals))
            part2_summary[kind][aname] = {
                "n_windows": len(vals),
                "pct_positive": float(np.mean(flags)),
                "mean_active_ann": float(np.nanmean(vals)),
                "median_active_ann": float(np.nanmedian(vals)),
                "worst_active_ann": float(vals[worst_i]),
                "worst_label": finite_rows[worst_i]["label"],
                "worst_start": finite_rows[worst_i]["start"],
                "worst_end": finite_rows[worst_i]["end"],
                "longest_negative_streak_windows": longest_negative_streak(flags),
            }

    (OUT / "part2_summary.json").write_text(json.dumps(part2_summary, indent=2), encoding="utf-8")

    # --- Part 3: bootstrap ---
    oos_start = pd.Timestamp(config.oos_start)
    boot = {}
    for name in ["MOM_12m", "mom_plus_shares", "restricted_mom_shares",
                 "restricted_mom_shares_mbr", "restricted_mom_shares_both_m",
                 "C1_research_partial", "equal_weight_pool"]:
        eq = continuous[name]["equity"]
        boot[name] = {
            "full_daily": block_bootstrap_metrics(eq.set_index("date")["return"]),
            "oos_daily": block_bootstrap_metrics(slice_equity(eq, oos_start).set_index("date")["return"]),
            "full_period": block_bootstrap_metrics(
                period_returns(eq, config.frequency), block=max(3, BLOCK // 2)
            ),
        }
    for aname, series in actives.items():
        boot[f"active::{aname}"] = {
            "full": block_bootstrap_active(series),
            "from_2020": block_bootstrap_active(series.loc[series.index >= "2020-01-01"]),
            "oos": block_bootstrap_active(series.loc[series.index >= oos_start]),
        }
    oos_eq = slice_equity(continuous["C1_research_partial"]["equity"], oos_start)
    oos_targets = continuous["C1_research_partial"]["targets"]
    oos_targets["signal_date"] = pd.to_datetime(oos_targets["signal_date"])
    n_oos_reb = int((oos_targets["signal_date"] >= oos_start).sum())
    boot["oos_meta"] = {
        "oos_start": str(oos_start.date()),
        "oos_end": str(pd.to_datetime(oos_eq["date"]).max().date()) if len(oos_eq) else None,
        "oos_n_days": int(len(oos_eq)),
        "oos_sample_years": round(_ann_years(len(oos_eq)), 2),
        "oos_independent_rebalances": n_oos_reb,
        "warning": (
            "OOS Sharpe point estimates (e.g. 1.3–1.7) are not evidence of stable efficacy "
            "when independent rebalance count and sample years are short; use bootstrap CIs."
        ),
    }
    (OUT / "part3_bootstrap.json").write_text(json.dumps(boot, indent=2), encoding="utf-8")

    # --- Part 4: candidate pool size bins ---
    # Map each day to last rebalance's candidate count; attribute daily returns
    reb_cand = ranked_counts.sort_index()
    day_cand = reb_cand.reindex(dates, method="ffill")

    def bin_label(n):
        if not np.isfinite(n):
            return "na"
        if n <= 5:
            return "<=5"
        if n <= 10:
            return "6-10"
        if n <= 20:
            return "11-20"
        if n <= 30:
            return "21-30"
        return ">30"

    bins = day_cand.map(bin_label)
    bin_rows = []
    for b in ["<=5", "6-10", "11-20", "21-30", ">30"]:
        mask = bins == b
        if mask.sum() < 20:
            continue
        row = {"bin": b, "n_days": int(mask.sum()), "cand_mean": float(day_cand.loc[mask].mean())}
        for name in ["MOM_12m", "mom_plus_shares", "restricted_mom_shares",
                     "restricted_mom_shares_mbr", "restricted_mom_shares_both_m",
                     "C1_research_partial", "equal_weight_pool"]:
            r = eq_map[name].loc[mask]
            row[f"{name}_ann"] = float(r.mean() * 252)
        for aname, series in actives.items():
            row[aname] = float(series.loc[mask].mean() * 252)
        # Top-2 / candidate ratio
        row["top2_over_cand_mean"] = float((2.0 / day_cand.loc[mask].replace(0, np.nan)).mean())
        bin_rows.append(row)
    bin_df = pd.DataFrame(bin_rows)
    bin_df.to_csv(OUT / "part4_pool_size_bins.csv", index=False)

    # Exclusion tests: drop rebalance days with cand < 5 or < 10 (filter scores)
    excl_rows = []
    for thr in (5, 10):
        keep_dates = set(ranked_counts.loc[ranked_counts >= thr].index)
        for name in ["mom_plus_shares", "restricted_mom_shares_mbr",
                     "restricted_mom_shares_both_m", "C1_research_partial", "MOM_12m"]:
            s = scored[name].copy()
            s["date"] = pd.to_datetime(s["date"])
            # Keep all days but only allow ranking on keep rebalance dates by blanking others' scores
            # Simpler: start from 2020 and drop low-cand reb days from score panel
            s = s.loc[s["date"] >= "2020-01-01"]
            reb_mask = s["date"].isin(reb) & ~s["date"].isin(keep_dates)
            s.loc[reb_mask, "score"] = np.nan
            s.loc[reb_mask, "rank01"] = np.nan
            eq, tgt, _ = run_bt(s, prices, continuous[name]["cfg"])
            summ = summarize_equity(eq, continuous[name]["cfg"])
            excl_rows.append({"min_cand": thr, "strategy": name, **summ, "n_rebalances": int(len(tgt))})
    pd.DataFrame(excl_rows).to_csv(OUT / "part4_exclude_low_cand.csv", index=False)

    # --- Part 5: proxy / residualization ---
    # Cross-sectional Spearman of MARGIN vs characteristics; Rank IC vs next 5d return
    fwd = []
    for code, frame in prices.items():
        f = frame.sort_values("date").copy()
        f["fwd_5d"] = f["close"].shift(-5) / f["close"] - 1
        fwd.append(f[["date", "code", "fwd_5d"]])
    fwd = pd.concat(fwd, ignore_index=True)
    fwd["date"] = pd.to_datetime(fwd["date"]).dt.normalize()
    fwd["code"] = fwd["code"].astype(str).str.zfill(6)
    px = panel2.merge(fwd, on=["date", "code"], how="left")
    # Focus post-2020 for denser pool
    px = px.loc[pd.to_datetime(px["date"]) >= "2020-01-01"].copy()

    chars = ["log_amount", "log_aum", "turnover_proxy", "vol_20d", "amihud",
             "listing_age_days", "is_qdii", "margin_eligible_flag"]
    proxy_rows = []
    for factor in ["MARGIN_BUY_RATIO", "MARGIN_CHG_10D"]:
        for char in chars:
            daily = []
            for _, g in px.groupby("date"):
                sub = g[[factor, char]].dropna()
                if len(sub) < 8:
                    continue
                daily.append(sub[factor].corr(sub[char], method="spearman"))
            proxy_rows.append({
                "factor": factor, "characteristic": char,
                "mean_cs_spearman": float(np.nanmean(daily)) if daily else np.nan,
                "n_days": len(daily),
            })
        # Rank IC vs fwd_5d
        ics = []
        for _, g in px.groupby("date"):
            sub = g[[factor, "fwd_5d"]].dropna()
            if len(sub) < 8:
                continue
            ics.append(sub[factor].corr(sub["fwd_5d"], method="spearman"))
        proxy_rows.append({
            "factor": factor, "characteristic": "rank_ic_fwd_5d",
            "mean_cs_spearman": float(np.nanmean(ics)) if ics else np.nan,
            "n_days": len(ics),
        })
        # Residualize on controls then Rank IC
        controls = ["log_amount", "log_aum", "vol_20d", "listing_age_days", "turnover_proxy"]
        resid_ics = []
        for _, g in px.groupby("date"):
            cols = [factor, "fwd_5d", *controls]
            sub = g[cols].dropna()
            if len(sub) < 12:
                continue
            y = sub[factor].to_numpy()
            X = np.column_stack([np.ones(len(sub)), sub[controls].to_numpy()])
            try:
                beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                resid = y - X @ beta
                resid_ics.append(pd.Series(resid).corr(sub["fwd_5d"], method="spearman"))
            except Exception:
                continue
        proxy_rows.append({
            "factor": factor, "characteristic": "resid_rank_ic_fwd_5d_ctrl_liq_vol_age",
            "mean_cs_spearman": float(np.nanmean(resid_ics)) if resid_ics else np.nan,
            "n_days": len(resid_ics),
        })
    pd.DataFrame(proxy_rows).to_csv(OUT / "part5_proxy_ic.csv", index=False)

    # --- Part 6: absence kinds recount ---
    reasons_mbr = classify_missing_reasons(
        panel, "MARGIN_BUY_RATIO", listing_dates=listing,
        raw_first_obs={
            code: pd.to_datetime(g["observation_date"]).min()
            for code, g in pd.read_parquet(raw_dir / "rzmre.parquet").groupby("code")
        },
        margin_absence_kinds=absence_kinds,
    )
    reason_counts = {str(k): int(v) for k, v in reasons_mbr.value_counts().items()}
    absence_report = {
        "kinds": absence_kinds,
        "notes": absence_kind_notes(),
        "reason_counts_mbr": reason_counts,
        "code_rulings": {
            "159985": {
                "kind": absence_kinds.get("159985"),
                "evidence": absence_kind_notes().get("159985"),
                "retry_helpful": False,
            },
            "518880": {
                "kind": absence_kinds.get("518880"),
                "evidence": absence_kind_notes().get("518880"),
                "retry_helpful": "maybe_network_only; gold ETF may still lack margin history after success",
            },
        },
    }
    (OUT / "part6_absence_kinds.json").write_text(json.dumps(absence_report, indent=2), encoding="utf-8")

    # --- Part 7: stop conditions ---
    def pct_pos(kind, aname):
        return part2_summary.get(kind, {}).get(aname, {}).get("pct_positive", 0.0)

    mbr_roll2 = pct_pos("roll_2y", "mbr_vs_rest_shares")
    mbr_roll3 = pct_pos("roll_3y", "mbr_vs_rest_shares")
    both_roll2 = pct_pos("roll_2y", "both_m_vs_rest_shares")
    both_roll3 = pct_pos("roll_3y", "both_m_vs_rest_shares")

    def window_active(win, strat_a, strat_b):
        sub = p1.loc[(p1.window == win)]
        a = sub.loc[sub.strategy == strat_a, "annual_return"]
        b = sub.loc[sub.strategy == strat_b, "annual_return"]
        if a.empty or b.empty:
            return np.nan
        return float(a.iloc[0] - b.iloc[0])

    mbr_2020 = window_active("from_2020", "restricted_mom_shares_mbr", "restricted_mom_shares")
    both_2020 = window_active("from_2020", "restricted_mom_shares_both_m", "restricted_mom_shares")
    mbr_oos = window_active("frozen_oos", "restricted_mom_shares_mbr", "restricted_mom_shares")
    both_oos = window_active("frozen_oos", "restricted_mom_shares_both_m", "restricted_mom_shares")

    boot_mbr = boot["active::mbr_vs_rest_shares"]
    boot_both = boot["active::both_m_vs_rest_shares"]

    # Proxy residual IC
    proxy_df = pd.DataFrame(proxy_rows)
    resid_mbr = proxy_df.loc[
        (proxy_df.factor == "MARGIN_BUY_RATIO")
        & (proxy_df.characteristic == "resid_rank_ic_fwd_5d_ctrl_liq_vol_age"),
        "mean_cs_spearman",
    ]
    resid_ic = float(resid_mbr.iloc[0]) if len(resid_mbr) else np.nan

    criteria = {
        "margin_vs_shares_majority_roll2y_positive": bool(mbr_roll2 >= 0.5 or both_roll2 >= 0.5),
        "margin_vs_shares_majority_roll3y_positive": bool(mbr_roll3 >= 0.5 or both_roll3 >= 0.5),
        "positive_after_2020": bool((mbr_2020 > 0) or (both_2020 > 0)),
        "positive_frozen_oos": bool((mbr_oos > 0) or (both_oos > 0)),
        "bootstrap_p_positive_high": bool(
            max(
                boot_mbr["full"]["p_active_ann_positive"] or 0,
                boot_both["full"]["p_active_ann_positive"] or 0,
                boot_mbr["oos"]["p_active_ann_positive"] or 0,
                boot_both["oos"]["p_active_ann_positive"] or 0,
            ) >= 0.8
        ),
        "residual_ic_nonzero": bool(np.isfinite(resid_ic) and abs(resid_ic) >= 0.02),
        "detail": {
            "mbr_roll2_pct_pos": mbr_roll2,
            "mbr_roll3_pct_pos": mbr_roll3,
            "both_roll2_pct_pos": both_roll2,
            "both_roll3_pct_pos": both_roll3,
            "mbr_2020_d_ann": mbr_2020,
            "both_2020_d_ann": both_2020,
            "mbr_oos_d_ann": mbr_oos,
            "both_oos_d_ann": both_oos,
            "boot_mbr_full_p": boot_mbr["full"]["p_active_ann_positive"],
            "boot_both_full_p": boot_both["full"]["p_active_ann_positive"],
            "boot_mbr_oos_p": boot_mbr["oos"]["p_active_ann_positive"],
            "boot_both_oos_p": boot_both["oos"]["p_active_ann_positive"],
            "resid_ic_mbr": resid_ic,
            "start_med10": str(start_med10.date()) if start_med10 is not None else None,
            "start_med20": str(start_med20.date()) if start_med20 is not None else None,
        },
    }
    continue_margin = all([
        criteria["margin_vs_shares_majority_roll2y_positive"],
        criteria["margin_vs_shares_majority_roll3y_positive"],
        criteria["positive_after_2020"],
        criteria["positive_frozen_oos"],
        criteria["bootstrap_p_positive_high"],
        criteria["residual_ic_nonzero"],
    ])

    # C1 as independent research?
    c1_roll2 = pct_pos("roll_2y", "c1_vs_mom12")
    c1_2020 = window_active("from_2020", "C1_research_partial", "MOM_12m")
    c1_oos = window_active("frozen_oos", "C1_research_partial", "MOM_12m")
    c1_boot = boot["active::c1_vs_mom12"]["full"]["p_active_ann_positive"]

    verdict = {
        "project_status": "ENGINEERING_PARTIAL_REPRODUCTION" if not continue_margin else "CONTINUE_MARGIN_DATA",
        "continue_procure_margin_data": continue_margin,
        "continue_c1_as_independent_research": bool(
            c1_roll2 >= 0.55 and c1_2020 > 0 and (c1_boot or 0) >= 0.7
        ),
        "seal_as_engineering_not_strategy_reproduction": True,
        "pivot_to_ARCANA": True,
        "criteria": criteria,
        "c1_checks": {
            "roll2_pct_pos_vs_mom12": c1_roll2,
            "d_ann_2020_vs_mom12": c1_2020,
            "d_ann_oos_vs_mom12": c1_oos,
            "boot_p_full": c1_boot,
        },
        "rationale": [],
    }
    if not continue_margin:
        verdict["rationale"].append(
            "Margin incremental edge vs same-pool shares fails the pre-registered stop gates "
            "(rolling positivity / OOS / bootstrap / residual IC)."
        )
        verdict["rationale"].append(
            "Stop chasing v8 published numbers; keep code + research reports; mark engineering-grade partial reproduction."
        )
    if verdict["seal_as_engineering_not_strategy_reproduction"]:
        verdict["rationale"].append(
            "Sealed C1/C4 factor sets remain PARTIAL_REPRODUCTION (margin not production-tier); "
            "this is an engineering reproduction of the pipeline, not a sealed strategy reproduction."
        )
    if verdict["pivot_to_ARCANA"]:
        verdict["rationale"].append(
            "Further research time is better spent on ARCANA reproduction than incremental margin backfills."
        )
    if not verdict["continue_c1_as_independent_research"]:
        verdict["rationale"].append(
            "C1 research-partial may still be studied as a hypothesis, but should not be treated as a validated live strategy."
        )
    else:
        verdict["rationale"].append(
            "C1 shows some vs-MOM12 positivity but remains data-blocked for sealed reproduction."
        )

    (OUT / "final_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print(json.dumps({
        "windows_starts": {k: (str(v[0].date()) if v[0] is not None else None) for k, v in windows.items()},
        "verdict": verdict,
        "outputs": str(OUT),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
