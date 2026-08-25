"""High-dividend, low-volatility, quality-filtered A-share portfolio."""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_backtest.config import StrategyConfig

REQUIRED_COLUMNS = {
    "code",
    "industry",
    "annual_dividend_yield",
    "consecutive_years",
    "volatility",
    "free_cash_flow",
    "earnings_stability",
    "listing_days",
    "average_turnover",
    "is_st",
}


def filter_candidates(snapshot: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Apply transparent hard filters before ranking eligible stocks."""
    missing = REQUIRED_COLUMNS - set(snapshot.columns)
    if missing:
        raise ValueError(f"snapshot missing columns: {sorted(missing)}")
    out = snapshot.copy()
    numeric = [
        "annual_dividend_yield",
        "consecutive_years",
        "volatility",
        "free_cash_flow",
        "earnings_stability",
        "listing_days",
        "average_turnover",
    ]
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="coerce")
    dividend_signal = config.dividend_signal
    if config.variant == "strict_b":
        dividend_signal = "implemented_ttm_yield"
    if dividend_signal not in out:
        raise ValueError(f"snapshot missing configured dividend signal: {dividend_signal}")
    out[dividend_signal] = pd.to_numeric(out[dividend_signal], errors="coerce")
    common = (
        ~out["is_st"].fillna(False).astype(bool)
        & (out["listing_days"] >= config.min_listing_days)
        & (out["average_turnover"] >= config.min_avg_turnover)
        & (out[dividend_signal] >= config.min_dividend_yield)
        & (out[dividend_signal] <= config.max_dividend_yield)
        & (out["volatility"] > 0)
    )
    if "trade_status" in out:
        common &= out["trade_status"].fillna(True).astype(bool)
    if config.excluded_industries:
        common &= ~out["industry"].fillna("未分类").isin(config.excluded_industries)
    if config.variant in {"dividend_quality", "quality_industry"}:
        common &= (
            (out["consecutive_years"] >= config.dividend_years)
            & (out["free_cash_flow"] > 0)
            & out["earnings_stability"].notna()
        )
        if "net_income" in out:
            common &= out["net_income"].isna() | (out["net_income"] > config.min_net_income)
        if "operating_cash_flow" in out:
            common &= out["operating_cash_flow"].isna() | (
                out["operating_cash_flow"] > config.min_operating_cash_flow
            )
        # Advanced fields are optional until quality panels are fully cached.
        if "debt_ratio" in out:
            common &= out["debt_ratio"].isna() | (out["debt_ratio"] <= config.max_debt_ratio)
        if "roe_std" in out:
            common &= out["roe_std"].isna() | (out["roe_std"] <= config.max_roe_std)
    out = out[common].copy()
    return out


def _rank_candidates(candidates: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Prefer larger annual-plan yield, then lower volatility/stabler earnings."""
    out = candidates.copy()
    out["dividend_rank"] = out["annual_dividend_yield"].rank(pct=True, method="average")
    out["low_vol_rank"] = (-out["volatility"]).rank(pct=True, method="average")
    out["stability_rank"] = (-out["earnings_stability"]).rank(pct=True, method="average")
    if config.variant == "dividend":
        out["score"] = out["dividend_rank"]
    elif config.variant in {"dividend_lowvol", "legacy_b_score"}:
        out["score"] = 0.70 * out["dividend_rank"] + 0.30 * out["low_vol_rank"]
    elif config.variant == "dividend_quality":
        out["score"] = 0.75 * out["dividend_rank"] + 0.25 * out["stability_rank"]
    else:
        out["score"] = 0.60 * out["dividend_rank"] + 0.25 * out["low_vol_rank"] + 0.15 * out["stability_rank"]
    return out.sort_values(["score", "annual_dividend_yield"], ascending=False)


def constrained_inverse_volatility_weights(
    holdings: pd.DataFrame, max_industry_weight: float, max_stock_weight: float
) -> pd.Series:
    """Allocate inverse-volatility weights with stock and industry caps.

    Iterative water filling redistributes capped exposure over still-eligible
    names. It raises when requested constraints make a fully invested portfolio
    impossible rather than returning misleading weights.
    """
    if holdings.empty:
        return pd.Series(dtype=float)
    industries = holdings["industry"].fillna("未分类")
    known_industries = industries[industries.ne("未分类")].nunique()
    if known_industries and known_industries * max_industry_weight < 1 - 1e-9:
        raise ValueError("industry cap prevents a fully invested portfolio")

    inv_vol = 1 / holdings["volatility"].clip(lower=1e-6)

    def cap_and_redistribute(base: pd.Series, cap: float, target: float = 1.0) -> pd.Series:
        """Proportionally allocate ``target`` while capping every item."""
        weights = pd.Series(0.0, index=base.index)
        active = base[base > 0].index
        remaining = target
        while len(active) and remaining > 1e-12:
            proposal = base.loc[active] / base.loc[active].sum() * remaining
            capped = proposal[proposal > cap + 1e-12]
            if capped.empty:
                weights.loc[active] = proposal
                remaining = 0.0
                break
            weights.loc[capped.index] = cap
            remaining -= cap * len(capped)
            active = active.difference(capped.index)
        if remaining > 1e-8:
            raise ValueError("stock/industry caps prevent a fully invested portfolio")
        return weights

    # Missing taxonomy must be disclosed, but must not make an otherwise
    # executable portfolio impossible. Unclassified names are capped per stock.
    if industries.eq("未分类").all():
        return cap_and_redistribute(inv_vol, max_stock_weight)
    industry_base = inv_vol.groupby(industries).sum()
    industry_weights = cap_and_redistribute(industry_base, max_industry_weight)
    weights = pd.Series(0.0, index=holdings.index)
    for industry, target in industry_weights.items():
        members = holdings.index[industries.eq(industry)]
        weights.loc[members] = cap_and_redistribute(inv_vol.loc[members], max_stock_weight, target)
    return weights


def select_portfolio(snapshot: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Select the configured number of holdings and attach constrained weights."""
    filtered = filter_candidates(snapshot, config)
    if config.variant == "strict_b":
        dividend_signal = "implemented_ttm_yield"
        cutoff = filtered[dividend_signal].quantile(1 - config.high_dividend_percentile)
        candidates = filtered[filtered[dividend_signal] >= cutoff].sort_values(
            [dividend_signal, "volatility"], ascending=[False, True]
        )
        # Strict sequence: high-dividend screen first; volatility exclusively
        # determines selection inside that screen. Yield is just deterministic
        # tie-breaking for equal volatility.
        candidates = candidates.sort_values(["volatility", dividend_signal], ascending=[True, False])
    else:
        candidates = _rank_candidates(filtered, config)
    # Enforce diversity at selection time, rather than discovering after
    # selection that the industry cap makes the intended portfolio impossible.
    # A higher cap does not force equal industry weights; it sets the maximum
    # number of names initially admitted from each classified industry.
    use_industry_cap = config.variant in {"quality_industry", "strict_b"}
    max_names_per_industry = max(1, int(np.floor(config.top_n * config.max_industry_weight)))
    selected, per_industry = [], {}
    for row in candidates.itertuples():
        industry = row.industry if pd.notna(row.industry) and row.industry != "未分类" else f"未分类:{row.code}"
        if use_industry_cap and per_industry.get(industry, 0) >= max_names_per_industry:
            continue
        selected.append(row.Index)
        per_industry[industry] = per_industry.get(industry, 0) + 1
        if len(selected) == config.top_n:
            break
    holdings = candidates.loc[selected].copy()
    if len(holdings) < config.top_n:
        raise ValueError(
            f"only {len(holdings)} diversified stocks passed filters; need {config.top_n} under industry cap"
        )
    if config.weighting == "equal":
        holdings["weight"] = 1.0 / len(holdings)
    elif use_industry_cap:
        holdings["weight"] = constrained_inverse_volatility_weights(
            holdings, config.max_industry_weight, config.max_stock_weight
        )
    else:
        holdings["weight"] = 1 / holdings["volatility"].clip(lower=1e-6)
        holdings["weight"] /= holdings["weight"].sum()
    return holdings.reset_index(drop=True)
