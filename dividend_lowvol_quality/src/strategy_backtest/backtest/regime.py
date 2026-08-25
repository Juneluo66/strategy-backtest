"""Point-in-time market-regime signals and STRICT_B exposure overlays."""
from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_backtest.backtest.metrics import performance_metrics
from strategy_backtest.config import StrategyConfig

REGIME_CONDITIONS = ("A_ma120", "B_ma250", "C_ret60", "D_ret120", "E_vol20_p70", "F_breadth40", "G_divlow_rel60")
EXPOSURE_SCHEMES = ("Always", "HardCash", "Soft75", "Soft50", "TrendScaling")


def compute_monthly_breadth(
    signal_dates: pd.Series,
    universe_dir: str | Path,
    price_dir: str | Path,
    batch_size: int = 50,
    rss_check: object | None = None,
) -> pd.DataFrame:
    """Compute T-1 monthly market breadth without materializing all prices.

    Each cached security file is read at most once.  This is materially less
    I/O intensive than rereading the full cross-section for every month while
    retaining a bounded memory footprint.
    """
    universe_root, prices_root = Path(universe_dir), Path(price_dir)
    dates = list(pd.to_datetime(signal_dates).drop_duplicates().sort_values())
    files = sorted(universe_root.glob("universe_asof_*.parquet"))
    members: dict[pd.Timestamp, set[str]] = {}
    for signal_date in dates:
        candidates = [
            item for item in files if pd.Timestamp(item.stem.rsplit("_", 1)[-1]) <= signal_date
        ]
        if not candidates:
            members[signal_date] = set()
            continue
        universe = pd.read_parquet(candidates[-1])
        universe["code"] = universe["code"].astype(str).str.extract(r"(\d{6})", expand=False)
        names = universe.get("name", pd.Series("", index=universe.index)).astype(str)
        members[signal_date] = set(
            universe.loc[
            universe["code"].notna() & ~names.str.contains("指数", na=False), "code"
            ].drop_duplicates()
        )
    counters = {
        date: {"valid_ma_count": 0, "above_ma_count": 0, "as_of_date": pd.NaT} for date in dates
    }
    codes = sorted(set().union(*members.values()))
    for start in range(0, len(codes), batch_size):
        for code in codes[start : start + batch_size]:
            path = prices_root / f"{code}_raw.parquet"
            if not path.exists():
                continue
            frame = pd.read_parquet(path, columns=["date", "close"]).dropna(subset=["close"])
            frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
            frame = frame.sort_values("date")
            for signal_date in dates:
                if code not in members[signal_date]:
                    continue
                visible = frame.loc[frame["date"] < signal_date].tail(120)
                if len(visible) < 120:
                    continue
                counters[signal_date]["valid_ma_count"] += 1
                counters[signal_date]["above_ma_count"] += int(
                    float(visible["close"].iloc[-1]) > float(visible["close"].mean())
                )
                last_date = visible["date"].iloc[-1]
                current = counters[signal_date]["as_of_date"]
                counters[signal_date]["as_of_date"] = (
                    last_date if pd.isna(current) else max(current, last_date)
                )
        gc.collect()
        if rss_check is not None:
            rss_check(processed=min(start + batch_size, len(codes)), total_codes=len(codes))
    rows: list[dict[str, object]] = []
    for signal_date in dates:
        count = counters[signal_date]
        rows.append(
            {
                "signal_date": signal_date,
                "as_of_date": count["as_of_date"],
                "universe_size": len(members[signal_date]),
                "valid_ma_count": count["valid_ma_count"],
                "above_ma_count": count["above_ma_count"],
                "breadth_pct": (
                    count["above_ma_count"] / count["valid_ma_count"]
                    if count["valid_ma_count"]
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def compute_regime_signals(
    broad: pd.DataFrame, divlow: pd.DataFrame, signal_dates: pd.Series, breadth: pd.DataFrame
) -> pd.DataFrame:
    """Return A--G with all market data cut off strictly before each signal date."""
    base = _prepare_prices(broad)
    low = _prepare_prices(divlow)
    base["ret1"] = base["close"].pct_change()
    base["ma120"] = base["close"].rolling(120, min_periods=120).mean()
    base["ma250"] = base["close"].rolling(250, min_periods=250).mean()
    base["ret60"] = base["close"].pct_change(60)
    base["ret120"] = base["close"].pct_change(120)
    base["vol20"] = base["ret1"].rolling(20, min_periods=20).std() * np.sqrt(252)
    base["vol20_p70_3y"] = base["vol20"].rolling(756, min_periods=252).quantile(0.70)
    low["ret60"] = low["close"].pct_change(60)
    output: list[dict[str, object]] = []
    breadth = breadth.copy()
    breadth["signal_date"] = pd.to_datetime(breadth["signal_date"]).dt.normalize()
    for signal_date in pd.to_datetime(signal_dates).drop_duplicates().sort_values():
        visible = base.loc[base["date"] < signal_date]
        low_visible = low.loc[low["date"] < signal_date]
        row: dict[str, object] = {"signal_date": signal_date}
        if visible.empty:
            output.append(row)
            continue
        point = visible.iloc[-1]
        low_point = low_visible.iloc[-1] if not low_visible.empty else pd.Series(dtype=float)
        row.update(
            {
                "as_of_date": point["date"],
                "broad_close": point["close"],
                "ma120": point["ma120"],
                "ma250": point["ma250"],
                "ret60": point["ret60"],
                "ret120": point["ret120"],
                "vol20": point["vol20"],
                "vol20_p70_3y": point["vol20_p70_3y"],
                "divlow_ret60": low_point.get("ret60", np.nan),
            }
        )
        row["relative_ret60"] = row["divlow_ret60"] - row["ret60"]
        b = breadth.loc[breadth["signal_date"].eq(signal_date)]
        row["breadth_pct"] = b["breadth_pct"].iloc[0] if not b.empty else np.nan
        row.update(
            {
                "A_ma120": _bool_or_nan(point["close"] < point["ma120"]),
                "B_ma250": _bool_or_nan(point["close"] < point["ma250"]),
                "C_ret60": _bool_or_nan(point["ret60"] < 0),
                "D_ret120": _bool_or_nan(point["ret120"] < 0),
                "E_vol20_p70": _bool_or_nan(point["vol20"] > point["vol20_p70_3y"]),
                "F_breadth40": _bool_or_nan(row["breadth_pct"] < 0.40),
                "G_divlow_rel60": _bool_or_nan(row["relative_ret60"] > 0),
            }
        )
        output.append(row)
    return pd.DataFrame(output)


def etf_period_returns(etf: pd.DataFrame, periods: pd.DataFrame) -> pd.DataFrame:
    """T+1 ETF gross returns aligned to frozen STRICT_B holding periods."""
    prices = _prepare_prices(etf)
    rows: list[dict[str, object]] = []
    for item in periods.itertuples():
        signal, next_signal = pd.Timestamp(item.signal_date), pd.Timestamp(item.next_signal_date)
        entry = prices.loc[prices["date"] > signal].head(1)
        exit_ = prices.loc[prices["date"] > next_signal].head(1)
        if entry.empty or exit_.empty:
            rows.append({"signal_date": signal, "etf_gross_return": np.nan})
            continue
        start, end = float(entry.iloc[0]["open"]), float(exit_.iloc[0]["close"])
        rows.append(
            {
                "signal_date": signal,
                "etf_entry_date": entry.iloc[0]["date"],
                "etf_exit_date": exit_.iloc[0]["date"],
                "etf_gross_return": end / start - 1 if start > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def run_overlay(
    strict_periods: pd.DataFrame,
    signals: pd.DataFrame,
    condition: str,
    config: StrategyConfig,
    etf_returns: pd.DataFrame,
    mode: str,
    index_upper_bound: bool = False,
) -> pd.DataFrame:
    """Apply a condition to frozen STRICT_B monthly results.

    STRICT_B period returns/costs remain untouched while held.  Additional
    transition costs account for fully entering/exiting the stock or ETF leg.
    """
    frame = strict_periods.merge(signals[["signal_date", condition]], on="signal_date", how="left")
    frame = frame.merge(etf_returns, on="signal_date", how="left")
    frame["condition"] = frame[condition]
    state: list[str] = []
    for value in frame["condition"]:
        if pd.isna(value):
            state.append("unavailable")
        elif mode == "Always" or bool(value):
            state.append("strict_b")
        elif mode == "Cash":
            state.append("cash")
        else:
            state.append("benchmark")
    frame["state"] = state
    previous: str | None = None
    returns, costs, overlay_turnover = [], [], []
    for row in frame.itertuples():
        current = row.state
        if current == "unavailable":
            returns.append(np.nan)
            costs.append(np.nan)
            overlay_turnover.append(np.nan)
            previous = current
            continue
        base_return = row.net_return if current == "strict_b" else (0.0 if current == "cash" else row.etf_gross_return)
        if not np.isfinite(base_return):
            returns.append(np.nan)
            costs.append(np.nan)
            overlay_turnover.append(np.nan)
            previous = current
            continue
        transition_cost, turnover = (
            (0.0, 0.0)
            if mode == "Always"
            else _transition_cost(
                previous, current, float(getattr(row, "turnover", 0.0)), config, index_upper_bound
            )
        )
        returns.append(float(base_return) - transition_cost)
        costs.append(transition_cost)
        overlay_turnover.append(turnover)
        previous = current
    frame["net_return"] = returns
    frame["overlay_transition_cost"] = costs
    frame["overlay_turnover"] = overlay_turnover
    frame["total_turnover"] = frame["turnover"].fillna(0) * frame["state"].eq("strict_b") + frame["overlay_turnover"].fillna(0)
    frame["strict_b_exposure"] = frame["state"].eq("strict_b").astype(float)
    frame["cash_exposure"] = frame["state"].eq("cash").astype(float)
    return frame


def run_continuous_exposure(
    strict_periods: pd.DataFrame, signals: pd.DataFrame, scheme: str, config: StrategyConfig
) -> pd.DataFrame:
    """Apply a frozen, predeclared STRICT_B/cash exposure schedule.

    ``net_return`` and ``transaction_cost`` originate from the frozen 100%
    STRICT_B engine.  They are scaled by actual exposure.  Only changes in
    target exposure add overlay trades, preserving T+1 period timing and never
    re-ranking or re-executing the stock selection.
    """
    if scheme not in EXPOSURE_SCHEMES:
        raise ValueError(f"unknown exposure scheme: {scheme}")
    columns = ["signal_date", "D_ret120", "F_breadth40"]
    frame = strict_periods.merge(signals[columns], on="signal_date", how="left")
    targets, states = [], []
    for row in frame.itertuples():
        target, state = exposure_target(row.D_ret120, row.F_breadth40, scheme)
        targets.append(target)
        states.append(state)
    frame["target_exposure"] = targets
    frame["state"] = states
    previous: float | None = None
    net_returns, transition_costs, transition_turnovers = [], [], []
    for row in frame.itertuples():
        exposure = row.target_exposure
        if pd.isna(exposure) or not np.isfinite(row.net_return):
            net_returns.append(np.nan)
            transition_costs.append(np.nan)
            transition_turnovers.append(np.nan)
            previous = None
            continue
        transition_cost, transition_turnover = _exposure_transition_cost(
            previous, float(exposure), config
        )
        net_returns.append(float(exposure) * float(row.net_return) - transition_cost)
        transition_costs.append(transition_cost)
        transition_turnovers.append(transition_turnover)
        previous = float(exposure)
    frame["net_return"] = net_returns
    frame["overlay_transition_cost"] = transition_costs
    frame["overlay_turnover"] = transition_turnovers
    frame["strict_b_exposure"] = frame["target_exposure"]
    frame["cash_exposure"] = 1.0 - frame["target_exposure"]
    frame["total_turnover"] = (
        frame["target_exposure"] * frame["turnover"].fillna(0.0)
        + frame["overlay_turnover"].fillna(0.0)
    )
    frame["scaled_strict_transaction_cost"] = (
        frame["target_exposure"] * frame.get("transaction_cost", pd.Series(0.0, index=frame.index))
    )
    frame["total_cost_drag"] = (
        frame["scaled_strict_transaction_cost"] + frame["overlay_transition_cost"].fillna(0.0)
    )
    return frame


def exposure_target(down_signal: object, weak_breadth: object, scheme: str) -> tuple[float, str]:
    """Map only existing T-1 trend/breadth signals to a fixed exposure."""
    if scheme == "Always":
        return 1.0, "always"
    if pd.isna(down_signal) or pd.isna(weak_breadth):
        return np.nan, "unavailable"
    down, weak = bool(down_signal), bool(weak_breadth)
    if down and weak:
        return 1.0, "down_and_weak"
    if scheme == "HardCash":
        return 0.0, "other"
    if scheme == "Soft75":
        return 0.75, "other"
    if scheme == "Soft50":
        return 0.50, "other"
    if down or weak:
        return 0.75, "down_only" if down else "weak_only"
    return 0.50, "other"


def exposure_summary(
    frame: pd.DataFrame, always: pd.DataFrame, sample: str, oos_start: object
) -> dict[str, object]:
    """Summarize a continuous overlay against the matching Always baseline."""
    summary = overlay_summary(frame, always, sample, oos_start)
    scoped = _select_sample(frame, sample, oos_start)
    summary.update(
        {
            "scaled_strict_cost_drag": scoped["scaled_strict_transaction_cost"].sum(min_count=1),
            "total_cost_drag": scoped["total_cost_drag"].sum(min_count=1),
            "average_target_exposure": scoped["target_exposure"].mean(),
        }
    )
    return summary


def overlay_summary(frame: pd.DataFrame, always: pd.DataFrame, sample: str, oos_start: object) -> dict[str, object]:
    cutoff = pd.Timestamp(oos_start)
    scoped = _select_sample(frame, sample, cutoff)
    base = always.loc[always["signal_date"].isin(scoped["signal_date"])]
    stats, base_stats = performance_metrics(scoped["net_return"]), performance_metrics(base["net_return"])
    states = scoped["state"].fillna("unavailable")
    switches = int(states.ne(states.shift()).iloc[1:].sum()) if len(states) > 1 else 0
    return {
        "sample": sample,
        "periods": len(scoped),
        **stats,
        "average_turnover": scoped["total_turnover"].mean(),
        "strict_b_exposure": scoped["strict_b_exposure"].mean(),
        "cash_exposure": scoped["cash_exposure"].mean(),
        "condition_switches": switches,
        "longest_cash_periods": _longest_run(states.eq("cash")),
        "annual_return_vs_always": stats["annual_return"] - base_stats["annual_return"],
        "max_drawdown_improvement_vs_always": abs(base_stats["max_drawdown"]) - abs(stats["max_drawdown"]),
        "transition_cost_drag": scoped["overlay_transition_cost"].sum(min_count=1),
        "signal_available_ratio": scoped["state"].ne("unavailable").mean(),
    }


def _exposure_transition_cost(
    previous: float | None, current: float, config: StrategyConfig
) -> tuple[float, float]:
    """Charge only the changed STRICT_B notional on continuous exposure moves."""
    if previous is None:
        # Frozen first-period net return already contains first stock purchase.
        return 0.0, 0.0
    delta = current - previous
    if abs(delta) <= 1e-12:
        return 0.0, 0.0
    commission = max(config.commission_rate, config.minimum_commission / config.initial_capital)
    if delta > 0:
        return delta * (commission + config.slippage_rate), delta
    sold = abs(delta)
    return sold * (commission + config.slippage_rate + config.sell_stamp_duty_rate), sold


def state_attribution(strict_periods: pd.DataFrame, signals: pd.DataFrame, oos_start: object) -> pd.DataFrame:
    """Describe frozen STRICT_B returns across predeclared live states."""
    frame = strict_periods.merge(signals, on="signal_date", how="left")
    labels = {
        "trend": ("ret120", lambda x: "up" if x >= 0 else "down"),
        "volatility": ("E_vol20_p70", lambda x: "high_vol" if x else "low_vol"),
        "breadth": ("F_breadth40", lambda x: "weak_breadth" if x else "strong_breadth"),
    }
    rows: list[dict[str, object]] = []
    for sample, scoped in _sample_frames(frame, oos_start):
        for family, (column, label) in labels.items():
            for value, group in scoped.dropna(subset=[column]).groupby(scoped.dropna(subset=[column])[column].map(label)):
                rows.append(_attribution_row(sample, family, value, group))
        trough = scoped[(scoped["ret120"] < 0) & (scoped["breadth_pct"] < 0.40)]
        other = scoped.drop(trough.index)
        rows.extend([_attribution_row(sample, "trough_proxy", "down_and_weak_breadth", trough), _attribution_row(sample, "trough_proxy", "other", other)])
    return pd.DataFrame(rows)


def _prepare_prices(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["open"] = pd.to_numeric(out.get("open", out["close"]), errors="coerce").fillna(out["close"])
    return out.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates("date")


def _bool_or_nan(value: object) -> object:
    return bool(value) if pd.notna(value) else np.nan


def _transition_cost(
    previous: str | None,
    current: str,
    strict_turnover: float,
    config: StrategyConfig,
    index_upper_bound: bool,
) -> tuple[float, float]:
    if previous is None:
        # The frozen STRICT_B first-period return already contains its initial
        # purchase costs.  There is no prior overlay position to unwind.
        return 0.0, 0.0
    if previous == current:
        return 0.0, 0.0
    cost, turnover = 0.0, 0.0
    commission = max(config.commission_rate, config.minimum_commission / config.initial_capital)
    if previous == "strict_b":
        cost += commission + config.slippage_rate + config.sell_stamp_duty_rate
        turnover += 1.0
    elif previous == "benchmark" and not index_upper_bound:
        cost += commission + config.slippage_rate
        turnover += 1.0
    if current == "strict_b" or current == "benchmark" and not index_upper_bound:
        if current == "strict_b":
            # Existing STRICT_B period cost captures rebalance turnover.  Add
            # only the incremental entry notional caused by returning from an
            # overlay state, never double-charge its frozen trades.
            additional = max(0.0, 1.0 - strict_turnover)
            cost += additional * (commission + config.slippage_rate)
            turnover += additional
        else:
            cost += commission + config.slippage_rate
            turnover += 1.0
    return cost, turnover


def _longest_run(mask: pd.Series) -> int:
    longest = current = 0
    for value in mask.fillna(False):
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _sample_frames(frame: pd.DataFrame, oos_start: object) -> list[tuple[str, pd.DataFrame]]:
    cutoff = pd.Timestamp(oos_start)
    return [
        ("all_sample", frame),
        ("in_sample", frame[pd.to_datetime(frame["signal_date"]) < cutoff]),
        ("out_of_sample", frame[pd.to_datetime(frame["signal_date"]) >= cutoff]),
    ]


def _select_sample(frame: pd.DataFrame, sample: str, oos_start: object) -> pd.DataFrame:
    cutoff = pd.Timestamp(oos_start)
    if sample == "in_sample":
        return frame[pd.to_datetime(frame["signal_date"]) < cutoff].copy()
    if sample == "out_of_sample":
        return frame[pd.to_datetime(frame["signal_date"]) >= cutoff].copy()
    return frame.copy()


def _attribution_row(sample: str, family: str, label: str, group: pd.DataFrame) -> dict[str, object]:
    returns = pd.to_numeric(group.get("net_return"), errors="coerce").dropna()
    return {
        "sample": sample,
        "state_family": family,
        "state": label,
        "months": len(returns),
        "mean_monthly_return": returns.mean(),
        "win_rate": (returns > 0).mean() if len(returns) else np.nan,
        "return_contribution": returns.sum(),
    }
