#!/usr/bin/env python3
"""Margin coverage diagnosis + same-pool attribution + OHLCV baselines + concentration.

Read-only research: no fill, no param/weight changes.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.backtest import metrics, variant_config, vector_backtest
from etf_rotation.config import frozen_config, strategy_definition
from etf_rotation.data import build_pit_universe, cached_prices, universe_definition
from etf_rotation.factors import (
    classify_missing_reasons,
    cross_sectional_scores,
    factor_panel,
    ohlcv_factor_panel,
)
from etf_rotation.non_ohlcv.loader import load_non_ohlcv_sources
from etf_rotation.strategy import rebalance_dates

OUT = Path("/home/ec2-user/strategy-backtest/etf_rotation/reports/margin_attribution")
OUT.mkdir(parents=True, exist_ok=True)


def yearly_returns(equity: pd.DataFrame) -> dict[str, float]:
    frame = equity.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    series = (
        frame.set_index("date")["return"]
        .resample("YE")
        .apply(lambda s: float((1 + s).prod() - 1) if len(s) else np.nan)
    )
    return {f"year_{pd.Timestamp(k).year}": float(v) for k, v in series.items()}


def rolling_12m(equity: pd.DataFrame) -> pd.Series:
    frame = equity.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    r = frame.set_index("date")["return"]
    # 252 trading days ≈ 12m
    return (1 + r).rolling(252).apply(lambda s: float(s.prod() - 1), raw=False)


def run_vec(scores: pd.DataFrame, prices: dict, config) -> dict:
    result = vector_backtest(scores, prices, config)
    equity = result["equity"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    m = metrics(equity["return"])
    return {
        "metrics": m,
        "equity": equity,
        "turnover": float(equity["turnover"].sum()) if "turnover" in equity else np.nan,
        "total_fees": float(equity["turnover"].sum() * config.commission_a_share),
        "yearly": yearly_returns(equity),
        "roll12_mean": float(rolling_12m(equity).mean()),
        "roll12_last": float(rolling_12m(equity).dropna().iloc[-1]) if rolling_12m(equity).notna().any() else np.nan,
        "result": result,
    }


def apply_pit(scores: pd.DataFrame, pit: pd.DataFrame) -> pd.DataFrame:
    out = scores.merge(pit[["date", "code", "eligible"]], on=["date", "code"], how="left")
    return out.loc[out.eligible.fillna(False)].drop(columns="eligible")


def main() -> None:
    config = frozen_config()
    prices = cached_prices(config)
    definition = universe_definition(config)
    sources = load_non_ohlcv_sources(config)
    panel = factor_panel(prices, config, sources=sources)
    pit = build_pit_universe(prices, definition, config.lookback)
    listing = {
        code: pd.to_datetime(frame["date"]).min()
        for code, frame in prices.items()
    }

    # Raw staging / production long frames
    root = Path(config.cache_dir) / "non_ohlcv"
    staging = sorted((root / "staging").glob("*"))[-1]
    raw_dir = sorted((root / "raw").glob("*"))[-1]
    rzye = pd.read_parquet(raw_dir / "rzye.parquet")
    rzmre = pd.read_parquet(raw_dir / "rzmre.parquet")
    stage_mbr = pd.read_parquet(staging / "MARGIN_BUY_RATIO.parquet")
    stage_mcg = pd.read_parquet(staging / "MARGIN_CHG_10D.parquet")

    # ------------------------------------------------------------------
    # Part A: coverage contradiction diagnosis
    # ------------------------------------------------------------------
    ohlcv = ohlcv_factor_panel(prices)
    n_ohlcv = len(ohlcv)
    # staging grid missing (24% story)
    full_mbr_miss = float(stage_mbr["value"].isna().mean())
    full_mcg_miss = float(stage_mcg["value"].isna().mean())
    full_both_ok = float(
        (stage_mbr["value"].notna() & stage_mcg["value"].notna()).mean()
    )
    full_either_ok = float(
        (stage_mbr["value"].notna() | stage_mcg["value"].notna()).mean()
    )

    # after merge into panel
    panel_mbr_miss = float(panel["MARGIN_BUY_RATIO"].isna().mean())
    panel_mcg_miss = float(panel["MARGIN_CHG_10D"].isna().mean())
    merge_match_mbr = float(panel["MARGIN_BUY_RATIO"].notna().mean())
    # row counts
    merge_diag = {
        "ohlcv_panel_rows": n_ohlcv,
        "staging_mbr_rows": len(stage_mbr),
        "staging_mcg_rows": len(stage_mcg),
        "merged_panel_rows": len(panel),
        "staging_mbr_missing_ratio": full_mbr_miss,
        "staging_mcg_missing_ratio": full_mcg_miss,
        "panel_mbr_missing_ratio": panel_mbr_miss,
        "panel_mcg_missing_ratio": panel_mcg_miss,
        "staging_both_valid_ratio": full_both_ok,
        "staging_either_valid_ratio": full_either_ok,
        "panel_both_valid_ratio": float(
            panel["MARGIN_BUY_RATIO"].notna() & panel["MARGIN_CHG_10D"].notna()
        ).mean() if False else float(
            (panel["MARGIN_BUY_RATIO"].notna() & panel["MARGIN_CHG_10D"].notna()).mean()
        ),
        "panel_mbr_only_ratio": float(
            (panel["MARGIN_BUY_RATIO"].notna() & panel["MARGIN_CHG_10D"].isna()).mean()
        ),
        "panel_mcg_only_ratio": float(
            (panel["MARGIN_CHG_10D"].notna() & panel["MARGIN_BUY_RATIO"].isna()).mean()
        ),
    }

    # code format check
    panel_codes = set(panel["code"].astype(str))
    stage_codes = set(stage_mbr["code"].astype(str))
    raw_codes = set(rzye["code"].astype(str))
    merge_diag["codes_panel_not_in_stage"] = sorted(panel_codes - stage_codes)[:20]
    merge_diag["codes_stage_not_in_panel"] = sorted(stage_codes - panel_codes)[:20]
    merge_diag["codes_never_in_raw_rzye"] = sorted(set(definition["code"].astype(str).str.zfill(6)) - raw_codes)

    # C1 score panel diagnostics (same as runtime)
    c1_factors, c1_signs, c1_icirs = strategy_definition(config, "composite_1")
    c1_scores, c1_audit = cross_sectional_scores(
        panel, c1_factors, c1_signs, c1_icirs, run_mode="research", sources=sources
    )
    c1_elig = apply_pit(c1_scores, pit)

    def exclusion_breakdown(scored: pd.DataFrame, margin_cols: list[str]) -> dict:
        n = len(scored)
        excluded = scored["score"].isna()
        n_ex = int(excluded.sum())
        margin_missing = scored[margin_cols].isna().all(axis=1) if margin_cols else pd.Series(False, index=scored.index)
        # other factor incompleteness (any non-margin declared factor NaN)
        other = [c for c in c1_factors if c not in margin_cols]
        other_missing = scored[other].isna().any(axis=1) if other else pd.Series(False, index=scored.index)
        # z columns
        z_margin_nan = pd.Series(False, index=scored.index)
        for col in margin_cols:
            zc = f"z_{col}"
            if zc in scored.columns:
                z_margin_nan |= scored[zc].isna()
        return {
            "rows": n,
            "excluded_rows": n_ex,
            "excluded_ratio": n_ex / n if n else np.nan,
            "margin_missing_rows": int(margin_missing.sum()),
            "margin_missing_ratio": float(margin_missing.mean()),
            "overlap_excluded_and_margin_missing": int((excluded & margin_missing).sum()),
            "p_margin_missing_given_excluded": float((excluded & margin_missing).sum() / n_ex) if n_ex else np.nan,
            "p_excluded_given_margin_missing": float((excluded & margin_missing).sum() / margin_missing.sum()) if margin_missing.any() else np.nan,
            "excluded_with_margin_present": int((excluded & ~margin_missing).sum()),
            "excluded_with_other_factor_missing": int((excluded & other_missing).sum()),
            "excluded_margin_present_but_other_missing": int((excluded & ~margin_missing & other_missing).sum()),
            "complete_score_ratio": float(scored["score"].notna().mean()),
        }

    diag_full = exclusion_breakdown(c1_scores, ["MARGIN_BUY_RATIO"])
    diag_elig = exclusion_breakdown(c1_elig, ["MARGIN_BUY_RATIO"])

    # Period slices on eligible C1 panel
    def period_cov(frame: pd.DataFrame) -> dict:
        d = pd.to_datetime(frame["date"])
        slices = {
            "all": frame,
            "train": frame.loc[(d >= "2020-01-01") & (d <= "2025-04-30")],
            "oos": frame.loc[d >= "2025-05-01"],
            "pre_2020": frame.loc[d < "2020-01-01"],
        }
        out = {}
        for name, sub in slices.items():
            if sub.empty:
                out[name] = {}
                continue
            out[name] = {
                "rows": len(sub),
                "mbr_coverage": float(sub["MARGIN_BUY_RATIO"].notna().mean()),
                "mcg_coverage": float(sub["MARGIN_CHG_10D"].notna().mean()) if "MARGIN_CHG_10D" in sub else np.nan,
                "both_coverage": float((sub["MARGIN_BUY_RATIO"].notna() & sub["MARGIN_CHG_10D"].notna()).mean()) if "MARGIN_CHG_10D" in sub else np.nan,
                "score_coverage": float(sub["score"].notna().mean()) if "score" in sub else np.nan,
            }
        return out

    # Attach MCG onto c1 for period stats
    c1_scores2 = c1_scores.merge(
        panel[["date", "code", "MARGIN_CHG_10D"]], on=["date", "code"], how="left", suffixes=("", "_y")
    )
    if "MARGIN_CHG_10D_y" in c1_scores2:
        c1_scores2["MARGIN_CHG_10D"] = c1_scores2["MARGIN_CHG_10D_y"]
    period_stats = period_cov(c1_scores2)
    period_stats_elig = period_cov(apply_pit(c1_scores2, pit))

    # Rebalance-day coverage
    score_dates = pd.DatetimeIndex(sorted(pd.to_datetime(c1_elig["date"]).unique()))
    reb = rebalance_dates(score_dates, config.frequency)
    reb_rows = c1_elig.loc[pd.to_datetime(c1_elig["date"]).isin(reb)]
    reb_diag = exclusion_breakdown(reb_rows, ["MARGIN_BUY_RATIO"])
    # candidates with score per rebalance date
    reb_counts = (
        reb_rows.loc[reb_rows["score"].notna()]
        .groupby("date")["code"].nunique()
        .rename("n_ranked")
    )
    reb_counts_all = reb_rows.groupby("date")["code"].nunique().rename("n_eligible_etf")
    reb_ts = pd.concat([reb_counts_all, reb_counts], axis=1).fillna(0)
    reb_ts["n_ranked"] = reb_ts["n_ranked"].astype(int)
    reb_ts.to_csv(OUT / "rebalance_ranked_count_timeseries.csv")

    # Per-ETF margin coverage
    etf_rows = []
    for code, g in panel.groupby("code"):
        mbr = g["MARGIN_BUY_RATIO"]
        valid = mbr.dropna()
        etf_rows.append({
            "code": code,
            "bars": len(g),
            "mbr_coverage": float(mbr.notna().mean()),
            "mcg_coverage": float(g["MARGIN_CHG_10D"].notna().mean()),
            "mbr_first": str(pd.to_datetime(g.loc[mbr.notna(), "date"]).min().date()) if mbr.notna().any() else "",
            "mbr_last": str(pd.to_datetime(g.loc[mbr.notna(), "date"]).max().date()) if mbr.notna().any() else "",
            "score_participation_c1": float(
                c1_elig.loc[c1_elig.code.eq(code), "score"].notna().mean()
            ) if code in set(c1_elig.code) else 0.0,
        })
    etf_cov = pd.DataFrame(etf_rows).sort_values("mbr_coverage")
    etf_cov.to_csv(OUT / "etf_margin_coverage.csv", index=False)

    # Missing reason decomposition on panel for MARGIN_BUY_RATIO
    raw_first = {
        "MARGIN_BUY_RATIO": {
            code: pd.to_datetime(g["observation_date"]).min()
            for code, g in rzmre.groupby("code")
        },
        "MARGIN_CHG_10D": {
            code: pd.to_datetime(g["observation_date"]).min()
            for code, g in rzye.groupby("code")
        },
    }
    download_failures = {"159985", "518880"}
    reasons_mbr = classify_missing_reasons(
        panel, "MARGIN_BUY_RATIO", listing_dates=listing,
        raw_first_obs=raw_first["MARGIN_BUY_RATIO"], download_failures=download_failures,
    )
    # Also tag exclusions due to other factors on C1 scored rows
    c1_ex = c1_scores["score"].isna()
    other_factors = [f for f in c1_factors if f != "MARGIN_BUY_RATIO"]
    reason_extra = {
        "excluded_rows_total": int(c1_ex.sum()),
        "excluded_due_to_margin_buy_ratio_nan": int((c1_ex & c1_scores["MARGIN_BUY_RATIO"].isna()).sum()),
        "excluded_with_margin_ok_other_nan": int(
            (c1_ex & c1_scores["MARGIN_BUY_RATIO"].notna() & c1_scores[other_factors].isna().any(axis=1)).sum()
        ),
    }
    for f in other_factors:
        reason_extra[f"excluded_with_{f}_nan"] = int((c1_ex & c1_scores[f].isna()).sum())
    reason_counts = reasons_mbr.value_counts().to_dict()
    reason_counts = {str(k): int(v) for k, v in reason_counts.items()}

    # Year concentration of exclusions
    c1_scores = c1_scores.copy()
    c1_scores["year"] = pd.to_datetime(c1_scores["date"]).dt.year
    year_ex = c1_scores.groupby("year").apply(
        lambda g: pd.Series({
            "rows": len(g),
            "excluded_ratio": float(g["score"].isna().mean()),
            "mbr_missing_ratio": float(g["MARGIN_BUY_RATIO"].isna().mean()),
            "ranked_etf_mean": float(g.loc[g["score"].notna()].groupby("date")["code"].nunique().mean()) if g["score"].notna().any() else 0.0,
        })
    )
    year_ex.to_csv(OUT / "exclusion_by_year.csv")

    part_a = {
        "merge_diag": merge_diag,
        "c1_full_panel_exclusion": diag_full,
        "c1_eligible_panel_exclusion": diag_elig,
        "rebalance_day_exclusion": reb_diag,
        "rebalance_ranked_count_summary": {
            "mean": float(reb_ts["n_ranked"].mean()),
            "median": float(reb_ts["n_ranked"].median()),
            "min": int(reb_ts["n_ranked"].min()),
            "max": int(reb_ts["n_ranked"].max()),
            "p10": float(reb_ts["n_ranked"].quantile(0.1)),
            "p90": float(reb_ts["n_ranked"].quantile(0.9)),
        },
        "period_coverage_full_c1_panel": period_stats,
        "period_coverage_eligible_c1": period_stats_elig,
        "missing_reason_counts_mbr": reason_counts,
        "exclusion_factor_decomposition": reason_extra,
        "interpretation": {
            "grid_24pct": (
                "staging MARGIN_* missing_ratio on full OHLCV ETF×date grid "
                f"(~{full_mbr_miss:.1%} NaN cells / all staging rows)"
            ),
            "overlap_91pct": (
                "P(all declared MARGIN_* NaN | score NaN) on the scored C1 panel — "
                "NOT the share of universe lacking margin. Denominator = excluded score rows; "
                "numerator = excluded rows that also lack MARGIN_BUY_RATIO."
            ),
        },
    }
    (OUT / "part_a_coverage_diagnosis.json").write_text(
        json.dumps(part_a, indent=2, default=str), encoding="utf-8"
    )

    # ------------------------------------------------------------------
    # Part B: same-pool attribution
    # ------------------------------------------------------------------
    # Define rebalance dates and margin-available pool (both margin factors for C4 path;
    # for C1 use MARGIN_BUY_RATIO). User asked: 两融因子共同可用 → both MBR and MCG.
    train_end = pd.Timestamp(config.training_end)
    oos_start = pd.Timestamp(config.oos_start)

    # Use eligible panel dates
    base_dates = pd.DatetimeIndex(sorted(pd.to_datetime(pit.loc[pit.eligible, "date"]).unique()))
    reb_dates = rebalance_dates(base_dates, config.frequency)

    # Build restricted universe membership: on each rebalance date, codes where both margin factors valid
    # AND OHLCV factors needed for mom/shares exist enough to score.
    panel2 = panel.merge(pit[["date", "code", "eligible"]], on=["date", "code"], how="left")
    panel2 = panel2.loc[panel2.eligible.fillna(False)].copy()

    # Precompute MOM_60D / MOM_252D for baselines (OHLCV only additions, not frozen weights)
    # Add to a working price-derived panel
    parts = []
    for code, frame in prices.items():
        f = frame.sort_values("date").copy()
        f["MOM_60D"] = f["close"].pct_change(60)
        f["MOM_126D"] = f["close"].pct_change(126)  # ~6m
        f["MOM_252D"] = f["close"].pct_change(252)  # ~12m
        parts.append(f[["date", "code", "MOM_60D", "MOM_126D", "MOM_252D"]])
    extra = pd.concat(parts, ignore_index=True)
    extra["date"] = pd.to_datetime(extra["date"]).dt.normalize()
    extra["code"] = extra["code"].astype(str).str.zfill(6)
    panel2 = panel2.merge(extra, on=["date", "code"], how="left")
    panel2["MOM_6_12_EQ"] = panel2[["MOM_126D", "MOM_252D"]].mean(axis=1)

    # Restricted pool: both margin factors non-null on that date
    panel2["margin_pool"] = panel2["MARGIN_BUY_RATIO"].notna() & panel2["MARGIN_CHG_10D"].notna()

    def score_on_pool(
        frame: pd.DataFrame,
        factors: list[str],
        signs: list[float],
        icirs: list[float],
        *,
        pool_mask: pd.Series | None,
        label: str,
    ) -> tuple[pd.DataFrame, dict]:
        sub = frame.loc[pool_mask].copy() if pool_mask is not None else frame.copy()
        # Require all factors present for a row to get a score (same complete rule)
        scored, audit = cross_sectional_scores(
            sub, factors, signs, icirs, run_mode="research", sources=sources
        )
        # Keep only rebalance dates that exist in restricted history
        return scored, {"audit": audit.to_jsonable(), "label": label}

    # Align date range: intersection of dates where margin pool has >= 2 names
    pool_counts = panel2.loc[panel2.margin_pool].groupby("date")["code"].nunique()
    valid_dates = pool_counts[pool_counts >= 2].index
    valid_reb = [d for d in reb_dates if d in set(valid_dates)]
    date_mask = panel2["date"].isin(valid_reb) | panel2["date"].isin(valid_dates)
    # Actually for backtest we need daily scores on all days or at least reb days.
    # Restrict scoring universe rows to margin_pool & dates >= first valid_reb
    if not valid_reb:
        raise RuntimeError("no valid restricted rebalance dates")
    start = pd.Timestamp(valid_reb[0])
    end = pd.Timestamp(valid_reb[-1])
    range_mask = (panel2["date"] >= start) & (panel2["date"] <= end)
    restricted_frame = panel2.loc[range_mask & panel2.margin_pool].copy()

    # Full-pool frame same date range for "pool switch" contrast
    full_frame = panel2.loc[range_mask].copy()

    cfg_r1 = variant_config(config, "R1")
    cfg_c1 = variant_config(config, "C1")
    cfg_c4 = variant_config(config, "C4")

    experiments_b = []

    def add_exp(name, frame, factors, signs, icirs, cfg):
        scored, meta = score_on_pool(frame, factors, signs, icirs, pool_mask=None, label=name)
        # Filter scores to same date range
        scored = scored.loc[(pd.to_datetime(scored["date"]) >= start) & (pd.to_datetime(scored["date"]) <= end)]
        # On each date, only keep codes in restricted pool for experiments 1-4
        if name.startswith("restricted_pool"):
            allow = set(zip(
                pd.to_datetime(restricted_frame["date"]).astype(str),
                restricted_frame["code"].astype(str),
            ))
            key = list(zip(pd.to_datetime(scored["date"]).astype(str), scored["code"].astype(str)))
            scored = scored.loc[[k in allow for k in key]].copy()
        run = run_vec(scored, prices, cfg)
        n_cand = (
            scored.loc[scored["score"].notna()]
            .groupby("date")["code"].nunique()
        )
        experiments_b.append({
            "experiment": name,
            "declared_factors": "|".join(factors),
            "actual_factors": "|".join(meta["audit"]["actual_factors"]),
            "reproduction_status": meta["audit"]["reproduction_status"],
            "date_start": str(start.date()),
            "date_end": str(end.date()),
            "mean_candidates": float(n_cand.mean()) if len(n_cand) else np.nan,
            "median_candidates": float(n_cand.median()) if len(n_cand) else np.nan,
            "annual_return": run["metrics"]["annual_return"],
            "sharpe": run["metrics"]["sharpe"],
            "max_drawdown": run["metrics"]["max_drawdown"],
            "turnover": run["turnover"],
            "total_fees": run["total_fees"],
            "total_return": run["metrics"]["total_return"],
            "roll12_mean": run["roll12_mean"],
            **run["yearly"],
            "_equity": run["equity"],
            "_scores": scored,
        })

    # 1 mom only on restricted pool
    add_exp("restricted_pool_mom_only", restricted_frame, ["MOM_20D"], [1], [1], cfg_r1)
    # 2 mom + shares
    add_exp(
        "restricted_pool_mom_plus_shares", restricted_frame,
        ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D"], [1, -1, -1], [1, 2.306, 1.807], cfg_r1,
    )
    # 3 + margin buy ratio
    add_exp(
        "restricted_pool_plus_margin_buy_ratio", restricted_frame,
        ["MOM_20D", "SHARE_CHG_5D", "MARGIN_BUY_RATIO"], [1, -1, -1], [1, 2.306, 5.101], cfg_r1,
    )
    # 4 + both margin
    add_exp(
        "restricted_pool_plus_both_margin_factors", restricted_frame,
        ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D", "MARGIN_BUY_RATIO", "MARGIN_CHG_10D"],
        [1, -1, -1, -1, -1], [1, 2.306, 1.807, 5.101, 3.387], cfg_r1,
    )
    # 5 C1 research partial on FULL pool but same date range
    add_exp("C1_research_partial_same_range", full_frame, c1_factors, c1_signs, c1_icirs, cfg_c1)
    # 6 C4
    c4_f, c4_s, c4_i = strategy_definition(config, "core_4f")
    add_exp("C4_research_partial_same_range", full_frame, c4_f, c4_s, c4_i, cfg_c4)

    # Also full-pool mom same range for pool-switch delta
    add_exp("full_pool_mom_same_range", full_frame, ["MOM_20D"], [1], [1], cfg_r1)

    b_table = pd.DataFrame([{k: v for k, v in row.items() if not k.startswith("_")} for row in experiments_b])
    b_table.to_csv(OUT / "part_b_same_pool.csv", index=False)

    # Attribution deltas
    by = {r["experiment"]: r for r in experiments_b}
    deltas = {
        "pool_switch_mom": {
            "from": "full_pool_mom_same_range",
            "to": "restricted_pool_mom_only",
            "d_ann": by["restricted_pool_mom_only"]["annual_return"] - by["full_pool_mom_same_range"]["annual_return"],
            "d_sharpe": by["restricted_pool_mom_only"]["sharpe"] - by["full_pool_mom_same_range"]["sharpe"],
            "d_mdd": by["restricted_pool_mom_only"]["max_drawdown"] - by["full_pool_mom_same_range"]["max_drawdown"],
        },
        "add_margin_buy_in_pool": {
            "from": "restricted_pool_mom_plus_shares",
            "to": "restricted_pool_plus_margin_buy_ratio",
            "d_ann": by["restricted_pool_plus_margin_buy_ratio"]["annual_return"] - by["restricted_pool_mom_plus_shares"]["annual_return"],
            "d_sharpe": by["restricted_pool_plus_margin_buy_ratio"]["sharpe"] - by["restricted_pool_mom_plus_shares"]["sharpe"],
        },
        "add_both_margin_in_pool": {
            "from": "restricted_pool_mom_plus_shares",
            "to": "restricted_pool_plus_both_margin_factors",
            "d_ann": by["restricted_pool_plus_both_margin_factors"]["annual_return"] - by["restricted_pool_mom_plus_shares"]["annual_return"],
            "d_sharpe": by["restricted_pool_plus_both_margin_factors"]["sharpe"] - by["restricted_pool_mom_plus_shares"]["sharpe"],
        },
    }
    # Proxy check: correlate margin factors with size/liquidity/listing age on restricted pool
    proxy = restricted_frame.copy()
    proxy["listing_age_days"] = (
        pd.to_datetime(proxy["date"]) - pd.to_datetime(proxy["code"].map(listing))
    ).dt.days
    proxy["log_amount"] = np.log1p(proxy["amount"].clip(lower=0))
    corr_rows = []
    for factor in ["MARGIN_BUY_RATIO", "MARGIN_CHG_10D", "SHARE_CHG_5D", "SHARE_CHG_20D", "MOM_20D"]:
        for char in ["log_amount", "listing_age_days", "PRICE_POSITION_120D"]:
            if char not in proxy.columns or factor not in proxy.columns:
                continue
            sub = proxy[[factor, char]].dropna()
            if len(sub) < 100:
                continue
            corr_rows.append({
                "factor": factor, "characteristic": char,
                "spearman": float(sub[factor].corr(sub[char], method="spearman")),
                "n": len(sub),
            })
    pd.DataFrame(corr_rows).to_csv(OUT / "part_b_proxy_correlations.csv", index=False)
    (OUT / "part_b_deltas.json").write_text(json.dumps(deltas, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Part C: OHLCV baselines (same range, costs, Top-K, hysteresis, regime)
    # ------------------------------------------------------------------
    # Equal-weight 49: synthetic scores all equal → need special handling.
    # Implement as equal rank by assigning constant score on eligible universe.
    baselines = []

    def add_baseline(name, factors, signs=None, icirs=None, equal_weight=False):
        frame = full_frame.copy()
        cfg = cfg_r1
        if equal_weight:
            # Hold full eligible universe equally: Top-K = all names that day; regime gate kept.
            scored = frame[["date", "code"]].copy()
            scored["score"] = 1.0
            scored["rank01"] = 0.5
            scored["is_partial_factor_set"] = False
            audit_status = "BASELINE_OHLCV"
            actual = ["EQUAL_WEIGHT"]
            n_max = int(scored.groupby("date")["code"].nunique().max())
            cfg = replace(cfg_r1, position_size=n_max, use_hysteresis=False)
        else:
            signs = signs or [1.0] * len(factors)
            icirs = icirs or [1.0] * len(factors)
            scored, audit = cross_sectional_scores(
                frame, factors, signs, icirs, run_mode="research", sources=sources
            )
            scored = scored.loc[(pd.to_datetime(scored["date"]) >= start) & (pd.to_datetime(scored["date"]) <= end)]
            audit_status = audit.reproduction_status
            actual = audit.actual_factors
        run = run_vec(scored, prices, cfg)
        baselines.append({
            "baseline": name,
            "status": audit_status,
            "factors": "|".join(actual if not equal_weight else ["EQUAL_WEIGHT_49"]),
            "annual_return": run["metrics"]["annual_return"],
            "sharpe": run["metrics"]["sharpe"],
            "max_drawdown": run["metrics"]["max_drawdown"],
            "turnover": run["turnover"],
            "total_return": run["metrics"]["total_return"],
            **run["yearly"],
            "_equity": run["equity"],
        })

    add_baseline("MOM_20D", ["MOM_20D"])
    add_baseline("MOM_126D_6m", ["MOM_126D"])
    add_baseline("MOM_252D_12m", ["MOM_252D"])
    # 6/12 equal weight combo as single factor already averaged
    add_baseline("MOM_6_12_EQ", ["MOM_6_12_EQ"])
    add_baseline(
        "all_frozen_ohlcv",
        ["ADX_14D", "BREAKOUT_20D", "PRICE_POSITION_120D", "SLOPE_20D", "MOM_20D"],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
    )
    add_baseline("equal_weight_49", [], equal_weight=True)

    # both share + C1 on same range already in part B; keep share-only baseline too
    add_baseline(
        "mom_plus_both_shares",
        ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D"],
        [1, -1, -1], [1, 2.306, 1.807],
    )

    c_table = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in baselines])
    c_table.to_csv(OUT / "part_c_ohlcv_baselines.csv", index=False)

    # ------------------------------------------------------------------
    # Part D: concentration for both-shares and C1
    # ------------------------------------------------------------------
    def concentration(label: str, exp_row: dict, mom_equity: pd.DataFrame) -> dict:
        scores = exp_row["_scores"]
        equity = exp_row["_equity"]
        cfg = cfg_c1 if "C1" in label else cfg_r1
        run = vector_backtest(scores, prices, cfg)
        targets = run["targets"]
        daily = run["daily_targets"].copy()
        daily["date"] = pd.to_datetime(daily["date"])

        # Approximate PnL contribution: equal-weight among holdings × daily portfolio return share
        # More precise: map holdings to next-day open-to-open via price panel.
        price_panel = []
        for code, frame in prices.items():
            f = frame.sort_values("date")[["date", "open"]].copy()
            f["code"] = code
            f["ret_open"] = f["open"].pct_change()
            price_panel.append(f)
        px = pd.concat(price_panel, ignore_index=True)
        px["date"] = pd.to_datetime(px["date"]).dt.normalize()
        px["code"] = px["code"].astype(str).str.zfill(6)

        rows = []
        for _, row in daily.iterrows():
            codes = [c for c in str(row["holdings"]).split("|") if c]
            if not codes:
                continue
            w = 1.0 / len(codes)
            for code in codes:
                rows.append({"date": row["date"], "code": code, "w": w})
        hold_df = pd.DataFrame(rows)
        contrib_map: dict[str, float] = {}
        if not hold_df.empty:
            merged_h = hold_df.merge(px, on=["date", "code"], how="left")
            merged_h["pnl"] = merged_h["w"] * merged_h["ret_open"].fillna(0.0)
            contrib_map = merged_h.groupby("code")["pnl"].sum().to_dict()
        top_etf = sorted(contrib_map.items(), key=lambda x: -x[1])[:5]
        top_etf = [(c, float(v)) for c, v in top_etf]

        hold_counts: dict[str, int] = {}
        if not targets.empty and "holdings" in targets.columns:
            for _, row in targets.iterrows():
                for code in str(row["holdings"]).split("|"):
                    if code:
                        hold_counts[code] = hold_counts.get(code, 0) + 1

        eq = equity.copy()
        eq["date"] = pd.to_datetime(eq["date"])
        eq = eq.sort_values("date")
        window = config.frequency
        period_rets = []
        for i in range(0, max(0, len(eq) - window), window):
            chunk = eq.iloc[i : i + window]
            period_rets.append({
                "start": str(chunk["date"].iloc[0].date()),
                "end": str(chunk["date"].iloc[-1].date()),
                "ret": float((1 + chunk["return"]).prod() - 1),
            })
        top_periods = sorted(period_rets, key=lambda x: -x["ret"])[:5]
        worst_periods = sorted(period_rets, key=lambda x: x["ret"])[:5]
        yearly = yearly_returns(eq)
        years = {int(k.split("_")[1]): v for k, v in yearly.items()}
        best_year = max(years, key=years.get) if years else None
        worst_year = min(years, key=years.get) if years else None

        drop_code = top_etf[0][0] if top_etf else None
        drop_metrics = {}
        if drop_code:
            scored2 = scores.loc[~scores.code.astype(str).eq(str(drop_code))].copy()
            run2 = run_vec(scored2, prices, cfg)
            drop_metrics = {
                "dropped_etf": drop_code,
                "annual_return": run2["metrics"]["annual_return"],
                "sharpe": run2["metrics"]["sharpe"],
                "max_drawdown": run2["metrics"]["max_drawdown"],
            }

        mid = eq["date"].min() + (eq["date"].max() - eq["date"].min()) / 2
        halves = {}
        for name, mask in [
            ("first_half", eq["date"] <= mid),
            ("second_half", eq["date"] > mid),
            ("oos", eq["date"] >= oos_start),
            ("is", eq["date"] <= train_end),
        ]:
            sub = eq.loc[mask, "return"]
            halves[name] = metrics(sub) if len(sub) else {}

        mom_eq = mom_equity.copy()
        mom_eq["date"] = pd.to_datetime(mom_eq["date"])
        merged = eq.merge(mom_eq[["date", "return"]], on="date", suffixes=("", "_mom"))
        active = merged["return"] - merged["return_mom"]
        incr = {
            "active_ann_approx": float(active.mean() * 252),
            "active_sharpe_approx": float(active.mean() / active.std() * np.sqrt(252)) if active.std() else np.nan,
            "active_total": float(active.sum()),
        }

        return {
            "label": label,
            "top5_etf_by_approx_pnl_contrib": top_etf,
            "top5_etf_selection_counts": sorted(hold_counts.items(), key=lambda x: -x[1])[:5],
            "top5_periods": top_periods,
            "worst5_periods": worst_periods,
            "best_year": best_year,
            "best_year_return": years.get(best_year) if best_year else None,
            "worst_year": worst_year,
            "worst_year_return": years.get(worst_year) if worst_year else None,
            "drop_top_etf": drop_metrics,
            "splits": halves,
            "vs_mom20": incr,
            "headline": {
                "annual_return": exp_row["annual_return"],
                "sharpe": exp_row["sharpe"],
                "max_drawdown": exp_row["max_drawdown"],
            },
        }

    mom_base_eq = by["full_pool_mom_same_range"]["_equity"]
    # both shares on full pool same range
    add_exp(
        "full_pool_both_shares_same_range", full_frame,
        ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D"], [1, -1, -1], [1, 2.306, 1.807], cfg_r1,
    )
    by2 = {r["experiment"]: r for r in experiments_b}
    conc_shares = concentration("both_shares", by2["full_pool_both_shares_same_range"], mom_base_eq)
    conc_c1 = concentration("C1", by2["C1_research_partial_same_range"], mom_base_eq)
    (OUT / "part_d_concentration.json").write_text(
        json.dumps({"both_shares": conc_shares, "C1": conc_c1}, indent=2, default=str),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # Final answers summary
    # ------------------------------------------------------------------
    summary = {
        "q1_is_91pct_a_bug": {
            "answer": "口径差异，不是源数据突然变成91%缺失。",
            "grid_missing_mbr": full_mbr_miss,
            "panel_missing_mbr": panel_mbr_miss,
            "p_margin_missing_given_excluded_full": diag_full["p_margin_missing_given_excluded"],
            "excluded_ratio_full": diag_full["excluded_ratio"],
            "margin_missing_ratio_on_scored_panel": diag_full["margin_missing_ratio"],
            "detail": part_a["interpretation"],
        },
        "q2_c1_improvement_source": {
            "pool_switch_d_ann": deltas["pool_switch_mom"]["d_ann"],
            "add_margin_d_ann": deltas["add_margin_buy_in_pool"]["d_ann"],
            "add_both_margin_d_ann": deltas["add_both_margin_in_pool"]["d_ann"],
            "proxy_correlations_path": str(OUT / "part_b_proxy_correlations.csv"),
        },
        "q3_share_factors_vs_mom_baselines": {
            "mom20": {k: baselines[0][k] for k in ("annual_return", "sharpe", "max_drawdown")},
            "mom6": {k: baselines[1][k] for k in ("annual_return", "sharpe", "max_drawdown")},
            "mom12": {k: baselines[2][k] for k in ("annual_return", "sharpe", "max_drawdown")},
            "mom6_12": {k: baselines[3][k] for k in ("annual_return", "sharpe", "max_drawdown")},
            "both_shares": {
                "annual_return": by2["full_pool_both_shares_same_range"]["annual_return"],
                "sharpe": by2["full_pool_both_shares_same_range"]["sharpe"],
                "max_drawdown": by2["full_pool_both_shares_same_range"]["max_drawdown"],
            },
            "vs_mom_active": conc_shares["vs_mom20"],
            "stability": conc_shares["splits"],
        },
        "outputs": str(OUT),
    }
    (OUT / "final_three_answers.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
