"""Month-end signal / next-session execution portfolio backtest."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from strategy_backtest.backtest.metrics import performance_metrics
from strategy_backtest.config import StrategyConfig
from strategy_backtest.strategies.dividend_lowvol_quality import select_portfolio


def monthly_rebalance_dates(prices: pd.DataFrame) -> list[pd.Timestamp]:
    """Return first observed trading date in each month."""
    dates = pd.DatetimeIndex(pd.to_datetime(prices["date"]).dropna().unique()).sort_values()
    return list(pd.Series(dates, index=dates).groupby(dates.to_period("M")).min())


def _next_session(dates: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    future = dates[dates > date]
    return future[0] if len(future) else None


def _period_return(
    prices: pd.DataFrame, holdings: pd.DataFrame, entry: pd.Timestamp, exit_: pd.Timestamp
) -> float:
    rows = []
    for holding in holdings.itertuples():
        stock = prices[prices["code"].astype(str) == str(holding.code)].copy()
        stock["date"] = pd.to_datetime(stock["date"])
        entry_column = "adjusted_open" if "adjusted_open" in stock.columns else "open"
        start = stock.loc[stock["date"].eq(entry), entry_column]
        end = stock.loc[stock["date"].eq(exit_), "adjusted_close"]
        if start.empty or end.empty or not np.isfinite(start.iloc[0]) or not np.isfinite(end.iloc[0]):
            continue
        rows.append((float(holding.weight), float(end.iloc[0] / start.iloc[0] - 1.0)))
    if not rows:
        return np.nan
    weights, returns = zip(*rows)
    weights = np.asarray(weights, dtype=float)
    return float(np.dot(weights / weights.sum(), np.asarray(returns, dtype=float)))


def _locked_limit(raw: pd.DataFrame, date: pd.Timestamp, direction: str) -> bool:
    """Conservative one-price limit proxy when no order-book history exists."""
    current = raw.loc[raw["date"].eq(date)]
    before = raw.loc[raw["date"] < date].tail(1)
    if current.empty or before.empty:
        return False
    row, prior = current.iloc[0], before.iloc[0]
    required = {"open", "high", "low", "close"}
    if not required.issubset(row.index):
        return False
    try:
        one_price = np.isclose(float(row["open"]), float(row["high"])) and np.isclose(
            float(row["open"]), float(row["low"])
        )
        change = float(row["open"]) / float(prior["close"]) - 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        return False
    return one_price and ((direction == "buy" and change >= 0.095) or (direction == "sell" and change <= -0.095))


def _amount_or_zero(row: pd.Series) -> float:
    value = pd.to_numeric(pd.Series([row.get("amount", 0)]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) else 0.0


def backtest_monthly(
    snapshots: dict[pd.Timestamp, pd.DataFrame],
    prices: pd.DataFrame,
    config: StrategyConfig,
) -> dict[str, object]:
    """Backtest prebuilt PIT snapshots using next-trading-day execution.

    ``snapshots`` must contain data that was available at its key date.  This
    function deliberately does not enrich snapshots itself so its timing
    contract is explicit and easy to test.
    """
    price_dates = pd.DatetimeIndex(pd.to_datetime(prices["date"]).dropna().unique()).sort_values()
    dates = sorted(pd.Timestamp(date).normalize() for date in snapshots)
    records: list[dict[str, object]] = []
    previous_weights = pd.Series(dtype=float)

    for index, signal_date in enumerate(dates[:-1]):
        entry = _next_session(price_dates, signal_date)
        next_signal = dates[index + 1]
        exit_ = _next_session(price_dates, next_signal)
        if entry is None or exit_ is None:
            continue
        try:
            holdings = select_portfolio(snapshots[signal_date], config)
        except ValueError as error:
            records.append(
                {
                    "signal_date": signal_date,
                    "entry_date": entry,
                    "exit_date": exit_,
                    "gross_return": 0.0,
                    "net_return": 0.0,
                    "turnover": 0.0,
                    "skip_reason": str(error),
                    "holdings": pd.DataFrame(),
                }
            )
            continue
        current = holdings.set_index("code")["weight"]
        turnover = float(current.abs().sum()) if previous_weights.empty else float(
            current.subtract(previous_weights, fill_value=0).abs().sum() / 2.0
        )
        gross_return = _period_return(prices, holdings, entry, exit_)
        net_return = gross_return - turnover * config.one_way_cost if np.isfinite(gross_return) else np.nan
        records.append(
            {
                "signal_date": signal_date,
                "entry_date": entry,
                "exit_date": exit_,
                "gross_return": gross_return,
                "net_return": net_return,
                "turnover": turnover,
                "skip_reason": "",
                "holdings": holdings,
            }
        )
        previous_weights = current

    periods = pd.DataFrame([{key: value for key, value in r.items() if key != "holdings"} for r in records])
    if not periods.empty:
        periods["nav"] = (1.0 + periods["net_return"].fillna(0.0)).cumprod()
    holdings_frames = []
    for record in records:
        frame = record["holdings"].copy()
        if not frame.empty:
            holdings_frames.append(frame.assign(signal_date=record["signal_date"]))
    holdings_frame = pd.concat(holdings_frames, ignore_index=True) if holdings_frames else pd.DataFrame()
    industry_exposure = (
        holdings_frame.groupby(["signal_date", "industry"], dropna=False)["weight"].sum().reset_index()
        if not holdings_frame.empty
        else pd.DataFrame(columns=["signal_date", "industry", "weight"])
    )
    return {
        "periods": periods,
        "holdings": {record["signal_date"]: record["holdings"] for record in records},
        "holdings_frame": holdings_frame,
        "industry_exposure": industry_exposure,
        "metrics": performance_metrics(periods["net_return"]) if not periods.empty else performance_metrics(pd.Series(dtype=float)),
    }


def backtest_cached_holdings(
    holdings: pd.DataFrame, cache_dir: str | Path, config: StrategyConfig
) -> dict[str, object]:
    """Backtest preselected holdings by loading only held stocks per month.

    This is intentionally separate from ``backtest_monthly``: it keeps the
    full-market price cache on disk and never materializes it as one DataFrame.
    """
    root = Path(cache_dir)
    frame = holdings.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.normalize()
    dates = sorted(frame["signal_date"].unique())
    previous_weights = pd.Series(dtype=float)
    records = []
    execution_rows = []

    for index, signal_date in enumerate(dates[:-1]):
        next_signal = dates[index + 1]
        month = frame[frame["signal_date"].eq(signal_date)].copy()
        current = month.set_index("code")["weight"]
        turnover = float(current.abs().sum()) if previous_weights.empty else float(
            current.subtract(previous_weights, fill_value=0).abs().sum() / 2.0
        )
        weighted_returns, available_weight, transaction_cost = 0.0, 0.0, 0.0
        entry_dates, exit_dates = [], []
        for row in month.itertuples():
            code = str(row.code).zfill(6)
            raw_path = root / "prices" / f"{code}_raw.parquet"
            qfq_path = root / "prices" / f"{code}_qfq.parquet"
            if not raw_path.exists() or not qfq_path.exists():
                continue
            raw = pd.read_parquet(raw_path)
            raw = raw[[column for column in ("date", "open", "high", "low", "close", "amount", "volume") if column in raw]]
            qfq = pd.read_parquet(qfq_path)[["date", "open", "close"]].rename(
                columns={"open": "adjusted_open", "close": "adjusted_close"}
            )
            price = raw.merge(qfq, on="date", how="inner")
            price["date"] = pd.to_datetime(price["date"]).dt.normalize()
            entry = price[price["date"] > signal_date].head(1)
            exit_ = price[price["date"] > next_signal].head(1)
            if entry.empty or exit_.empty:
                execution_rows.append({"signal_date": signal_date, "code": code, "status": "missing_price"})
                continue
            entry_date, exit_date = entry.iloc[0]["date"], exit_.iloc[0]["date"]
            raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
            entry_raw = raw[raw["date"].eq(entry_date)]
            exit_raw = raw[raw["date"].eq(exit_date)]
            if entry_raw.empty or _amount_or_zero(entry_raw.iloc[0]) <= 0:
                execution_rows.append({"signal_date": signal_date, "code": code, "status": "buy_suspended"})
                continue
            if _locked_limit(raw, entry_date, "buy"):
                execution_rows.append({"signal_date": signal_date, "code": code, "status": "buy_limit_up"})
                continue
            if exit_raw.empty or _amount_or_zero(exit_raw.iloc[0]) <= 0:
                execution_rows.append({"signal_date": signal_date, "code": code, "status": "sell_suspended"})
                continue
            if _locked_limit(raw, exit_date, "sell"):
                execution_rows.append({"signal_date": signal_date, "code": code, "status": "sell_limit_down"})
                continue
            average_amount = pd.to_numeric(raw.loc[raw["date"] <= entry_date, "amount"], errors="coerce").tail(20).mean()
            order_value = config.initial_capital * float(row.weight)
            if not np.isfinite(average_amount) or order_value > average_amount * config.max_order_to_avg_turnover:
                execution_rows.append({"signal_date": signal_date, "code": code, "status": "liquidity_limit"})
                continue
            start = float(entry.iloc[0]["adjusted_open"])
            end = float(exit_.iloc[0]["adjusted_close"])
            if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
                continue
            weighted_returns += float(row.weight) * (end / start - 1.0)
            available_weight += float(row.weight)
            notional = config.initial_capital * float(row.weight)
            buy_commission = max(notional * config.commission_rate, config.minimum_commission)
            sell_notional = notional * (end / start)
            sell_commission = max(sell_notional * config.commission_rate, config.minimum_commission)
            transaction_cost += (
                buy_commission
                + sell_commission
                + (notional + sell_notional) * config.slippage_rate
                + sell_notional * config.sell_stamp_duty_rate
            ) / config.initial_capital
            entry_dates.append(entry_date)
            exit_dates.append(exit_date)
            execution_rows.append({"signal_date": signal_date, "code": code, "status": "executed"})
        gross_return = weighted_returns / available_weight if available_weight > 0 else np.nan
        net_return = gross_return - transaction_cost if np.isfinite(gross_return) else np.nan
        records.append(
            {
                "signal_date": signal_date,
                "entry_date": min(entry_dates) if entry_dates else pd.NaT,
                "exit_date": max(exit_dates) if exit_dates else pd.NaT,
                "gross_return": gross_return,
                "net_return": net_return,
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "available_weight": available_weight,
                "skip_reason": "" if available_weight > 0 else "no executable prices",
            }
        )
        previous_weights = current
    periods = pd.DataFrame(records)
    if not periods.empty:
        periods["nav"] = (1 + periods["net_return"].fillna(0)).cumprod()
    return {
        "periods": periods,
        "holdings_frame": frame,
        "industry_exposure": frame.groupby(["signal_date", "industry"], dropna=False)["weight"].sum().reset_index(),
        "metrics": performance_metrics(periods["net_return"]) if not periods.empty else performance_metrics(pd.Series(dtype=float)),
        "executions": pd.DataFrame(execution_rows),
    }
