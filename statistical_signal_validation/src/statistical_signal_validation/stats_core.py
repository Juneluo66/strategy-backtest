"""Statistical primitives: HAC, bootstrap, PSR, DSR, MinTRL.

References (implementation-level, not strategy retuning):
- Newey & West (1987) HAC
- Bailey & López de Prado, Probabilistic Sharpe Ratio / Deflated Sharpe Ratio / MinTRL
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


def align_returns(strategy: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    return pd.concat(
        [strategy.rename("strategy"), benchmark.rename("benchmark")], axis=1
    ).dropna()


def arithmetic_active(strategy: pd.Series, benchmark: pd.Series) -> pd.Series:
    a = align_returns(strategy, benchmark)
    return a["strategy"] - a["benchmark"]


def relative_nav_stats(strategy: pd.Series, benchmark: pd.Series) -> dict:
    a = align_returns(strategy, benchmark)
    nav_s = (1 + a["strategy"]).cumprod()
    nav_b = (1 + a["benchmark"]).cumprod()
    nav_s = nav_s / float(nav_s.iloc[0])
    nav_b = nav_b / float(nav_b.iloc[0])
    rel = nav_s / nav_b
    years = max((a.index.max() - a.index.min()).days / 365.25, 1 / 12)
    final_rel = float(rel.iloc[-1])
    return {
        "final_relative_wealth": final_rel,
        "relative_cagr": float(final_rel ** (1 / years) - 1) if final_rel > 0 else np.nan,
        "strategy_cagr": float(nav_s.iloc[-1] ** (1 / years) - 1),
        "benchmark_cagr": float(nav_b.iloc[-1] ** (1 / years) - 1),
        "cagr_edge": float(nav_s.iloc[-1] ** (1 / years) - 1) - float(nav_b.iloc[-1] ** (1 / years) - 1),
        "final_strategy_wealth": float(nav_s.iloc[-1]),
        "final_benchmark_wealth": float(nav_b.iloc[-1]),
        "n_obs": int(len(a)),
        "years": float(years),
        "start": str(a.index.min().date()),
        "end": str(a.index.max().date()),
    }


def information_ratio(active: pd.Series, periods_per_year: float = 252.0) -> float:
    a = active.dropna()
    if len(a) < 5 or a.std(ddof=1) == 0:
        return float("nan")
    return float(a.mean() / a.std(ddof=1) * np.sqrt(periods_per_year))


def newey_west_mean_tstat(x: pd.Series, lags: Optional[int] = None) -> dict:
    """HAC t-stat for H0: E[x]=0 (Newey-West with Bartlett kernel)."""
    a = x.dropna().to_numpy(dtype=float)
    n = len(a)
    if n < 10:
        return {"mean": np.nan, "se_hac": np.nan, "t_stat": np.nan, "p_value": np.nan, "lags": lags, "n": n}
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2 / 9)))
        lags = max(lags, 1)
    mu = float(a.mean())
    u = a - mu
    gamma0 = float(np.dot(u, u) / n)
    hac = gamma0
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        gamma = float(np.dot(u[lag:], u[:-lag]) / n)
        hac += 2.0 * w * gamma
    se = np.sqrt(max(hac, 0.0) / n)
    t = mu / se if se > 0 else np.nan
    p = float(2 * (1 - stats.t.cdf(abs(t), df=max(n - 1, 1)))) if np.isfinite(t) else np.nan
    return {
        "mean": mu,
        "mean_ann": mu * 252.0,
        "se_hac": float(se),
        "t_stat": float(t) if np.isfinite(t) else np.nan,
        "p_value": p,
        "lags": int(lags),
        "n": int(n),
    }


def active_moments(active: pd.Series) -> dict:
    a = active.dropna()
    if len(a) < 5:
        return {"skewness": np.nan, "excess_kurtosis": np.nan, "acf1": np.nan, "acf5": np.nan, "acf21": np.nan}
    acf1 = float(a.autocorr(lag=1)) if len(a) > 2 else np.nan
    acf5 = float(a.autocorr(lag=5)) if len(a) > 6 else np.nan
    acf21 = float(a.autocorr(lag=21)) if len(a) > 22 else np.nan
    return {
        "skewness": float(stats.skew(a, bias=False)),
        "excess_kurtosis": float(stats.kurtosis(a, fisher=True, bias=False)),
        "acf1": acf1,
        "acf5": acf5,
        "acf21": acf21,
        "std": float(a.std(ddof=1)),
        "mean": float(a.mean()),
    }


def effective_independent_n(active: pd.Series) -> dict:
    """n_eff ≈ n * (1-ρ)/(1+ρ) using lag-1 autocorrelation of active returns."""
    a = active.dropna()
    n = len(a)
    if n < 5:
        return {"n": n, "rho1": np.nan, "n_eff": np.nan}
    rho = float(a.autocorr(lag=1))
    if not np.isfinite(rho) or abs(rho) >= 0.999:
        neff = np.nan
    else:
        neff = n * (1 - rho) / (1 + rho)
        neff = float(max(neff, 1.0))
    return {"n": int(n), "rho1": rho, "n_eff": neff}


def _block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    picks = []
    while len(picks) < n:
        start = int(rng.integers(0, max(n - block + 1, 1)))
        picks.extend(range(start, min(start + block, n)))
    return np.asarray(picks[:n], dtype=int)


def block_bootstrap_edges(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    block: int,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict:
    """Bootstrap distribution of CAGR edge and final relative wealth."""
    a = align_returns(strategy, benchmark)
    s = a["strategy"].to_numpy()
    b = a["benchmark"].to_numpy()
    n = len(s)
    years = n / 252.0
    rng = np.random.default_rng(seed)
    cagr_edges = []
    final_rels = []
    for _ in range(n_boot):
        idx = _block_indices(n, block, rng)
        ss, bb = s[idx], b[idx]
        nav_s = np.cumprod(1.0 + ss)
        nav_b = np.cumprod(1.0 + bb)
        # rebase
        nav_s = nav_s / nav_s[0]
        nav_b = nav_b / nav_b[0]
        cagr_s = nav_s[-1] ** (1 / years) - 1
        cagr_b = nav_b[-1] ** (1 / years) - 1
        cagr_edges.append(cagr_s - cagr_b)
        final_rels.append(nav_s[-1] / nav_b[-1])
    ce = np.asarray(cagr_edges)
    fr = np.asarray(final_rels)
    return {
        "block": int(block),
        "n_boot": int(n_boot),
        "prob_cagr_edge_gt_0": float((ce > 0).mean()),
        "prob_final_rel_gt_1": float((fr > 1).mean()),
        "cagr_edge_mean": float(ce.mean()),
        "cagr_edge_p05": float(np.quantile(ce, 0.05)),
        "cagr_edge_p50": float(np.quantile(ce, 0.50)),
        "cagr_edge_p95": float(np.quantile(ce, 0.95)),
        "final_rel_mean": float(fr.mean()),
        "final_rel_p05": float(np.quantile(fr, 0.05)),
        "final_rel_p50": float(np.quantile(fr, 0.50)),
        "final_rel_p95": float(np.quantile(fr, 0.95)),
    }


def observed_sharpe(returns: pd.Series, periods_per_year: float = 252.0) -> float:
    r = returns.dropna()
    if len(r) < 5 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year))


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    *,
    sr_benchmark: float = 0.0,
    periods_per_year: float = 252.0,
) -> dict:
    """Bailey & López de Prado PSR: P(true SR > sr_benchmark | observed sample)."""
    r = returns.dropna()
    n = len(r)
    if n < 10:
        return {"psr": np.nan, "sr_obs": np.nan, "sr_benchmark": sr_benchmark, "n": n}
    sr = observed_sharpe(r, periods_per_year) / np.sqrt(periods_per_year)  # per-period SR
    # moments on per-period returns
    skew = float(stats.skew(r, bias=False))
    kurt = float(stats.kurtosis(r, fisher=False, bias=False))  # non-excess
    # σ(SR) ≈ sqrt( (1 - skew*SR + (kurt-1)/4 * SR^2) / (n-1) )
    sr_star = sr_benchmark / np.sqrt(periods_per_year)
    numer = 1 - skew * sr + ((kurt - 1) / 4.0) * (sr ** 2)
    denom = max(n - 1, 1)
    se = np.sqrt(max(numer, 1e-16) / denom)
    z = (sr - sr_star) / se if se > 0 else np.nan
    psr = float(stats.norm.cdf(z)) if np.isfinite(z) else np.nan
    return {
        "psr": psr,
        "sr_obs_ann": float(sr * np.sqrt(periods_per_year)),
        "sr_benchmark_ann": float(sr_benchmark),
        "z": float(z) if np.isfinite(z) else np.nan,
        "skew": skew,
        "kurtosis": kurt,
        "n": int(n),
    }


def deflated_sharpe_ratio(
    returns: pd.Series,
    *,
    n_trials: int,
    periods_per_year: float = 252.0,
    variance_trials: Optional[float] = None,
) -> dict:
    """
    Deflated Sharpe Ratio (Bailey & López de Prado).

    Compares observed SR to the expected maximum SR under n_trials independent
    tests (Euler-Mascheroni approximation), then applies PSR vs that threshold.
    """
    r = returns.dropna()
    n = len(r)
    if n < 10 or n_trials < 1:
        return {"dsr": np.nan, "sr_obs": np.nan, "sr_expected_max": np.nan, "n_trials": n_trials}
    sr_obs = observed_sharpe(r, periods_per_year)
    # Expected max of n_trials N(0,1) approx for standardized SRs, then scale by σ(SR)
    # Following BL: E[max SR] ≈ sqrt(V) * ((1-γ)*Z^{-1}(1-1/N) + γ*Z^{-1}(1-1/(N*e)))
    # Use V ≈ (1 / (n-1)) under null for per-period; work in annualized space carefully.
    # Practical implementation: expected max of N iid SR ~ N(0, se^2) where se is null SE of annualized SR.
    se_null = np.sqrt(periods_per_year / max(n - 1, 1))  # approx under null mean0 unit?
    # Better: per-period SR se under null ≈ 1/sqrt(n-1); annualize later.
    gamma = 0.5772156649
    N = float(n_trials)
    z1 = stats.norm.ppf(1 - 1.0 / N)
    z2 = stats.norm.ppf(1 - 1.0 / (N * np.e))
    # Expected max of N standard normals
    emax = (1 - gamma) * z1 + gamma * z2
    if variance_trials is None:
        # Variance of SR estimator under null (annualized)
        variance_trials = se_null ** 2
    sr_expected_max = float(np.sqrt(variance_trials) * emax)
    # PSR where benchmark is expected max SR
    psr = probabilistic_sharpe_ratio(r, sr_benchmark=sr_expected_max, periods_per_year=periods_per_year)
    return {
        "dsr": psr["psr"],
        "sr_obs_ann": sr_obs,
        "sr_expected_max_ann": sr_expected_max,
        "n_trials": int(n_trials),
        "variance_trials": float(variance_trials),
        "n": int(n),
        "psr_vs_expected_max": psr["psr"],
    }


def min_track_record_length(
    returns: pd.Series,
    *,
    sr_benchmark: float = 0.0,
    conf: float = 0.95,
    periods_per_year: float = 252.0,
) -> dict:
    """Minimum Track Record Length (years) to conclude SR > sr_benchmark at confidence."""
    r = returns.dropna()
    if len(r) < 10:
        return {"min_trl_years": np.nan, "observed_years": np.nan, "sufficient": False}
    sr = observed_sharpe(r, periods_per_year) / np.sqrt(periods_per_year)
    sr_star = sr_benchmark / np.sqrt(periods_per_year)
    skew = float(stats.skew(r, bias=False))
    kurt = float(stats.kurtosis(r, fisher=False, bias=False))
    z = stats.norm.ppf(conf)
    # MinTRL formula (per-period observations):
    # n* = 1 + (1 - skew*sr + ((kurt-1)/4)*sr^2) * (z / (sr - sr*))^2
    if abs(sr - sr_star) < 1e-12:
        n_star = np.inf
    else:
        numer = 1 - skew * sr + ((kurt - 1) / 4.0) * (sr ** 2)
        n_star = 1 + numer * (z / (sr - sr_star)) ** 2
    years_needed = float(n_star / periods_per_year) if np.isfinite(n_star) else np.inf
    observed_years = len(r) / periods_per_year
    return {
        "min_trl_years": years_needed,
        "observed_years": float(observed_years),
        "sufficient": bool(np.isfinite(years_needed) and observed_years >= years_needed),
        "sr_obs_ann": float(sr * np.sqrt(periods_per_year)),
        "sr_benchmark_ann": float(sr_benchmark),
        "confidence": conf,
    }


def multiple_testing_adjustments(p_values: dict[str, float]) -> dict:
    """Bonferroni and Benjamini-Hochberg FDR on a named p-value dict."""
    items = [(k, v) for k, v in p_values.items() if v is not None and np.isfinite(v)]
    m = len(items)
    if m == 0:
        return {"bonferroni": {}, "bh_fdr": {}, "m": 0}
    bonf = {k: min(v * m, 1.0) for k, v in items}
    # BH
    ordered = sorted(items, key=lambda kv: kv[1])
    bh = {}
    prev = 1.0
    for i, (k, p) in enumerate(reversed(ordered), start=1):
        rank = m - i + 1
        val = min(prev, p * m / rank)
        prev = val
        bh[k] = float(min(val, 1.0))
    # fill in order
    return {"bonferroni": bonf, "bh_fdr": bh, "m": m}


def power_years_for_cagr_edge(
    *,
    edge: float,
    tracking_error_ann: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict:
    """
    Approximate years needed to detect CAGR/active edge with two-sided t-test
    on annualized IR = edge / TE.
    """
    if tracking_error_ann <= 0 or not np.isfinite(edge):
        return {"years_needed": np.nan}
    ir = abs(edge) / tracking_error_ann
    if ir < 1e-12:
        return {"years_needed": np.inf, "information_ratio": 0.0}
    # For annual observations of active return ~ N(edge, TE^2):
    # n ≈ ((z_{1-α/2}+z_power) / IR)^2
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_p = stats.norm.ppf(power)
    n = ((z_a + z_p) / ir) ** 2
    return {
        "years_needed": float(n),
        "information_ratio": float(ir),
        "edge": float(edge),
        "tracking_error_ann": float(tracking_error_ann),
        "alpha": alpha,
        "power": power,
    }


def full_relative_battery(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    n_trials: int,
    label: str,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict:
    """Complete relative statistical battery for one strategy/benchmark pair."""
    active = arithmetic_active(strategy, benchmark)
    rel = relative_nav_stats(strategy, benchmark)
    moments = active_moments(active)
    neff = effective_independent_n(active)
    hac = newey_west_mean_tstat(active)
    ir = information_ratio(active)
    te = float(active.std(ddof=1) * np.sqrt(252)) if active.std(ddof=1) else np.nan
    boots = {
        "1m": block_bootstrap_edges(strategy, benchmark, block=21, n_boot=n_boot, seed=seed),
        "3m": block_bootstrap_edges(strategy, benchmark, block=63, n_boot=n_boot, seed=seed + 1),
        "12m": block_bootstrap_edges(strategy, benchmark, block=252, n_boot=n_boot, seed=seed + 2),
    }
    # PSR/DSR/MinTRL on active returns (skill vs 0) and on strategy absolute returns
    psr_active = probabilistic_sharpe_ratio(active, sr_benchmark=0.0)
    dsr_active = deflated_sharpe_ratio(active, n_trials=n_trials)
    mintrl_active = min_track_record_length(active, sr_benchmark=0.0)
    psr_abs = probabilistic_sharpe_ratio(strategy.dropna(), sr_benchmark=0.0)
    dsr_abs = deflated_sharpe_ratio(strategy.dropna(), n_trials=n_trials)
    power = power_years_for_cagr_edge(edge=rel["cagr_edge"], tracking_error_ann=te)
    return {
        "label": label,
        "relative_nav": rel,
        "arithmetic_active_mean_ann": hac["mean_ann"],
        "information_ratio": ir,
        "tracking_error_ann": te,
        "newey_west": hac,
        "moments": moments,
        "effective_n": neff,
        "bootstrap": boots,
        "psr_active": psr_active,
        "dsr_active": dsr_active,
        "min_trl_active": mintrl_active,
        "psr_absolute": psr_abs,
        "dsr_absolute": dsr_abs,
        "power_years": power,
    }
