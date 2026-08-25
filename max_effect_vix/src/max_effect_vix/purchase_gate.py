"""Purchase-gate analysis on frozen HISTORICAL_SP500_APPROX evidence only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .artifacts import new_run_directory
from .backtest import run_backtest
from .config import MaxEffectConfig, load_config
from .data import load_benchmark, load_pilot
from .factors import max_factor, monthly_signal_dates
from .metrics import performance_report, window_reports
from .status import research_status
from .universe_provider import load_historical_provider
from .validation import (
    factor_regression,
    load_ken_french_factors,
    monthly_ic_table,
)

# Frozen for this gate only; not used to retune the strategy.
GATE_WINDOWS = {
    "P1_2015_2018": ("2015-01-01", "2018-12-31"),
    "P2_2019_2022": ("2019-01-01", "2022-12-31"),
    "P3_2023_2026": ("2023-01-01", "2026-12-31"),
}


def _run_leg(config: MaxEffectConfig, selection: str):
    opens, closes, volumes, vix = load_pilot(config.cache_dir)
    benchmark = load_benchmark(config.cache_dir, config.raw["benchmark"])
    provider = load_historical_provider(config.cache_dir)
    kwargs = config.raw
    results, holdings, trades, exits = run_backtest(
        opens,
        closes,
        volumes,
        vix,
        lookback=kwargs["signal_lookback_days"],
        top_returns=kwargs["top_returns"],
        min_dollar_volume=kwargs["min_dollar_volume"],
        portfolio_decile=kwargs["portfolio_decile"],
        max_portfolio_size=kwargs["max_portfolio_size"],
        vix_mode="none",
        one_way_bps=kwargs["costs"]["one_way_bps"],
        annual_margin_rate=kwargs["costs"]["annual_margin_rate"],
        benchmark=benchmark,
        factor_variant="raw",
        volatility_lookback_days=kwargs["neutralization"]["volatility_lookback_days"],
        beta_lookback_days=kwargs["neutralization"]["beta_lookback_days"],
        beta_min_observations=kwargs["neutralization"]["beta_min_observations"],
        winsor_limits=tuple(kwargs["neutralization"]["winsor_limits"]),
        annual_spy_borrow_rate=kwargs["costs"]["annual_spy_borrow_rate"],
        membership_on=provider.symbols_on,
        selection=selection,
    )
    metrics = performance_report(results, trades, benchmark)
    market_beta = _market_beta(results["net_return"], benchmark)
    return {
        "results": results,
        "holdings": holdings,
        "trades": trades,
        "exits": exits,
        "metrics": metrics,
        "market_beta": market_beta,
        "benchmark": benchmark,
        "opens": opens,
        "closes": closes,
        "provider": provider,
    }


def _invert_leg(leg: dict) -> dict:
    """Economic short of the high-MAX long book (ignore borrow beyond existing cost model)."""
    results = leg["results"].copy()
    results["gross_return"] = -results["gross_return"]
    results["net_return"] = -results["net_return"]
    metrics = performance_report(results, leg["trades"], leg["benchmark"])
    market_beta = _market_beta(results["net_return"], leg["benchmark"])
    return {"results": results, "trades": leg["trades"], "metrics": metrics, "market_beta": market_beta}


def _market_beta(returns: pd.Series, benchmark: pd.Series) -> float:
    aligned = pd.concat(
        [returns.rename("y"), benchmark.reindex(returns.index).pct_change(fill_method=None).rename("m")],
        axis=1,
    ).dropna()
    if len(aligned) < 60 or aligned["m"].var() == 0:
        return float("nan")
    return float(aligned["y"].cov(aligned["m"]) / aligned["m"].var())


def _period_ic(closes: pd.DataFrame, provider, config: dict, start: str, end: str) -> float:
    returns = closes.pct_change(fill_method=None)
    signals = returns.apply(
        max_factor, lookback=config["signal_lookback_days"], top_returns=config["top_returns"]
    )
    signal_dates = list(monthly_signal_dates(closes.index))
    if len(signal_dates) < 3:
        return float("nan")
    forward = pd.DataFrame(index=signal_dates[:-1], columns=closes.columns, dtype=float)
    for idx, date in enumerate(signal_dates[:-1]):
        nxt = signal_dates[idx + 1]
        forward.loc[date] = closes.loc[nxt] / closes.loc[date] - 1
    panel = signals.loc[forward.index].copy()
    for date in panel.index:
        members = provider.symbols_on(date)
        panel.loc[date] = panel.loc[date].where(panel.columns.isin(list(members)))
        forward.loc[date] = forward.loc[date].where(forward.columns.isin(list(members)))
    table = monthly_ic_table(panel, forward)
    if table.empty:
        return float("nan")
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    dates = pd.to_datetime(table["date"])
    sliced = table.loc[(dates >= start_ts) & (dates <= end_ts)]
    return float(sliced["ic"].mean()) if not sliced.empty else float("nan")


def _ff3_table(results: pd.DataFrame, benchmark: pd.Series) -> dict:
    factors = load_ken_french_factors()
    monthly = results["net_return"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
    if factors.empty or "RF" not in factors.columns:
        return {"status": "FACTORS_UNAVAILABLE"}
    excess = monthly - factors.reindex(monthly.index)["RF"].fillna(0.0)
    ff3 = factors[["MKT_RF", "SMB", "HML"]]
    result = factor_regression(excess, ff3)
    return {
        "status": "OK",
        "n_months": result["n"],
        "alpha_monthly": result["alpha"],
        "alpha_annualized": result.get("alpha_annualized"),
        "alpha_t_stat": result.get("alpha_t_stat", result.get("t_stat")),
        "MKT_RF": result["loadings"].get("MKT_RF"),
        "MKT_RF_t": result["loading_t_stats"].get("MKT_RF"),
        "SMB": result["loadings"].get("SMB"),
        "SMB_t": result["loading_t_stats"].get("SMB"),
        "HML": result["loadings"].get("HML"),
        "HML_t": result["loading_t_stats"].get("HML"),
    }


def run_purchase_gate(config: Optional[MaxEffectConfig] = None) -> Path:
    config = config or load_config()
    status = research_status(historical_membership=True)
    directory = new_run_directory(config, "purchase_gate", status["DATA_TIER"], status)

    long_full = _run_leg(config, "low")
    high_long = _run_leg(config, "high")
    short_full = _invert_leg(high_long)
    ff3 = _ff3_table(long_full["results"], long_full["benchmark"])

    window_metrics = window_reports(
        long_full["results"], long_full["trades"], long_full["benchmark"], GATE_WINDOWS
    )
    period_rows = []
    for name, (start, end) in GATE_WINDOWS.items():
        wm = window_metrics[name]
        ic = _period_ic(long_full["closes"], long_full["provider"], config.raw, start, end)
        period_rows.append(
            {
                "period": name,
                "start": start,
                "end": end,
                "gross_sharpe": wm.get("gross_sharpe"),
                "net_sharpe": wm.get("net_sharpe"),
                "gross_max_drawdown": wm.get("gross_max_drawdown"),
                "net_max_drawdown": wm.get("net_max_drawdown"),
                "mean_ic": ic,
                "one_way_turnover": wm.get("one_way_turnover"),
                "annualized_turnover": wm.get("annualized_turnover"),
            }
        )
    periods = pd.DataFrame(period_rows)

    legs = pd.DataFrame(
        [
            {
                "leg": "long_low_MAX",
                "gross_cagr": long_full["metrics"].get("gross_cagr"),
                "net_cagr": long_full["metrics"].get("net_cagr"),
                "gross_sharpe": long_full["metrics"].get("gross_sharpe"),
                "net_sharpe": long_full["metrics"].get("net_sharpe"),
                "market_beta": long_full["market_beta"],
            },
            {
                "leg": "short_high_MAX",
                "gross_cagr": short_full["metrics"].get("gross_cagr"),
                "net_cagr": short_full["metrics"].get("net_cagr"),
                "gross_sharpe": short_full["metrics"].get("gross_sharpe"),
                "net_sharpe": short_full["metrics"].get("net_sharpe"),
                "market_beta": short_full["market_beta"],
                "note": "economic short = -1 * long high-MAX book",
            },
        ]
    )

    # Long-short: long low-MAX + short high-MAX.
    aligned = pd.concat(
        [
            long_full["results"]["net_return"].rename("long"),
            short_full["results"]["net_return"].rename("short"),
        ],
        axis=1,
    ).dropna()
    ls = aligned["long"] + aligned["short"]
    ls_sharpe = float(ls.mean() / ls.std(ddof=1) * np.sqrt(252)) if ls.std(ddof=1) else float("nan")

    decision, support, oppose = _decide(ff3, periods, legs, long_full["metrics"], ls_sharpe, status)

    # Which leg drives returns?
    long_cagr = long_full["metrics"].get("net_cagr") or 0.0
    short_cagr = short_full["metrics"].get("net_cagr") or 0.0
    if long_cagr > 0 and short_cagr <= 0:
        leg_driver = "long_low_MAX"
    elif short_cagr > 0 and long_cagr <= 0:
        leg_driver = "short_high_MAX"
    elif long_cagr > 0 and short_cagr > 0:
        leg_driver = "long_low_MAX" if long_cagr >= short_cagr else "short_high_MAX"
    else:
        leg_driver = "neither"
    support.append(
        f"Leg attribution (net CAGR): long_low_MAX={long_cagr:.4f}, short_high_MAX={short_cagr:.4f}; "
        f"primary driver={leg_driver}."
    )

    payload = {
        "status": status,
        "frozen_parameters": {
            "top_returns": config.raw["top_returns"],
            "signal_lookback_days": config.raw["signal_lookback_days"],
            "portfolio_decile": config.raw["portfolio_decile"],
            "max_portfolio_size": config.raw["max_portfolio_size"],
            "one_way_bps": config.raw["costs"]["one_way_bps"],
        },
        "ff3": ff3,
        "periods": period_rows,
        "legs": legs.to_dict(orient="records"),
        "leg_driver": leg_driver,
        "long_short_net_sharpe": ls_sharpe,
        "decision": decision,
        "support": support,
        "oppose": oppose,
    }
    (directory / "purchase_gate.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    periods.to_csv(directory / "subperiod_metrics.csv", index=False)
    legs.to_csv(directory / "leg_metrics.csv", index=False)
    pd.DataFrame(
        [
            {"factor": "alpha", "coef": ff3.get("alpha_monthly"), "t_stat": ff3.get("alpha_t_stat")},
            {"factor": "MKT_RF", "coef": ff3.get("MKT_RF"), "t_stat": ff3.get("MKT_RF_t")},
            {"factor": "SMB", "coef": ff3.get("SMB"), "t_stat": ff3.get("SMB_t")},
            {"factor": "HML", "coef": ff3.get("HML"), "t_stat": ff3.get("HML_t")},
        ]
    ).to_csv(directory / "ff3_full.csv", index=False)

    report = _render_markdown(payload)
    (directory / "PURCHASE_GATE.md").write_text(report, encoding="utf-8")
    (config.reports_dir / "PURCHASE_GATE.md").write_text(report, encoding="utf-8")
    return directory


def _decide(ff3, periods, legs, long_metrics, ls_sharpe, status) -> tuple[str, list[str], list[str]]:
    support: list[str] = []
    oppose: list[str] = []

    net_sharpe = long_metrics.get("net_sharpe")
    if isinstance(net_sharpe, (int, float)) and np.isfinite(net_sharpe) and net_sharpe > 0.3:
        support.append(f"Full-sample after-cost long-only Sharpe is {net_sharpe:.3f} (>0.3).")
    else:
        oppose.append(f"Full-sample after-cost Sharpe is weak or missing ({net_sharpe}).")

    nets = [row["net_sharpe"] for row in periods.to_dict("records")]
    ics = [row["mean_ic"] for row in periods.to_dict("records")]
    periods_ok = all(isinstance(x, (int, float)) and np.isfinite(x) and x > 0 for x in nets)
    ic_negative = all(isinstance(x, (int, float)) and np.isfinite(x) and x < 0 for x in ics)

    if periods_ok:
        support.append(f"All three frozen subperiods have positive net Sharpe: {[round(x, 3) for x in nets]}.")
    else:
        oppose.append(f"Subperiod net Sharpes are not uniformly positive: {nets}.")
    if any(isinstance(x, (int, float)) and np.isfinite(x) and x < 0 for x in nets):
        oppose.append("At least one frozen subperiod has negative net Sharpe; edge is regime-dependent.")

    if ic_negative:
        support.append(
            f"All subperiod mean ICs are negative (high MAX → lower forward returns): {[round(x, 4) for x in ics]}."
        )
    else:
        oppose.append(f"Cross-sectional IC is not consistently negative across subperiods: {ics}.")

    smb_pos_sig = False
    alpha_pos_sig = False
    if ff3.get("status") == "OK":
        smb = ff3.get("SMB")
        smb_t = ff3.get("SMB_t") or 0.0
        alpha = ff3.get("alpha_monthly")
        alpha_t = ff3.get("alpha_t_stat") or 0.0
        support.append(
            f"FF3: alpha={alpha:.4f} (t={alpha_t:.2f}), "
            f"MKT={ff3.get('MKT_RF'):.3f} (t={ff3.get('MKT_RF_t'):.2f}), "
            f"SMB={smb:.3f} (t={smb_t:.2f}), HML={ff3.get('HML'):.3f} (t={ff3.get('HML_t'):.2f})."
        )
        if abs(smb_t) >= 1.96 and smb > 0:
            smb_pos_sig = True
            oppose.append(
                f"SMB loading is positive and significant ({smb:.3f}, t={smb_t:.2f}); size confound is first-order."
            )
        elif abs(smb_t) >= 1.96 and smb < 0:
            support.append(f"SMB loading is negative and significant ({smb:.3f}, t={smb_t:.2f}); not a small-cap bet.")
        else:
            oppose.append(f"SMB loading is insignificant (SMB={smb}, t={smb_t}); size exposure not rejected.")

        if abs(alpha_t) >= 1.96 and alpha is not None and alpha > 0:
            alpha_pos_sig = True
            support.append(f"FF3 alpha is positive and significant (t={alpha_t:.2f}).")
        else:
            oppose.append(f"FF3 alpha is not significantly positive (alpha={alpha}, t={alpha_t}).")
    else:
        oppose.append("FF3 factors unavailable; cannot claim factor-adjusted alpha.")

    long_net = float(legs.loc[legs["leg"] == "long_low_MAX", "net_sharpe"].iloc[0])
    short_net = float(legs.loc[legs["leg"] == "short_high_MAX", "net_sharpe"].iloc[0])
    long_cagr = float(legs.loc[legs["leg"] == "long_low_MAX", "net_cagr"].iloc[0])
    short_cagr = float(legs.loc[legs["leg"] == "short_high_MAX", "net_cagr"].iloc[0])
    if np.isfinite(long_net) and long_net > 0.3:
        support.append(f"Long low-MAX net Sharpe is {long_net:.3f}.")
    if np.isfinite(short_net) and short_net > 0.2:
        support.append(f"Short high-MAX net Sharpe is {short_net:.3f} (economic short of high-MAX book).")
    elif np.isfinite(short_net) and short_net < 0:
        oppose.append(
            f"Short high-MAX net Sharpe is negative ({short_net:.3f}); short leg does not contribute positively."
        )
    if np.isfinite(ls_sharpe) and ls_sharpe > 0.3:
        support.append(f"Long+short (low long + high short) net Sharpe is {ls_sharpe:.3f}.")
    else:
        oppose.append(f"Combined long+short net Sharpe is weak ({ls_sharpe}).")
    if np.isfinite(long_cagr) and np.isfinite(short_cagr):
        if long_cagr > 0 and short_cagr <= 0:
            oppose.append(
                f"Return is long-leg dominated (long net CAGR {long_cagr:.4f} vs short {short_cagr:.4f}); "
                "classic MAX short-lottery story is weak on this sample."
            )
        elif short_cagr > long_cagr and short_cagr > 0:
            support.append(
                f"Short high-MAX contributes more net CAGR ({short_cagr:.4f}) than long low-MAX ({long_cagr:.4f})."
            )

    oppose.append(
        f"DATA_TIER={status['DATA_TIER']}; SURVIVORSHIP_BIAS={status['SURVIVORSHIP_BIAS']} (reduced, not eliminated)."
    )
    oppose.append("PIT_VALIDATED=false; size neutralization remains BLOCKED_BY_PIT_MARKET_CAP.")
    oppose.append("DELISTING_RETURN=UNAVAILABLE on Yahoo / index-exit proxy.")
    oppose.append("Do not purchase merely because free Sharpe is high.")

    looks_coherent = isinstance(net_sharpe, (int, float)) and np.isfinite(net_sharpe) and net_sharpe > 0.3 and periods_ok
    classic_max_ok = ic_negative and np.isfinite(short_net) and short_net > 0
    factor_kills = (
        ff3.get("status") == "OK"
        and not alpha_pos_sig
        and ((ff3.get("alpha_monthly") or 0) <= 0 or abs(ff3.get("alpha_t_stat") or 0) < 1.96)
    )
    # Negative significant SMB already rejects "small-cap lottery" as the free-data confound.
    size_already_cleared_on_free = (
        ff3.get("status") == "OK"
        and (ff3.get("SMB") or 0) < 0
        and abs(ff3.get("SMB_t") or 0) >= 1.96
    )

    if factor_kills and isinstance(net_sharpe, (int, float)) and net_sharpe > 0.3:
        decision = (
            "NO — free after-cost Sharpe is positive, but FF3 alpha is not significantly positive. "
            "Buying Sharadar would mainly re-price a factor/risk story, not settle an unresolved "
            "independent-alpha claim. Do not purchase on this evidence."
        )
    elif not classic_max_ok and looks_coherent:
        decision = (
            "NO — long low-MAX looks fine in isolation, but frozen IC and/or the short high-MAX leg "
            "fail the classic MAX anomaly pattern. Paid PIT/size data is not justified to chase a "
            "long-only Sharpe that already fails the anomaly identification test."
        )
    elif size_already_cleared_on_free and status["SIZE_NEUTRAL"] == "BLOCKED_BY_PIT_MARKET_CAP":
        decision = (
            "NO — SMB loading is already significantly negative on free data, so size is not the "
            "binding confound that Sharadar size-neutral would uniquely resolve. Remaining gaps "
            "(PIT membership, delisting) do not outweigh the weak alpha/IC/short-leg evidence."
        )
    elif looks_coherent and smb_pos_sig:
        decision = (
            "YES — buy one-month Sharadar only as a falsification budget for size-neutral + PIT. "
            "Free Sharpe is not proof of alpha; significant positive SMB makes size the binding uncertainty."
        )
    elif looks_coherent and classic_max_ok and alpha_pos_sig:
        decision = (
            "YES — buy one-month Sharadar as a falsification budget for PIT membership + delisting; "
            "free evidence coheres as MAX-like with significant alpha, but PIT_VALIDATED remains false."
        )
    elif not looks_coherent:
        decision = (
            "NO — free HISTORICAL_SP500_APPROX evidence is too weak or unstable under frozen subperiods "
            "to justify Sharadar spend."
        )
    else:
        decision = (
            "NO — mixed free evidence; Sharadar would help PIT/delisting mechanically, but results are "
            "not strong or clean enough to make a one-month purchase clearly decision-relevant."
        )

    return decision, support, oppose


def _render_markdown(payload: dict) -> str:
    ff3 = payload["ff3"]
    lines = [
        "# PURCHASE_GATE — Sharadar one-month decision",
        "",
        "## Status",
        "",
        f"- DATA_TIER: `{payload['status']['DATA_TIER']}`",
        f"- SURVIVORSHIP_BIAS: `{payload['status']['SURVIVORSHIP_BIAS']}`",
        f"- PIT_VALIDATED: `{payload['status']['PIT_VALIDATED']}`",
        f"- SIZE_NEUTRAL: `{payload['status']['SIZE_NEUTRAL']}`",
        "",
        "Frozen parameters (no retuning): "
        f"MAX{payload['frozen_parameters']['top_returns']} / "
        f"lookback {payload['frozen_parameters']['signal_lookback_days']} / "
        f"decile {payload['frozen_parameters']['portfolio_decile']} / "
        f"cap {payload['frozen_parameters']['max_portfolio_size']} / "
        f"{payload['frozen_parameters']['one_way_bps']} bp one-way.",
        "",
        "## 1. FF3 full regression (long low-MAX, after costs)",
        "",
    ]
    if ff3.get("status") != "OK":
        lines.append("FF3 factors unavailable.")
    else:
        lines.extend(
            [
                f"- N months: {ff3['n_months']}",
                f"- alpha (monthly): {ff3['alpha_monthly']:.6f} (t={ff3['alpha_t_stat']:.3f})",
                f"- alpha (ann.): {ff3['alpha_annualized']:.4f}",
                f"- MKT_RF: {ff3['MKT_RF']:.4f} (t={ff3['MKT_RF_t']:.3f})",
                f"- SMB: {ff3['SMB']:.4f} (t={ff3['SMB_t']:.3f})  ← size-confound check",
                f"- HML: {ff3['HML']:.4f} (t={ff3['HML_t']:.3f})",
                "",
            ]
        )
    lines.extend(["## 2. Frozen-parameter subperiods", "", "| Period | Gross Sharpe | Net Sharpe | Mean IC | Max DD (net) | Ann. turnover |", "|---|---:|---:|---:|---:|---:|"])
    for row in payload["periods"]:
        lines.append(
            f"| {row['period']} | {row['gross_sharpe']:.3f} | {row['net_sharpe']:.3f} | "
            f"{row['mean_ic']:.4f} | {row['net_max_drawdown']:.3f} | {row['annualized_turnover']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## 3. Long low-MAX vs short high-MAX legs",
            "",
            "| Leg | Gross CAGR | Net CAGR | Gross Sharpe | Net Sharpe | Market beta |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["legs"]:
        lines.append(
            f"| {row['leg']} | {row['gross_cagr']:.4f} | {row['net_cagr']:.4f} | "
            f"{row['gross_sharpe']:.3f} | {row['net_sharpe']:.3f} | {row['market_beta']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"Long+short (low long + high short) net Sharpe: **{payload['long_short_net_sharpe']:.3f}**",
            "",
            f"Primary return driver: `{payload.get('leg_driver', 'n/a')}`",
            "",
            "Note: `short_high_MAX` is the economic short of the high-MAX long book (−returns).",
            "",
            "## 4. Supporting evidence",
            "",
        ]
    )
    for item in payload["support"]:
        lines.append(f"- {item}")
    lines.extend(["", "## 5. Opposing evidence", ""])
    for item in payload["oppose"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 6. Decision",
            "",
            f"**{payload['decision']}**",
            "",
            "Rule used: do not buy because Sharpe is high; buy only if free evidence leaves PIT/size/delisting",
            "as the binding uncertainty and the pattern is otherwise coherent under frozen parameters.",
            "",
        ]
    )
    return "\n".join(lines)
