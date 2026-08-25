"""Month-end signal / next-open execution backtest engine."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from .config import DualMomentumConfig
from .data import cash_symbol_on
from .portfolio import PortfolioState, choose_holdings
from .signals import build_monthly_signal_panel, month_end_index, next_trading_day


def run_variant(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    config: DualMomentumConfig,
    variant_name: str,
    *,
    one_way_bps: Optional[float] = None,
    trend_horizons: Optional[tuple[int, int, int]] = None,
) -> dict[str, Any]:
    """Run a single named variant; returns equity/targets/trades/scores/audit tables."""
    variant = config.variant(variant_name)
    pool_name = variant["pool"]
    pool = config.universe[pool_name]
    risk_symbols = list(pool["risk"])
    category_map = config.category_map()
    cost_bps = float(one_way_bps if one_way_bps is not None else config.raw["costs"]["one_way_bps"])
    horizons = trend_horizons or tuple(
        int(x) for x in config.raw.get("trend_consistency", {}).get("horizons", [3, 6, 12])
    )

    common = opens.index.intersection(closes.index).sort_values()
    opens = opens.reindex(common)
    closes = closes.reindex(common)

    signal_panel = build_monthly_signal_panel(
        closes,
        risk_symbols=risk_symbols,
        weight_5m=float(config.raw["momentum"]["weight_5m"]),
        weight_12m=float(config.raw["momentum"]["weight_12m"]),
        sma_months=int(config.raw["trend_filter"]["month_sma"]),
        vol_lookback=int(config.raw["volatility"]["lookback_days"]),
        vol_min_obs=int(config.raw["volatility"]["min_observations"]),
        trend_horizons=horizons,  # type: ignore[arg-type]
    )
    month_ends = month_end_index(common)
    # Need enough history for 12m return + 10m SMA => skip early months with incomplete scores.
    execute_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal_date in month_ends:
        exec_date = next_trading_day(common, signal_date)
        if exec_date is not None:
            execute_map[exec_date] = pd.Timestamp(signal_date)

    state = PortfolioState()
    weights = pd.Series(dtype=float)
    pending_target: Optional[pd.Series] = None
    pending_signal: Optional[pd.Timestamp] = None
    pending_audit: list[dict] = []
    cash_switches: list[dict] = []
    previous_cash: Optional[str] = None

    equity_rows: list[dict] = []
    targets: list[dict] = []
    trades: list[dict] = []
    audit_rows: list[dict] = []
    previous_close: Optional[pd.Series] = None

    signal_dates = set(month_ends)

    for date in common:
        open_prices = opens.loc[date]
        close_prices = closes.loc[date]
        gross_return = 0.0
        cost = 0.0

        if previous_close is not None and not weights.empty:
            overnight = (open_prices / previous_close - 1).replace([np.inf, -np.inf], np.nan)
            overnight = overnight.fillna(0.0)
            gross_return += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())

        if date in execute_map and pending_target is not None:
            turnover = float(pending_target.sub(weights, fill_value=0.0).abs().sum())
            trade_cost = turnover * cost_bps / 10_000
            cost += trade_cost
            trades.append(
                {
                    "date": date,
                    "signal_date": pending_signal,
                    "turnover": turnover,
                    "cost": trade_cost,
                    "holdings": int((pending_target > 0).sum()),
                    "reason": "next_open_rebalance",
                }
            )
            for symbol, weight in pending_target.items():
                targets.append(
                    {
                        "signal_date": pending_signal,
                        "execution_date": date,
                        "symbol": symbol,
                        "weight": float(weight),
                    }
                )
            for event in pending_audit:
                audit_rows.append({"signal_date": pending_signal, "execution_date": date, **event})
            weights = pending_target
            pending_target = None
            pending_signal = None
            pending_audit = []

        if not weights.empty:
            intraday = (close_prices / open_prices - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross_return += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())

        if date in signal_dates:
            day = signal_panel[signal_panel["date"] == date].copy()
            cash = cash_symbol_on(date, config, closes)
            if previous_cash is not None and cash != previous_cash:
                cash_switches.append(
                    {"date": date, "from": previous_cash, "to": cash, "reason": "cash_proxy_switch"}
                )
            previous_cash = cash
            target_dict, state, day_audit = choose_holdings(
                day,
                state,
                vol_adjust=bool(variant["vol_adjust"]),
                category_constraint=bool(variant["category_constraint"]),
                trend_consistency=bool(variant["trend_consistency"]),
                regime_sizing=bool(variant["regime_sizing"]),
                top_k=int(variant.get("top_k", config.raw["portfolio"]["top_k"])),
                relative_threshold=float(config.raw["hysteresis"]["relative_threshold"]),
                category_map=category_map,
                cash_symbol=cash,
                use_hysteresis=bool(variant.get("use_hysteresis", True)),
                selection_mode=str(variant.get("selection_mode", "topk")),
            )
            # Drop targets for symbols missing open prices on next day later;
            # keep weight map as-is; missing prices treated as 0 return.
            pending_target = pd.Series(target_dict, dtype=float)
            pending_signal = date
            pending_audit = day_audit

        net_return = gross_return - cost
        equity_rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "cost": cost,
                "net_return": net_return,
                "exposure": float(weights.drop(labels=[c for c in weights.index if c in {"SGOV", "BIL"}], errors="ignore").sum())
                if not weights.empty
                else 0.0,
                "n_holdings": int((weights > 0).sum()) if not weights.empty else 0,
            }
        )
        previous_close = close_prices

    equity = pd.DataFrame(equity_rows).set_index("date").sort_index()
    # Drop leading zeros before first execution so metrics start when invested.
    if trades:
        first_exec = pd.Timestamp(min(t["date"] for t in trades))
        equity = equity.loc[equity.index >= first_exec]
    equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()

    return {
        "variant": variant_name,
        "equity": equity,
        "targets": pd.DataFrame(targets),
        "trades": pd.DataFrame(trades),
        "monthly_scores": signal_panel,
        "audit": pd.DataFrame(audit_rows),
        "cash_switches": pd.DataFrame(cash_switches),
        "one_way_bps": cost_bps,
        "trend_horizons": horizons,
    }
