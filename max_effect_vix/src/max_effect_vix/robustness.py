"""Predeclared MAX parameter and neutralization research grid."""
from __future__ import annotations

import pandas as pd

from .backtest import run_backtest
from .metrics import performance_report


def run_grid(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    vix: pd.Series,
    benchmark: pd.Series,
    config: dict,
    one_way_bps: float,
    membership_on=None,
) -> pd.DataFrame:
    rows = []
    costs = config["costs"]
    controls = config["neutralization"]
    for top_returns in config["robustness"]["top_returns"]:
        for portfolio_size in config["robustness"]["portfolio_sizes"]:
            for variant in controls["variants"]:
                if variant == "size_neutral":
                    rows.append(
                        {
                            "top_returns": top_returns,
                            "portfolio_size": portfolio_size,
                            "variant": variant,
                            "status": "BLOCKED_BY_PIT_MARKET_CAP",
                        }
                    )
                    continue
                results, _, trades, _ = run_backtest(
                    opens, closes, volumes, vix,
                    lookback=config["signal_lookback_days"],
                    top_returns=top_returns,
                    min_dollar_volume=config["min_dollar_volume"],
                    portfolio_decile=config["portfolio_decile"],
                    max_portfolio_size=portfolio_size,
                    vix_mode="none",
                    one_way_bps=one_way_bps,
                    annual_margin_rate=costs["annual_margin_rate"],
                    benchmark=benchmark,
                    factor_variant=variant,
                    volatility_lookback_days=controls["volatility_lookback_days"],
                    beta_lookback_days=controls["beta_lookback_days"],
                    beta_min_observations=controls["beta_min_observations"],
                    winsor_limits=tuple(controls["winsor_limits"]),
                    annual_spy_borrow_rate=costs["annual_spy_borrow_rate"],
                    membership_on=membership_on,
                )
                rows.append(
                    {
                        "top_returns": top_returns,
                        "portfolio_size": portfolio_size,
                        "variant": variant,
                        "status": "OK",
                        **performance_report(results, trades, benchmark),
                    }
                )
    return pd.DataFrame(rows)
