"""Command-line entry points for data retrieval, audit, and backtesting."""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_backtest.backtest.engine import (
    _amount_or_zero,
    _locked_limit,
    backtest_cached_holdings,
    backtest_monthly,
)
from strategy_backtest.backtest.metrics import (
    drawdown_table,
    performance_metrics,
    relative_metrics,
    rolling_metrics,
    yearly_returns,
)
from strategy_backtest.backtest.regime import (
    EXPOSURE_SCHEMES,
    REGIME_CONDITIONS,
    compute_monthly_breadth,
    compute_regime_signals,
    etf_period_returns,
    exposure_summary,
    overlay_summary,
    run_continuous_exposure,
    run_overlay,
    state_attribution,
)
from strategy_backtest.backtest.robustness import run_top_n_sensitivity
from strategy_backtest.config import StrategyConfig
from strategy_backtest.data.akshare_client import AkShareClient
from strategy_backtest.data.baostock_client import BaoStockClient
from strategy_backtest.data.market_data import MarketDataClient
from strategy_backtest.data.snapshots import (
    build_monthly_snapshots,
    enrich_industries,
    load_cached_histories,
)
from strategy_backtest.reporting import (
    render_backtest_report,
    render_comparative_report,
    render_readiness_report,
    save_report,
)
from strategy_backtest.strategies.dividend_lowvol_quality import select_portfolio
from strategy_backtest.validation.coverage import scan_cache_coverage
from strategy_backtest.validation.dividend_audit import audit_dividend_stages, audit_dividends

VARIANT_PRESETS = {
    "A": ("dividend", "equal"),
    "B": ("dividend_lowvol", "equal"),
    "C": ("dividend_quality", "equal"),
    "D": ("quality_industry", "equal"),
    "E": ("quality_industry", "inverse_volatility"),
    "STRICT_B": ("strict_b", "equal"),
    "LEGACY_B": ("legacy_b_score", "equal"),
}


def _config(args: argparse.Namespace) -> StrategyConfig:
    variant, weighting = VARIANT_PRESETS.get(
        getattr(args, "preset", None),
        (getattr(args, "variant", "quality_industry"), getattr(args, "weighting", "inverse_volatility")),
    )
    return StrategyConfig(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        variant=variant,
        weighting=weighting,
        top_n=getattr(args, "top_n", 25),
        volatility_window=getattr(args, "volatility_window", 120),
        dividend_signal=getattr(args, "dividend_signal", "annual_dividend_yield"),
        high_dividend_percentile=getattr(args, "high_dividend_percentile", 0.20),
        rebalance_position=getattr(args, "rebalance_position", "first"),
        excluded_industries=tuple(
            value.strip()
            for value in getattr(args, "exclude_industries", "").split(",")
            if value.strip()
        ),
        max_industry_weight=getattr(args, "max_industry_weight", 0.20),
        max_stock_weight=getattr(args, "max_stock_weight", 0.10),
    )


def _write_safety(path: Path, **values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


def _require_full(args: argparse.Namespace, command: str) -> None:
    """Reject accidental full-market work before it starts."""
    limit = getattr(args, "limit", None)
    if limit == 0 and not getattr(args, "full", False):
        raise RuntimeError(f"{command}: use --full explicitly for a full-market run")


def _check_rss(limit_mb: int, safety_path: Path, **context: object) -> float:
    rss = _rss_mb()
    if rss > limit_mb:
        _write_safety(
            safety_path,
            peak_rss_mb=round(rss, 1),
            max_memory_mb=limit_mb,
            stopped_for_memory=True,
            stopped_reason="rss_limit_exceeded",
            **context,
        )
        raise RuntimeError(f"stopped above RSS limit ({limit_mb} MB)")
    return rss


def cmd_fetch(args: argparse.Namespace) -> None:
    _require_full(args, "fetch")
    config = _config(args)
    client = AkShareClient(config.cache_dir)
    universe = enrich_industries(client.universe(refresh=args.refresh), args.industry_map)
    if args.limit:
        universe = universe.head(args.limit)
    universe.to_parquet(config.cache_dir / "universe_selected.parquet", index=False)
    completed, failed = 0, []

    def is_complete(code: str) -> bool:
        required = [
            config.cache_dir / "prices" / f"{code}_raw.parquet",
            config.cache_dir / "prices" / f"{code}_qfq.parquet",
            config.cache_dir / "dividends" / f"{code}.parquet",
            config.cache_dir / "financials" / f"{code}_cashflow.parquet",
            config.cache_dir / "financials" / f"{code}_profit.parquet",
        ]
        return all(path.exists() for path in required)

    codes = [code for code in universe["code"] if args.refresh or not is_complete(code)]
    completed = len(universe) - len(codes)

    def fetch_stock(code: str) -> str:
        command = [
            sys.executable,
            "-m",
            "strategy_backtest.cli",
            "--cache-dir",
            str(config.cache_dir),
            "fetch-one",
            "--code",
            code,
        ]
        if args.refresh:
            command.append("--refresh")
        if args.quality:
            command.append("--quality")
        subprocess.run(
            command,
            check=True,
            timeout=args.stock_timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        return code

    workers = min(args.workers, 2)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_stock, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                future.result()
                completed += 1
            except Exception as error:  # noqa: BLE001 - remote per-stock fetch failures are recorded
                failed.append({"code": code, "error": str(error)})
            if (completed + len(failed)) % 50 == 0:
                print(f"processed {completed + len(failed)}/{len(universe)}; success={completed}, failed={len(failed)}")
                _check_rss(
                    args.max_memory_mb,
                    config.cache_dir / "fetch_safety.json",
                    requested_stocks=len(universe),
                    completed=completed,
                    failed=len(failed),
                    workers=workers,
                )
    if failed:
        pd.DataFrame(failed).to_csv(config.cache_dir / "fetch_failures.csv", index=False)
    print(f"cached {completed}/{len(universe)} stocks at {config.cache_dir}")
    if failed:
        print(f"{len(failed)} stocks failed; see {config.cache_dir / 'fetch_failures.csv'}")
    _write_safety(
        config.cache_dir / "fetch_safety.json",
        requested_stocks=len(universe),
        completed=completed,
        failed=len(failed),
        workers=workers,
        peak_rss_mb=round(_rss_mb(), 1),
        max_memory_mb=args.max_memory_mb,
        stopped_for_memory=False,
    )


def cmd_fetch_one(args: argparse.Namespace) -> None:
    config = _config(args)
    client = AkShareClient(config.cache_dir)
    client.daily_prices(args.code, refresh=args.refresh)
    client.dividends(args.code, refresh=args.refresh)
    client.financials(args.code, refresh=args.refresh)
    if args.quality:
        client.quality_indicators(args.code, refresh=args.refresh)


def cmd_build_snapshots(args: argparse.Namespace) -> None:
    _require_full(args, "build-snapshots")
    config = _config(args)
    selected = config.cache_dir / "universe_selected.parquet"
    universe = pd.read_parquet(selected if selected.exists() else config.cache_dir / "universe.parquet")
    universe = enrich_industries(universe, args.industry_map)
    universe_by_date: dict[pd.Timestamp, pd.DataFrame] | None = None
    if args.universe_dir:
        universe_files = sorted(Path(args.universe_dir).glob("universe_asof_*.parquet"))
        if not universe_files:
            raise RuntimeError(f"no monthly universe files found in {args.universe_dir}")
        universe_by_date = {}
        historical_parts = []
        for path in universe_files:
            frame = enrich_industries(pd.read_parquet(path), args.industry_map)
            date = pd.Timestamp(path.stem.removeprefix("universe_asof_"))
            universe_by_date[date] = frame
            historical_parts.append(frame)
        # Metadata only: this makes historical delisted codes eligible for
        # bounded per-stock loads without materialising their price histories.
        universe = pd.concat([universe, *historical_parts], ignore_index=True).drop_duplicates("code")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    available = _complete_cached_codes(config.cache_dir)
    universe = universe[universe["code"].astype(str).str.zfill(6).isin(available)].copy()
    if args.limit:
        universe = universe.head(args.limit)
    if universe.empty:
        raise RuntimeError("no complete cached stock histories available")

    # Every partition must use the same exchange calendar.  Deriving the
    # month date inside each stock batch creates mismatched cross-sections
    # when an individual batch lacks the month's first trading day.
    reference_code = min(available)
    reference_dates = pd.to_datetime(
        pd.read_parquet(config.cache_dir / "prices" / f"{reference_code}_raw.parquet", columns=["date"])[
            "date"
        ],
        errors="coerce",
    ).dropna()
    reference_dates = reference_dates[
        (reference_dates >= pd.Timestamp(args.start)) & (reference_dates <= pd.Timestamp(args.end))
    ].dt.normalize().sort_values()
    by_month = reference_dates.groupby(reference_dates.dt.to_period("M"))
    if config.rebalance_position == "first":
        signal_dates = by_month.min().tolist()
    elif config.rebalance_position == "last":
        signal_dates = by_month.max().tolist()
    else:
        signal_dates = by_month.apply(lambda values: values.iloc[(len(values) - 1) // 2]).tolist()
    if not signal_dates:
        raise RuntimeError(f"reference calendar is empty for {reference_code}")

    parts_dir = output.parent / f"{output.stem}_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    panel_parts, coverage_parts, audit_parts = [], [], []
    peak_rss_mb = _rss_mb()
    stopped_for_memory = False
    for batch_number, batch_start in enumerate(range(0, len(universe), args.batch_size)):
        if _rss_mb() > args.max_memory_mb:
            stopped_for_memory = True
            _write_safety(
                output.with_name("safety_report.json"),
                peak_rss_mb=round(_rss_mb(), 1),
                max_memory_mb=args.max_memory_mb,
                stopped_for_memory=True,
                stopped_reason="rss_limit_exceeded",
                processed_stocks=batch_start,
            )
            break
        batch = universe.iloc[batch_start : batch_start + args.batch_size]
        codes = batch["code"].astype(str).str.zfill(6).tolist()
        prices, dividends, financials = load_cached_histories(config.cache_dir, codes)
        snapshots, audit, coverage = build_monthly_snapshots(
            batch,
            prices,
            dividends,
            financials,
            config,
            start=args.start,
            end=args.end,
            universe_by_date=(
                {
                    date: date_universe[date_universe["code"].astype(str).str.zfill(6).isin(codes)]
                    for date, date_universe in universe_by_date.items()
                }
                if universe_by_date
                else None
            ),
            signal_dates=signal_dates,
        )
        part_path = parts_dir / f"part_{batch_number:03d}.parquet"
        snapshots.to_parquet(part_path, index=False)
        # Only retain panel frames for bounded smoke runs. A full-universe
        # build leaves them on disk for month-wise ranking/replay.
        if not snapshots.empty and args.limit:
            panel_parts.append(snapshots)
        if not coverage.empty:
            coverage_parts.append(coverage)
        if not audit.empty:
            audit_parts.append(audit)
        peak_rss_mb = max(peak_rss_mb, _rss_mb())
        del prices, dividends, financials, snapshots, audit, coverage
        gc.collect()

    panels = pd.concat(panel_parts, ignore_index=True) if panel_parts else pd.DataFrame()
    coverage = pd.concat(coverage_parts, ignore_index=True) if coverage_parts else pd.DataFrame()
    audit = pd.concat(audit_parts, ignore_index=True) if audit_parts else pd.DataFrame()
    if not coverage.empty:
        coverage = (
            coverage.groupby("date", as_index=False)[
                ["price_rows", "dividend_coverage", "financial_coverage", "industry_coverage", "eligible_candidates"]
            ]
            .sum()
            .assign(has_target_holdings=lambda frame: frame["eligible_candidates"] >= config.top_n)
        )
    if args.limit:
        panels.to_parquet(output, index=False)
    coverage.to_csv(output.with_name("coverage.csv"), index=False)
    audit.to_csv(output.with_name("dividend_audit.csv"), index=False)
    safety = {
        "requested_stocks": args.limit or len(universe),
        "processed_stocks": len(universe),
        "batch_size": args.batch_size,
        "peak_rss_mb": round(peak_rss_mb, 1),
        "max_memory_mb": args.max_memory_mb,
        "stopped_for_memory": stopped_for_memory,
        "snapshot_rows": len(panels) if args.limit else int(coverage["price_rows"].sum()) if not coverage.empty else 0,
        "snapshot_months": int(panels["date"].nunique()) if not panels.empty else int(coverage["date"].nunique()) if not coverage.empty else 0,
        "min_eligible_candidates": int(coverage["eligible_candidates"].min()) if not coverage.empty else 0,
        "max_eligible_candidates": int(coverage["eligible_candidates"].max()) if not coverage.empty else 0,
        "months_with_target_holdings": int(coverage["has_target_holdings"].sum()) if not coverage.empty else 0,
    }
    output.with_name("safety_report.json").write_text(json.dumps(safety, ensure_ascii=False, indent=2))
    print(f"built {safety['snapshot_rows']} snapshot rows across {safety['snapshot_months']} months")
    print(f"safety report written to {output.with_name('safety_report.json')}")


def _complete_cached_codes(cache_dir: Path) -> set[str]:
    """Return only codes with every source required by strict PIT snapshots."""
    raw = {path.stem.removesuffix("_raw") for path in (cache_dir / "prices").glob("*_raw.parquet")}
    qfq = {path.stem.removesuffix("_qfq") for path in (cache_dir / "prices").glob("*_qfq.parquet")}
    dividend = {path.stem for path in (cache_dir / "dividends").glob("*.parquet")}
    cashflow = {path.stem.removesuffix("_cashflow") for path in (cache_dir / "financials").glob("*_cashflow.parquet")}
    profit = {path.stem.removesuffix("_profit") for path in (cache_dir / "financials").glob("*_profit.parquet")}
    return raw & qfq & dividend & cashflow & profit


def _signal_month(value: str | None) -> pd.Timestamp:
    """Return a requested month start or the current calendar month start."""
    if value is None:
        return pd.Timestamp.now().normalize().to_period("M").to_timestamp()
    parsed = pd.Timestamp(value)
    return parsed.to_period("M").to_timestamp()


def _rolling_data_end() -> str:
    """Default automatic-update boundary; reproducible runs pass --end explicitly."""
    return pd.Timestamp.now().normalize().date().isoformat()


def _first_session_in_month(cache_dir: Path, month: pd.Timestamp) -> pd.Timestamp:
    """Derive the exchange signal date from a cached reference calendar."""
    complete = sorted(_complete_cached_codes(cache_dir))
    if not complete:
        raise RuntimeError("no complete cached histories available")
    dates = pd.to_datetime(
        pd.read_parquet(cache_dir / "prices" / f"{complete[0]}_raw.parquet", columns=["date"])["date"],
        errors="coerce",
    ).dropna()
    observed = dates[(dates.dt.year == month.year) & (dates.dt.month == month.month)]
    if observed.empty:
        raise RuntimeError(f"price cache has no trading session in {month:%Y-%m}")
    return observed.min().normalize()


def _append_monthly_universe_audit(
    output: Path, signal_date: pd.Timestamp, universe: pd.DataFrame, cache_dir: Path
) -> None:
    """Append one universe audit row without destroying historical coverage."""
    path = output / "survivorship_audit.csv"
    live_path = cache_dir / "universe.parquet"
    live_codes = (
        set(pd.read_parquet(live_path)["code"].astype(str).str.zfill(6)) if live_path.exists() else set()
    )
    codes = set(universe["code"].dropna().astype(str).str.zfill(6))
    row = pd.DataFrame(
        [
            {
                "date": signal_date,
                "historical_codes": len(codes),
                "outside_live_cache": len(codes - live_codes),
                "live_cache_codes": len(codes & live_codes),
            }
        ]
    )
    prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
    merged = pd.concat([prior, row], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"]).dt.normalize()
    merged.drop_duplicates("date", keep="last").sort_values("date").to_csv(path, index=False)


def _monthly_entry_audit(
    holdings: pd.DataFrame, signal_date: pd.Timestamp, cache_dir: Path, config: StrategyConfig
) -> pd.DataFrame:
    """Use the same conservative buy-side checks as cached holdings backtests."""
    rows: list[dict[str, object]] = []
    for holding in holdings.itertuples():
        code = str(holding.code).zfill(6)
        path = cache_dir / "prices" / f"{code}_raw.parquet"
        if not path.exists():
            rows.append({"signal_date": signal_date, "code": code, "status": "missing_price"})
            continue
        raw = pd.read_parquet(path)
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.normalize()
        entry = raw[raw["date"] > signal_date].head(1)
        if entry.empty:
            rows.append({"signal_date": signal_date, "code": code, "status": "missing_price"})
            continue
        entry_date = entry.iloc[0]["date"]
        status = "executed"
        if _amount_or_zero(entry.iloc[0]) <= 0:
            status = "buy_suspended"
        elif _locked_limit(raw, entry_date, "buy"):
            status = "buy_limit_up"
        else:
            average_amount = pd.to_numeric(
                raw.loc[raw["date"] <= entry_date, "amount"], errors="coerce"
            ).tail(20).mean()
            order_value = config.initial_capital * float(holding.weight)
            if not np.isfinite(average_amount) or order_value > average_amount * config.max_order_to_avg_turnover:
                status = "liquidity_limit"
        rows.append(
            {
                "signal_date": signal_date,
                "entry_date": entry_date,
                "code": code,
                "weight": float(holding.weight),
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def cmd_update_monthly(args: argparse.Namespace) -> None:
    """Incrementally create one STRICT_B PIT signal without rewriting history."""
    config = _config(args)
    month = _signal_month(args.signal_month)
    signal_date = _first_session_in_month(config.cache_dir, month)
    universes = Path(args.universe_dir)
    universes.mkdir(parents=True, exist_ok=True)
    universe_path = universes / f"universe_asof_{signal_date:%Y%m%d}.parquet"
    if universe_path.exists() and not args.refresh_universe:
        universe = pd.read_parquet(universe_path)
    else:
        client = BaoStockClient(config.cache_dir, pause_seconds=args.pause_seconds)
        try:
            universe = client.universe_as_of(signal_date, refresh=args.refresh_universe)
        finally:
            client.close()
        if universe.empty:
            raise RuntimeError(f"no PIT universe available on {signal_date.date()}")
        universe.to_parquet(universe_path, index=False)
    universe = enrich_industries(universe, args.industry_map)
    _append_monthly_universe_audit(universes, signal_date, universe, config.cache_dir)
    available = _complete_cached_codes(config.cache_dir)
    universe = universe[universe["code"].astype(str).str.zfill(6).isin(available)].copy()
    if universe.empty:
        raise RuntimeError("monthly universe has no complete PIT source histories")

    panels, coverage_parts, audit_parts = [], [], []
    peak_rss_mb = _rss_mb()
    for batch_start in range(0, len(universe), args.batch_size):
        _check_rss(
            args.max_memory_mb,
            config.cache_dir / "monthly_update_safety.json",
            signal_date=str(signal_date.date()),
            processed_stocks=batch_start,
            requested_stocks=len(universe),
        )
        batch = universe.iloc[batch_start : batch_start + args.batch_size]
        codes = batch["code"].astype(str).str.zfill(6).tolist()
        prices, dividends, financials = load_cached_histories(config.cache_dir, codes)
        snapshots, audit, coverage = build_monthly_snapshots(
            batch, prices, dividends, financials, config, signal_dates=[signal_date]
        )
        if not snapshots.empty:
            panels.append(snapshots)
        if not coverage.empty:
            coverage_parts.append(coverage)
        if not audit.empty:
            audit_parts.append(audit)
        peak_rss_mb = max(peak_rss_mb, _rss_mb())
        del prices, dividends, financials, snapshots, audit, coverage
        gc.collect()
    panel = pd.concat(panels, ignore_index=True) if panels else pd.DataFrame()
    if panel.empty:
        raise RuntimeError(f"no PIT snapshot rows produced for {signal_date.date()}")
    holdings = select_portfolio(panel, config).assign(signal_date=signal_date)
    if len(holdings) != config.top_n or not np.isclose(holdings["weight"].sum(), 1.0):
        raise AssertionError("monthly STRICT_B selection violated frozen holding count or weights")
    max_industry = holdings.groupby("industry")["weight"].sum().max()
    if max_industry > config.max_industry_weight + 1e-12:
        raise AssertionError("monthly STRICT_B selection violated industry cap")

    output = Path(args.holdings)
    output.parent.mkdir(parents=True, exist_ok=True)
    prior = pd.read_parquet(output) if output.exists() else pd.DataFrame()
    if not prior.empty:
        prior["signal_date"] = pd.to_datetime(prior["signal_date"]).dt.normalize()
    updated = pd.concat(
        [prior[prior["signal_date"].ne(signal_date)] if not prior.empty else prior, holdings],
        ignore_index=True,
    ).sort_values(["signal_date", "code"])
    updated.to_parquet(output, index=False)
    update_dir = output.parent / "monthly_updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(update_dir / f"{signal_date:%Y%m%d}_snapshot.parquet", index=False)
    entry = _monthly_entry_audit(holdings, signal_date, config.cache_dir, config)
    entry.to_csv(update_dir / f"{signal_date:%Y%m%d}_entry_audit.csv", index=False)
    coverage = pd.concat(coverage_parts, ignore_index=True) if coverage_parts else pd.DataFrame()
    audit = pd.concat(audit_parts, ignore_index=True) if audit_parts else pd.DataFrame()
    coverage.to_csv(update_dir / f"{signal_date:%Y%m%d}_coverage.csv", index=False)
    audit.to_csv(update_dir / f"{signal_date:%Y%m%d}_dividend_audit.csv", index=False)
    _write_safety(
        update_dir / f"{signal_date:%Y%m%d}_audit.json",
        signal_date=str(signal_date.date()),
        as_of_date_max=str(signal_date.date()),
        selected=len(holdings),
        candidate_rows=len(panel),
        eligible_candidates=int(coverage["eligible_candidates"].sum()) if not coverage.empty else 0,
        max_industry_weight=float(max_industry),
        entry_execution_date=str(entry["entry_date"].min().date()) if "entry_date" in entry and entry["entry_date"].notna().any() else None,
        entry_status_counts=entry["status"].value_counts().to_dict(),
        peak_rss_mb=round(peak_rss_mb, 1),
        max_memory_mb=args.max_memory_mb,
    )
    print(f"updated {output} with {signal_date.date()} ({len(holdings)} holdings)")


def cmd_refresh_strict_verification(args: argparse.Namespace) -> None:
    """Refresh only STRICT_B final-verification rows from cached period returns."""
    config = _config(args)
    periods = pd.read_csv(args.periods)
    periods["signal_date"] = pd.to_datetime(periods["signal_date"]).dt.normalize()
    cutoff = pd.Timestamp(args.oos_start)
    rows = []
    for sample, frame in (
        ("all_sample", periods),
        ("in_sample", periods[periods["signal_date"] < cutoff]),
        ("out_of_sample", periods[periods["signal_date"] >= cutoff]),
    ):
        metrics = performance_metrics(frame["net_return"])
        rows.append(
            {
                "variant": "STRICT_B",
                "sample": sample,
                "periods": len(frame),
                "annual_return": metrics["annual_return"],
                "sharpe": metrics["sharpe"],
                "max_drawdown": metrics["max_drawdown"],
                "calmar": metrics["calmar"],
                "monthly_win_rate": metrics["win_rate"],
                "average_turnover": frame["turnover"].mean(),
                "cost_drag": frame["transaction_cost"].sum(),
            }
        )
    strict = pd.DataFrame(rows)
    core_path = config.reports_dir / "final_verification_core.csv"
    existing = pd.read_csv(core_path) if core_path.exists() else pd.DataFrame(columns=strict.columns)
    refreshed = pd.concat([existing[existing["variant"].ne("STRICT_B")], strict], ignore_index=True)
    refreshed.to_csv(core_path, index=False)
    monthly_path = config.reports_dir / "final_verification_strict_b_monthly_returns.csv"
    periods.to_csv(monthly_path, index=False)
    appendix = "\n".join(
        [
            "## 2026-07 STRICT_B 追加更新",
            "",
            (
                f"STRICT_B 已补入 2026-07-01 信号，封闭 2026-06-01 至 2026-07-01 持有期；"
                f"OOS 完整期由 23 增至 {len(periods[periods['signal_date'] >= cutoff])}。"
                "其余变体、OAT 稳健性与静态数据质量表保持原冻结结果，未混入本次追加。"
            ),
            "",
            strict.to_markdown(index=False, floatfmt=".4f"),
            "",
            f"月度净收益明细：`{monthly_path.name}`。",
        ]
    )
    summary_path = config.reports_dir / "final_verification_summary.md"
    original = summary_path.read_text(encoding="utf-8") if summary_path.exists() else "# 最终验证摘要表\n"
    marker = "\n## 2026-07 STRICT_B 追加更新\n"
    original = original.split(marker, 1)[0].rstrip()
    core_section = "\n".join(
        [
            "## 1. 核心绩效",
            "",
            "STRICT_B 已追加 2026-06-01→2026-07-01 完整持有期；其余变体仍为原冻结窗口。",
            "",
            refreshed.to_markdown(index=False, floatfmt=".4f"),
        ]
    )
    core_start, section_two = original.find("## 1. 核心绩效"), original.find("## 2.")
    if core_start >= 0 and section_two > core_start:
        original = original[:core_start].rstrip() + "\n\n" + core_section + "\n\n" + original[section_two:]
    summary_path.write_text(original.rstrip() + "\n\n" + appendix + "\n", encoding="utf-8")
    print(f"refreshed {core_path}, {monthly_path}, and {summary_path}")


def _rss_mb() -> float:
    """Current resident memory on Linux without an optional dependency."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def cmd_audit_dividends(args: argparse.Namespace) -> None:
    events = pd.read_parquet(args.events)
    prices = pd.read_parquet(args.prices)
    audit, metrics = audit_dividends(events, prices, args.code, args.as_of)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(destination, index=False)
    print(metrics)
    print(f"audit written to {destination}")


def cmd_audit_dividend_sample(args: argparse.Namespace) -> None:
    """Audit a bounded, reproducible sample of cached dividend histories."""
    config = _config(args)
    complete = sorted(_complete_cached_codes(config.cache_dir))
    # Deterministic strata: broad code range, prior dividend-event count and
    # historical-status availability. This avoids auditing only early codes.
    candidates = []
    for code in complete:
        dividend_path = config.cache_dir / "dividends" / f"{code}.parquet"
        count = len(pd.read_parquet(dividend_path)) if dividend_path.exists() else 0
        status_path = config.cache_dir / "baostock" / "status" / f"{code}.parquet"
        candidates.append((code, count, status_path.exists()))
    strata = [
        [code for code, count, historical in candidates if count >= 4 and historical],
        [code for code, count, _ in candidates if count >= 4],
        [code for code, count, _ in candidates if 1 <= count < 4],
        [code for code, count, historical in candidates if count == 0 or historical],
    ]
    codes = []
    for stratum in strata:
        for code in stratum:
            if code not in codes:
                codes.append(code)
            if len(codes) >= args.limit:
                break
        if len(codes) >= args.limit:
            break
    audit_rows, metric_rows = [], []
    cutoff = pd.Timestamp(args.as_of).normalize()
    for number, code in enumerate(codes, start=1):
        _check_rss(
            args.max_memory_mb,
            Path(args.output).with_suffix(".safety.json"),
            processed_stocks=number - 1,
            requested_stocks=len(codes),
        )
        events = pd.read_parquet(config.cache_dir / "dividends" / f"{code}.parquet")
        required_events = {
            "code",
            "report_year",
            "plan_id",
            "public_date",
            "ex_date",
            "cash_per_share",
            "plan_type",
            "status",
        }
        if not required_events.issubset(events.columns):
            from strategy_backtest.data.akshare_client import _normalize_cninfo_dividends

            events = _normalize_cninfo_dividends(events, code) if not events.empty else pd.DataFrame(
                columns=sorted(required_events)
            )
        prices = pd.read_parquet(config.cache_dir / "prices" / f"{code}_raw.parquet")
        audit, metrics = audit_dividend_stages(events, prices, code, cutoff)
        audit_rows.append(audit.assign(code=code))
        metric_rows.append({"code": code, **metrics})
        del events, prices, audit
        gc.collect()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(audit_rows, ignore_index=True).to_csv(output, index=False) if audit_rows else pd.DataFrame().to_csv(output, index=False)
    pd.DataFrame(metric_rows).to_csv(output.with_name("dividend_audit_metrics.csv"), index=False)
    _write_safety(
        output.with_suffix(".safety.json"),
        requested_stocks=len(codes),
        processed_stocks=len(metric_rows),
        peak_rss_mb=round(_rss_mb(), 1),
        max_memory_mb=args.max_memory_mb,
        stopped_for_memory=False,
    )


def cmd_rank_snapshot_parts(args: argparse.Namespace) -> None:
    """Rank one month at a time across all snapshot partitions."""
    config = _config(args)
    parts_dir = Path(args.parts_dir)
    parts = sorted(parts_dir.glob("part_*.parquet"))
    if not parts:
        raise RuntimeError(f"no snapshot parts found in {parts_dir}")
    first = pd.read_parquet(parts[0], columns=["date"])
    raw_dates = pd.to_datetime(first["date"]).dt.normalize()
    # Older snapshot partitions may contain extra dates from an imperfect
    # calendar build. Ranking always uses exactly one signal date per month.
    dates = sorted(
        pd.Series(raw_dates).groupby(pd.Series(raw_dates).dt.to_period("M")).min().tolist()
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    holding_rows, summary_rows = [], []
    peak_rss_mb = _rss_mb()
    for date in dates:
        monthly = []
        for path in parts:
            frame = pd.read_parquet(path)
            frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
            selected = frame[frame["date"].eq(date)]
            if not selected.empty:
                monthly.append(selected)
            del frame
        panel = pd.concat(monthly, ignore_index=True) if monthly else pd.DataFrame()
        _check_rss(
            args.max_memory_mb,
            output.with_name("ranking_safety.json"),
            parts=len(parts),
            processed_months=len(summary_rows),
        )
        if panel.empty:
            continue
        try:
            holdings = select_portfolio(panel, config)
            holding_rows.append(holdings.assign(signal_date=date))
            summary_rows.append({"date": date, "candidates": len(panel), "status": "selected"})
        except ValueError as error:
            summary_rows.append({"date": date, "candidates": len(panel), "status": str(error)})
        peak_rss_mb = max(peak_rss_mb, _rss_mb())
        del monthly, panel
        gc.collect()
    holdings = pd.concat(holding_rows, ignore_index=True) if holding_rows else pd.DataFrame()
    summary = pd.DataFrame(summary_rows)
    holdings.to_parquet(output, index=False)
    summary.to_csv(output.with_name("ranking_summary.csv"), index=False)
    output.with_name("ranking_safety.json").write_text(
        json.dumps(
            {
                "parts": len(parts),
                "months": len(dates),
                "peak_rss_mb": round(peak_rss_mb, 1),
                "max_memory_mb": args.max_memory_mb,
                "holding_rows": len(holdings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"ranked {len(dates)} months; wrote {len(holdings)} holdings")


def cmd_coverage(args: argparse.Namespace) -> None:
    config = _config(args)
    coverage, summary = scan_cache_coverage(config.cache_dir)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    output = config.reports_dir / "source_coverage.csv"
    coverage.to_csv(output, index=False)
    save_report(render_readiness_report(coverage, summary), config.reports_dir, "data_readiness.md")
    print(coverage.to_string(index=False))
    print(summary)
    print(f"coverage written to {output}")


def cmd_backtest(args: argparse.Namespace) -> None:
    config = _config(args)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    snapshots_frame = pd.read_parquet(args.snapshots)
    snapshots_frame["date"] = pd.to_datetime(snapshots_frame["date"]).dt.normalize()
    snapshots = {date: group.drop(columns="date").copy() for date, group in snapshots_frame.groupby("date")}
    prices = pd.read_parquet(args.prices)
    result = backtest_monthly(snapshots, prices, config)
    data_notes = {"snapshot_rows": len(snapshots_frame), "snapshot_months": snapshots_frame["date"].nunique()}
    if args.benchmark:
        benchmark = pd.read_parquet(args.benchmark)
        benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
        benchmark_return = pd.to_numeric(benchmark["adjusted_close"], errors="coerce").pct_change()
        benchmark_monthly = (
            pd.DataFrame({"date": benchmark["date"], "benchmark_return": benchmark_return})
            .groupby(pd.Grouper(key="date", freq="MS"))["benchmark_return"]
            .apply(lambda values: (1 + values.dropna()).prod() - 1)
            .reset_index()
        )
        aligned = result["periods"].merge(
            benchmark_monthly, left_on="signal_date", right_on="date", how="left"
        )
        result["relative_metrics"] = relative_metrics(aligned["net_return"], aligned["benchmark_return"])
        aligned.to_csv(config.reports_dir / "benchmark_periods.csv", index=False)
    report = save_report(render_backtest_report(result, data_notes), config.reports_dir)
    result["periods"].to_csv(config.reports_dir / "periods.csv", index=False)
    result["holdings_frame"].to_csv(config.reports_dir / "holdings.csv", index=False)
    result["industry_exposure"].to_csv(config.reports_dir / "industry_exposure.csv", index=False)
    drawdown_table(result["periods"].set_index("signal_date")["net_return"]).to_csv(
        config.reports_dir / "drawdowns.csv", index=False
    )
    returns = result["periods"].set_index("signal_date")["net_return"]
    yearly_returns(returns).to_csv(config.reports_dir / "yearly.csv", index=False)
    rolling_metrics(returns, 12).to_csv(config.reports_dir / "rolling_12m.csv", index=False)
    rolling_metrics(returns, 36).to_csv(config.reports_dir / "rolling_36m.csv", index=False)
    if args.robustness:
        run_top_n_sensitivity(snapshots, prices, config).to_csv(config.reports_dir / "robustness.csv", index=False)
    print(result["metrics"])
    print(f"report written to {report}")


def cmd_backtest_cached_holdings(args: argparse.Namespace) -> None:
    """Run an out-of-core backtest from partitioned AkShare price history."""
    config = _config(args)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    holdings = pd.read_parquet(args.holdings)
    result = backtest_cached_holdings(holdings, config.cache_dir, config)
    report = save_report(
        render_backtest_report(
            result,
            {"execution": "partitioned cache", "holding_rows": len(holdings), "price_loading": "held stocks only"},
        ),
        config.reports_dir,
        "cached_backtest.md",
    )
    result["periods"].to_csv(config.reports_dir / "cached_periods.csv", index=False)
    result["industry_exposure"].to_csv(config.reports_dir / "cached_industry_exposure.csv", index=False)
    if "executions" in result:
        result["executions"].to_csv(config.reports_dir / "cached_executions.csv", index=False)
    drawdown_table(result["periods"].set_index("signal_date")["net_return"]).to_csv(
        config.reports_dir / "cached_drawdowns.csv", index=False
    )
    print(result["metrics"])
    print(f"report written to {report}")


def cmd_build_universe(args: argparse.Namespace) -> None:
    """Build monthly historical BaoStock universes without full-market prices."""
    config = _config(args)
    client = BaoStockClient(config.cache_dir, pause_seconds=args.pause_seconds)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range(args.start, args.end, freq="MS")
    if not args.full:
        dates = dates[: args.limit]
    live_path = config.cache_dir / "universe.parquet"
    live_codes = set()
    if live_path.exists():
        live_codes = set(pd.read_parquet(live_path)["code"].astype(str).str.zfill(6))
    audit_rows = []
    peak_rss_mb = _rss_mb()
    try:
        for number, date in enumerate(dates, start=1):
            _check_rss(
                args.max_memory_mb,
                output / "universe_safety.json",
                processed_months=number - 1,
                requested_months=len(dates),
            )
            universe = client.universe_as_of(date, refresh=args.refresh)
            # Month starts can be holidays. Query the first available trading
            # day, matching the strategy's monthly signal convention.
            actual_date = date
            for offset in range(1, 11):
                if not universe.empty:
                    break
                actual_date = date + pd.Timedelta(days=offset)
                universe = client.universe_as_of(actual_date, refresh=args.refresh)
            if not universe.empty:
                universe.to_parquet(output / f"universe_asof_{actual_date:%Y%m%d}.parquet", index=False)
                codes = set(universe["code"].dropna().astype(str).str.zfill(6))
                audit_rows.append(
                    {
                        "date": actual_date,
                        "historical_codes": len(codes),
                        "outside_live_cache": len(codes - live_codes),
                        "live_cache_codes": len(codes & live_codes),
                    }
                )
            peak_rss_mb = max(peak_rss_mb, _rss_mb())
            del universe
            gc.collect()
    finally:
        client.close()
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(output / "survivorship_audit.csv", index=False)
    _write_safety(
        output / "universe_safety.json",
        requested_months=len(dates),
        processed_months=len(audit),
        peak_rss_mb=round(peak_rss_mb, 1),
        max_memory_mb=args.max_memory_mb,
        stopped_for_memory=False,
    )
    print(f"built {len(audit)} monthly universes; audit written to {output / 'survivorship_audit.csv'}")


def cmd_fetch_baostock_status(args: argparse.Namespace) -> None:
    """Fetch bounded historical ST/suspension panels for listed code input."""
    config = _config(args)
    codes = pd.read_parquet(args.codes)["code"].astype(str).str.zfill(6).drop_duplicates().tolist()
    if not args.full:
        codes = codes[: args.limit]
    client = BaoStockClient(config.cache_dir, pause_seconds=args.pause_seconds)
    rows, peak_rss_mb = [], _rss_mb()
    try:
        for number, code in enumerate(codes, start=1):
            _check_rss(
                args.max_memory_mb,
                config.cache_dir / "baostock_status_safety.json",
                processed_stocks=number - 1,
                requested_stocks=len(codes),
            )
            try:
                frame = client.daily_status(code, args.start, args.end, refresh=args.refresh)
                rows.append({"code": code, "rows": len(frame), "status": "cached"})
            except Exception as error:  # noqa: BLE001 - provider errors are audit rows, not fatal
                rows.append({"code": code, "rows": 0, "status": str(error)})
            peak_rss_mb = max(peak_rss_mb, _rss_mb())
            if number % 10 == 0:
                print(f"processed {number}/{len(codes)}; rss={_rss_mb():.1f}MB")
            gc.collect()
    finally:
        client.close()
    pd.DataFrame(rows).to_csv(config.cache_dir / "baostock_status_coverage.csv", index=False)
    _write_safety(
        config.cache_dir / "baostock_status_safety.json",
        requested_stocks=len(codes),
        processed_stocks=len(rows),
        peak_rss_mb=round(peak_rss_mb, 1),
        max_memory_mb=args.max_memory_mb,
        stopped_for_memory=False,
    )


def cmd_fetch_historical_missing(args: argparse.Namespace) -> None:
    """Incrementally fill cached histories for codes found only in old universes."""
    config = _config(args)
    universe_files = sorted(Path(args.universe_dir).glob("universe_asof_*.parquet"))
    if not universe_files:
        raise RuntimeError(f"no universe files found in {args.universe_dir}")
    codes = sorted(
        {
            code
            for path in universe_files
            for code in pd.read_parquet(path)["code"].dropna().astype(str).str.zfill(6)
        }
    )
    missing = [code for code in codes if code not in _complete_cached_codes(config.cache_dir)]
    if not args.full:
        missing = missing[: args.limit]
    source = getattr(args, "source", "baostock")
    ak_client = AkShareClient(config.cache_dir, sleep_seconds=args.pause_seconds)
    bs_client = BaoStockClient(config.cache_dir, pause_seconds=args.pause_seconds)
    rows, peak_rss_mb = [], _rss_mb()
    try:
        for number, code in enumerate(missing, start=1):
            _check_rss(
                args.max_memory_mb,
                config.cache_dir / "historical_fetch_safety.json",
                processed_stocks=number - 1,
                requested_stocks=len(missing),
            )
            try:
                if source == "akshare":
                    ak_client.daily_prices(code, refresh=args.refresh)
                    ak_client.dividends(code, refresh=args.refresh)
                    ak_client.financials(code, refresh=args.refresh)
                    rows.append({"code": code, "status": "cached_akshare", "price_rows": None})
                else:
                    # Default path for delisted / AkShare-missing names.
                    result = bs_client.fill_delisted_history(
                        code,
                        start=args.start,
                        end=args.end,
                        years=range(args.finance_start_year, args.finance_end_year + 1),
                        refresh=args.refresh,
                    )
                    rows.append(result)
            except Exception as error:  # noqa: BLE001 - historical provider errors are audit rows
                rows.append({"code": code, "status": str(error), "price_rows": 0})
            peak_rss_mb = max(peak_rss_mb, _rss_mb())
            if number % 10 == 0:
                print(f"processed {number}/{len(missing)}; rss={_rss_mb():.1f}MB")
            gc.collect()
    finally:
        bs_client.close()
    coverage_path = config.cache_dir / "historical_fetch_coverage.csv"
    batch = pd.DataFrame(rows)
    if coverage_path.exists() and not args.refresh:
        previous = pd.read_csv(coverage_path)
        batch = pd.concat([previous, batch], ignore_index=True).drop_duplicates("code", keep="last")
    batch.to_csv(coverage_path, index=False)
    _write_safety(
        config.cache_dir / "historical_fetch_safety.json",
        requested_stocks=len(missing),
        processed_stocks=len(rows),
        peak_rss_mb=round(peak_rss_mb, 1),
        max_memory_mb=args.max_memory_mb,
        stopped_for_memory=False,
        source=source,
        cached_baostock=int((batch["status"] == "cached_baostock").sum()) if "status" in batch else 0,
        no_price_history=int((batch["status"] == "no_price_history").sum()) if "status" in batch else 0,
    )


def cmd_compare_variants(args: argparse.Namespace) -> None:
    """Run already-ranked variants sequentially and lock an OOS split."""
    config = _config(args)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    benchmark_monthly = None
    if args.benchmark:
        benchmark = pd.read_parquet(args.benchmark)
        benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.normalize()
        price_column = "adjusted_close" if "adjusted_close" in benchmark else "close"
        benchmark["return"] = pd.to_numeric(benchmark[price_column], errors="coerce").pct_change()
        benchmark_monthly = (
            benchmark.groupby(pd.Grouper(key="date", freq="MS"))["return"]
            .apply(lambda values: (1 + values.dropna()).prod() - 1)
            .rename("benchmark_return")
            .reset_index()
        )
    rows = []
    for item in args.holdings:
        try:
            variant, path_text = item.split("=", 1)
        except ValueError as error:
            raise ValueError("--holdings must use VARIANT=PATH") from error
        holdings = pd.read_parquet(path_text)
        result = backtest_cached_holdings(holdings, config.cache_dir, config)
        periods = result["periods"].copy()
        periods.to_csv(config.reports_dir / f"{variant}_periods.csv", index=False)
        if not periods.empty:
            yearly_returns(periods.set_index("signal_date")["net_return"]).to_csv(
                config.reports_dir / f"{variant}_yearly.csv", index=False
            )
            if benchmark_monthly is not None:
                environment = periods.merge(
                    benchmark_monthly, left_on="signal_date", right_on="date", how="left"
                )
                environment["regime"] = pd.cut(
                    environment["benchmark_return"],
                    bins=[float("-inf"), -0.03, 0.03, float("inf")],
                    labels=["bear", "range", "bull"],
                )
                (
                    environment.groupby("regime", observed=False)
                    .agg(
                        periods=("net_return", "size"),
                        strategy_return=("net_return", "mean"),
                        benchmark_return=("benchmark_return", "mean"),
                    )
                    .reset_index()
                    .to_csv(config.reports_dir / f"{variant}_market_regimes.csv", index=False)
                )
        result["industry_exposure"].to_csv(config.reports_dir / f"{variant}_industry_exposure.csv", index=False)
        exposure = result["industry_exposure"]
        if not exposure.empty:
            hhi = (
                exposure.assign(weight_sq=lambda frame: frame["weight"] ** 2)
                .groupby("signal_date", as_index=False)["weight_sq"]
                .sum()
                .rename(columns={"weight_sq": "industry_hhi"})
            )
            hhi.to_csv(config.reports_dir / f"{variant}_industry_hhi.csv", index=False)
        if "executions" in result:
            result["executions"].to_csv(config.reports_dir / f"{variant}_executions.csv", index=False)
        for sample, sample_periods in (
            ("in_sample", periods[pd.to_datetime(periods["signal_date"]) < pd.Timestamp(args.oos_start)]),
            ("out_of_sample", periods[pd.to_datetime(periods["signal_date"]) >= pd.Timestamp(args.oos_start)]),
        ):
            metrics = performance_metrics(sample_periods["net_return"])
            rows.append(
                {
                    "variant": variant,
                    "sample": sample,
                    "periods": len(sample_periods),
                    **metrics,
                    "average_turnover": float(sample_periods["turnover"].mean()) if not sample_periods.empty else float("nan"),
                    "cost_drag": float(sample_periods.get("transaction_cost", pd.Series(dtype=float)).sum()),
                }
            )
    summary = pd.DataFrame(rows)
    summary.to_csv(config.reports_dir / "variant_comparison.csv", index=False)
    survivorship_path = Path(args.survivorship_audit) if args.survivorship_audit else None
    survivorship = pd.read_csv(survivorship_path) if survivorship_path and survivorship_path.exists() else None
    report = save_report(
        render_comparative_report(summary, survivorship),
        config.reports_dir,
        "comparative_research.md",
    )
    print(f"wrote {report}")


def cmd_prepare_regime_market(args: argparse.Namespace) -> None:
    """Cache fixed index series and choose the ETF proxy without return selection."""
    config = _config(args)
    client = MarketDataClient(config.cache_dir)
    broad = client.index("000985", refresh=args.refresh)
    divlow = client.index("H30269", refresh=args.refresh)
    broad.to_parquet(config.cache_dir / "market" / "indices" / "000985.parquet", index=False)
    divlow.to_parquet(config.cache_dir / "market" / "indices" / "H30269.parquet", index=False)
    candidates = [value.strip() for value in args.etf_candidates.split(",") if value.strip()]
    rows, available = [], []
    for code in candidates:
        try:
            etf = client.etf(code, refresh=args.refresh)
            merged = broad.merge(etf, on="date", suffixes=("_index", "_etf"))
            calibration = merged[
                (merged["date"] >= pd.Timestamp("2018-01-01"))
                & (merged["date"] < pd.Timestamp("2019-01-01"))
            ].copy()
            tracking_error = (
                (calibration["close_etf"].pct_change() - calibration["close_index"].pct_change())
                .dropna()
                .std()
                * (252**0.5)
            )
            eligible = (
                etf["date"].min() <= pd.Timestamp("2019-01-02")
                and etf["date"].max() >= pd.Timestamp(args.required_end)
                and len(calibration) >= 120
            )
            row = {
                "etf_code": code,
                "status": "eligible" if eligible else "insufficient_coverage",
                "start": etf["date"].min(),
                "end": etf["date"].max(),
                "calibration_days": len(calibration),
                "tracking_error_2018": tracking_error,
                "mean_daily_amount": pd.to_numeric(etf.get("amount"), errors="coerce").mean(),
            }
            rows.append(row)
            if eligible:
                available.append((row, etf))
        except Exception as error:  # noqa: BLE001 - remote provider error is reported per candidate
            rows.append({"etf_code": code, "status": f"fetch_failed:{error}"})
    audit = pd.DataFrame(rows)
    if not available:
        raise RuntimeError("no eligible broad-market ETF candidate with full research coverage")
    ranked = sorted(
        available,
        key=lambda item: (
            float(item[0]["tracking_error_2018"]) if pd.notna(item[0]["tracking_error_2018"]) else float("inf"),
            -float(item[0]["mean_daily_amount"]) if pd.notna(item[0]["mean_daily_amount"]) else float("inf"),
            item[0]["start"],
        ),
    )
    selected, etf = ranked[0]
    selected["proxy_selection_rule"] = "coverage_then_2018_tracking_error_then_amount_then_history"
    audit["selected"] = audit["etf_code"].eq(selected["etf_code"])
    # Current official product disclosure for the selected predeclared proxy.
    # Daily market prices already embed these fund-level charges; never deduct
    # them again from the ETF trade return.
    if selected["etf_code"] == "510500":
        audit.loc[audit["selected"], "fund_name"] = "南方中证500ETF"
        audit.loc[audit["selected"], "tracked_index"] = "中证500"
        audit.loc[audit["selected"], "management_fee_annual"] = 0.0015
        audit.loc[audit["selected"], "custody_fee_annual"] = 0.0005
        audit.loc[audit["selected"], "fee_source"] = "SSE 510500 2026-03 product summary"
    audit.loc[audit["selected"], "price_series_treatment"] = (
        "provider_qfq_when_available; Sina trade-price fallback; fees not double-counted"
    )
    audit_path = config.cache_dir / "market" / "etf_proxy_audit.csv"
    audit.to_csv(audit_path, index=False)
    etf.to_parquet(config.cache_dir / "market" / "etfs" / "selected_proxy.parquet", index=False)
    _write_safety(
        config.cache_dir / "market" / "market_data_safety.json",
        broad_rows=len(broad),
        divlow_rows=len(divlow),
        selected_etf=selected["etf_code"],
        selected_etf_start=str(selected["start"]),
        selected_etf_end=str(selected["end"]),
    )
    print(f"selected ETF proxy: {selected['etf_code']}; audit={audit_path}")


def cmd_build_regime_breadth(args: argparse.Namespace) -> None:
    """Build only monthly T-1 breadth observations under a bounded RSS limit."""
    config = _config(args)
    holdings = pd.read_parquet(args.holdings)
    safety_path = config.cache_dir / "market" / "breadth_safety.json"

    def check(**context: object) -> None:
        _check_rss(args.max_memory_mb, safety_path, **context)

    breadth = compute_monthly_breadth(
        holdings["signal_date"],
        args.universe_dir,
        config.cache_dir / "prices",
        batch_size=args.batch_size,
        rss_check=check,
    )
    output = config.cache_dir / "market" / "breadth_120ma_monthly.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    breadth.to_parquet(output, index=False)
    _write_safety(
        safety_path,
        months=len(breadth),
        peak_rss_mb=round(_rss_mb(), 1),
        max_memory_mb=args.max_memory_mb,
        batch_size=args.batch_size,
        valid_ma_min=int(breadth["valid_ma_count"].min()) if "valid_ma_count" in breadth else 0,
    )
    print(f"wrote {output}")


def _regime_report(
    detail: pd.DataFrame,
    attribution: pd.DataFrame,
    etf_audit: pd.DataFrame,
    market_audit: pd.DataFrame,
) -> str:
    main = detail[
        (detail["result_type"] == "performance")
        & detail["condition"].isin(REGIME_CONDITIONS)
        & detail["mode"].isin(["Always", "Cash", "BenchmarkETF"])
    ].copy()
    columns = [
        "condition",
        "mode",
        "sample",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "calmar",
        "win_rate",
        "average_turnover",
        "strict_b_exposure",
        "condition_switches",
        "longest_cash_periods",
        "transition_cost_drag",
        "annual_return_vs_always",
        "max_drawdown_improvement_vs_always",
    ]
    sensitivity = detail[
        (detail["result_type"] == "performance")
        & detail["condition"].isin(["E_vol20_p60", "E_vol20_p70", "E_vol20_p80", "F_breadth30", "F_breadth40", "F_breadth50"])
        & detail["mode"].isin(["Cash", "BenchmarkETF"])
    ].copy()
    oos = main[(main["sample"] == "out_of_sample") & (main["mode"] != "Always")]
    cash = oos[oos["mode"] == "Cash"]
    etf = oos[oos["mode"] == "BenchmarkETF"]
    sensitivity_oos = sensitivity[sensitivity["sample"] == "out_of_sample"]
    cash_return_wins = int((cash["annual_return_vs_always"] > 0).sum())
    cash_dd_wins = int((cash["max_drawdown_improvement_vs_always"] > 0).sum())
    etf_return_wins = int((etf["annual_return_vs_always"] > 0).sum())
    etf_dd_wins = int((etf["max_drawdown_improvement_vs_always"] > 0).sum())
    sensitivity_wins = int((sensitivity_oos["annual_return_vs_always"] > 0).sum())
    lines = [
        "# STRICT_B 市场状态过滤研究",
        "",
        "口径：STRICT_B 持仓、PIT 分红、股票 T+1 成交、股票成本和不可交易规则均冻结。所有状态在调仓日前一交易日收盘后计算；BenchmarkETF 是可交易 ETF 覆盖层，BenchmarkIndexUpperBound 仅是无成本理论上限。",
        "",
        "## 主结果",
        "",
        main[columns].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 状态归因",
        "",
        attribution.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## ETF 代理审计",
        "",
        etf_audit.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 市场数据覆盖",
        "",
        market_audit.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 预设阈值敏感性",
        "",
        sensitivity[
            [
                "condition",
                "mode",
                "sample",
                "annual_return",
                "sharpe",
                "max_drawdown",
                "annual_return_vs_always",
                "max_drawdown_improvement_vs_always",
            ]
        ].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 结论",
        "",
        f"- 绝对收益：OOS 中 Cash 的 7 个主条件有 {cash_return_wins} 个超过 Always；BenchmarkETF 有 {etf_return_wins} 个超过 Always。BenchmarkETF 的改善来自替换为 ETF 市场暴露，不能归因于“空仓择时”。",
        f"- 回撤：OOS 中 Cash 的 {cash_dd_wins}/7 个主条件改善最大回撤；BenchmarkETF 为 {etf_dd_wins}/7 个。若收益改善但回撤恶化，覆盖层不满足风险调整改善。",
        "- 市场暴露：Cash 的严格 B 在场比例直接量化了降低个股/红利低波暴露的程度；BenchmarkETF 的非 STRICT_B 月仍在宽基 ETF 中，因此不是减仓到现金。",
        f"- OOS 与阈值：E/F 的预设敏感性在 OOS 共有 {sensitivity_wins}/{len(sensitivity_oos)} 个结果超过 Always。该计数只用于稳健性判断，不用于选择交易阈值；单点有效或 OOS 不一致均按阈值过拟合风险处理。",
        "- 低谷期归因：`trough_proxy=down_and_weak_breadth` 是事前可观测的下跌且弱宽度交集，不使用事后最低点；其月份数、均值和胜率见状态归因表，小样本 OOS 不构成强结论。",
        "",
        "## 解读规则",
        "",
        "- 绝对收益：比较各模式的 `annual_return_vs_always`；正值才是提高收益。",
        "- 回撤：`max_drawdown_improvement_vs_always` 为正才是降低最大回撤。",
        "- 市场暴露：Cash/ETF 模式的 `strict_b_exposure` 越低，改善越可能主要来自降低 STRICT_B 暴露；ETF 模式仍保持股票市场暴露。",
        "- OOS：仅 `sample=out_of_sample` 的结论可用于独立验证，不能据此重调阈值。",
        "- 阈值过拟合：E 的 60/70/80 分位与 F 的 30/40/50% 全部披露；若仅单一阈值有效或 OOS 不成立，结论标记为不稳健。",
    ]
    return "\n".join(lines)


def cmd_regime_research(args: argparse.Namespace) -> None:
    """Run frozen STRICT_B market-regime overlays and write final two artifacts."""
    config = _config(args)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    holdings = pd.read_parquet(args.holdings)
    strict = backtest_cached_holdings(holdings, config.cache_dir, config)["periods"].copy()
    signal_dates = sorted(pd.to_datetime(holdings["signal_date"]).drop_duplicates())
    strict["signal_date"] = pd.to_datetime(strict["signal_date"]).dt.normalize()
    strict["next_signal_date"] = signal_dates[1:]
    market_root = config.cache_dir / "market"
    broad = pd.read_parquet(market_root / "indices" / "000985.parquet")
    divlow = pd.read_parquet(market_root / "indices" / "H30269.parquet")
    breadth = pd.read_parquet(market_root / "breadth_120ma_monthly.parquet")
    signals = compute_regime_signals(broad, divlow, signal_dates, breadth)
    # The predeclared sensitivity uses the same live 3-year history, not a
    # cross-sectional/full-sample estimate.
    broad_live = broad.copy()
    broad_live["date"] = pd.to_datetime(broad_live["date"]).dt.normalize()
    broad_live["ret1"] = broad_live["close"].pct_change()
    broad_live["vol20"] = broad_live["ret1"].rolling(20, min_periods=20).std() * (252**0.5)
    for quantile, label in ((0.60, "E_vol20_p60"), (0.80, "E_vol20_p80")):
        broad_live[label] = broad_live["vol20"].rolling(756, min_periods=252).quantile(quantile)
        values = []
        for signal_date in signals["signal_date"]:
            visible = broad_live[broad_live["date"] < signal_date]
            values.append(np.nan if visible.empty else visible["vol20"].iloc[-1] > visible[label].iloc[-1])
        signals[label] = values
    signals["F_breadth30"] = signals["breadth_pct"] < 0.30
    signals["F_breadth50"] = signals["breadth_pct"] < 0.50
    signals.to_parquet(market_root / "regime_signals.parquet", index=False)
    etf = pd.read_parquet(market_root / "etfs" / "selected_proxy.parquet")
    etf_returns = etf_period_returns(etf, strict)
    all_rows: list[dict[str, object]] = []
    conditions = list(REGIME_CONDITIONS) + ["E_vol20_p60", "E_vol20_p80", "F_breadth30", "F_breadth50"]
    for condition in conditions:
        always = run_overlay(strict, signals, condition, config, etf_returns, "Always")
        for mode, upper_bound in (
            ("Always", False),
            ("Cash", False),
            ("BenchmarkETF", False),
            ("BenchmarkIndexUpperBound", True),
        ):
            result = run_overlay(
                strict, signals, condition, config, etf_returns, mode if mode != "BenchmarkIndexUpperBound" else "BenchmarkETF", upper_bound
            )
            for sample in ("all_sample", "in_sample", "out_of_sample"):
                row = overlay_summary(result, always, sample, args.oos_start)
                row.update({"result_type": "performance", "condition": condition, "mode": mode})
                all_rows.append(row)
    attribution = state_attribution(strict, signals, args.oos_start)
    attribution["result_type"] = "attribution"
    etf_audit = pd.read_csv(market_root / "etf_proxy_audit.csv")
    etf_audit["result_type"] = "etf_audit"
    market_audit = pd.DataFrame(
        [
            {
                "market_series": "中证全指",
                "market_code": "000985",
                "start": pd.to_datetime(broad["date"]).min(),
                "end": pd.to_datetime(broad["date"]).max(),
                "rows": len(broad),
            },
            {
                "market_series": "中证红利低波",
                "market_code": "H30269",
                "start": pd.to_datetime(divlow["date"]).min(),
                "end": pd.to_datetime(divlow["date"]).max(),
                "rows": len(divlow),
            },
        ]
    )
    market_audit["result_type"] = "market_data_audit"
    detail = pd.concat(
        [pd.DataFrame(all_rows), attribution, etf_audit, market_audit], ignore_index=True, sort=False
    )
    detail_path = config.reports_dir / "strict_b_regime_detail.csv"
    detail.to_csv(detail_path, index=False)
    report_path = config.reports_dir / "strict_b_regime_summary.md"
    report_path.write_text(
        _regime_report(detail, attribution, etf_audit, market_audit), encoding="utf-8"
    )
    print(f"wrote {detail_path} and {report_path}")


def _exposure_report(detail: pd.DataFrame, state_counts: pd.DataFrame) -> str:
    columns = [
        "scheme",
        "sample",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "calmar",
        "average_turnover",
        "average_target_exposure",
        "scaled_strict_cost_drag",
        "transition_cost_drag",
        "total_cost_drag",
        "annual_return_vs_always",
        "max_drawdown_improvement_vs_always",
        "annual_return_vs_hard_cash",
        "sharpe_vs_hard_cash",
        "max_drawdown_improvement_vs_hard_cash",
        "total_cost_drag_vs_hard_cash",
    ]
    oos = detail[detail["sample"].eq("out_of_sample")]
    soft = oos[oos["scheme"].isin(["Soft75", "Soft50", "TrendScaling"])]
    soft_vs_cash = detail[detail["scheme"].isin(["Soft75", "Soft50", "TrendScaling"])][
        [
            "scheme",
            "sample",
            "annual_return_vs_hard_cash",
            "sharpe_vs_hard_cash",
            "max_drawdown_improvement_vs_hard_cash",
            "average_turnover_vs_hard_cash",
            "total_cost_drag_vs_hard_cash",
        ]
    ]
    robust = soft[
        (soft["sharpe"] > oos.loc[oos["scheme"].eq("Always"), "sharpe"].iloc[0])
        & (soft["max_drawdown_improvement_vs_always"] > 0)
        & (soft["sharpe_vs_hard_cash"] >= 0)
        & (soft["max_drawdown_improvement_vs_hard_cash"] >= 0)
    ]
    lines = [
        "# STRICT_B 连续仓位测试",
        "",
        "口径：冻结 STRICT_B、PIT 分红、股票成本和 T+1 成交。状态仅复用已有 T−1 `ret120` 与 `breadth<40%`；不重新定义状态或优化阈值。现金收益为零。",
        "",
        "## 主结果",
        "",
        detail[columns].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Soft 相对 HardCash",
        "",
        soft_vs_cash.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 预设状态月份数",
        "",
        state_counts.to_markdown(index=False),
        "",
        "## OOS 判断",
        "",
        f"- OOS 中满足“Sharpe 高于 Always、最大回撤更浅、且不逊于 HardCash”的软仓位方案数：{len(robust)}/3。",
        "- 只有上述条件同时满足的方案才可称为比硬切换更稳健；若不满足，结论为“不得推荐用于实盘”。",
        "- 所有比较均为预设方案并列展示，不按本表选择未来仓位或阈值。",
    ]
    return "\n".join(lines)


def cmd_regime_exposure_research(args: argparse.Namespace) -> None:
    """Run fixed continuous STRICT_B/cash exposure schedules."""
    config = _config(args)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    holdings = pd.read_parquet(args.holdings)
    strict = backtest_cached_holdings(holdings, config.cache_dir, config)["periods"].copy()
    strict["signal_date"] = pd.to_datetime(strict["signal_date"]).dt.normalize()
    signals = pd.read_parquet(config.cache_dir / "market" / "regime_signals.parquet")
    signals["signal_date"] = pd.to_datetime(signals["signal_date"]).dt.normalize()
    always = run_continuous_exposure(strict, signals, "Always", config)
    results: list[dict[str, object]] = []
    for scheme in EXPOSURE_SCHEMES:
        frame = run_continuous_exposure(strict, signals, scheme, config)
        for sample in ("all_sample", "in_sample", "out_of_sample"):
            row = exposure_summary(frame, always, sample, args.oos_start)
            row["scheme"] = scheme
            results.append(row)
    detail = pd.DataFrame(results)
    for sample, group in detail.groupby("sample"):
        always_row = group[group["scheme"].eq("Always")].iloc[0]
        cash_row = group[group["scheme"].eq("HardCash")].iloc[0]
        mask = detail["sample"].eq(sample)
        detail.loc[mask, "annual_return_vs_hard_cash"] = (
            detail.loc[mask, "annual_return"] - cash_row["annual_return"]
        )
        detail.loc[mask, "sharpe_vs_hard_cash"] = detail.loc[mask, "sharpe"] - cash_row["sharpe"]
        detail.loc[mask, "max_drawdown_improvement_vs_hard_cash"] = (
            abs(cash_row["max_drawdown"]) - abs(detail.loc[mask, "max_drawdown"])
        )
        detail.loc[mask, "average_turnover_vs_hard_cash"] = (
            detail.loc[mask, "average_turnover"] - cash_row["average_turnover"]
        )
        detail.loc[mask, "total_cost_drag_vs_hard_cash"] = (
            detail.loc[mask, "total_cost_drag"] - cash_row["total_cost_drag"]
        )
        # Guard frozen baseline identity during every formal exposure run.
        if always_row["annual_return_vs_always"] != 0:
            raise AssertionError("Always exposure overlay must equal frozen STRICT_B")
    state_frame = run_continuous_exposure(strict, signals, "TrendScaling", config)
    state_counts = []
    for sample, subset in (
        ("all_sample", state_frame),
        ("in_sample", state_frame[pd.to_datetime(state_frame["signal_date"]) < pd.Timestamp(args.oos_start)]),
        ("out_of_sample", state_frame[pd.to_datetime(state_frame["signal_date"]) >= pd.Timestamp(args.oos_start)]),
    ):
        for state, group in subset.groupby("state", dropna=False):
            state_counts.append({"sample": sample, "state": state, "months": len(group)})
    state_counts_frame = pd.DataFrame(state_counts)
    detail_path = config.reports_dir / "strict_b_regime_exposure_detail.csv"
    report_path = config.reports_dir / "strict_b_regime_exposure_summary.md"
    detail.to_csv(detail_path, index=False)
    report_path.write_text(_exposure_report(detail, state_counts_frame), encoding="utf-8")
    print(f"wrote {detail_path} and {report_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-share high-dividend low-volatility backtest")
    parser.add_argument("--cache-dir", help="Override cache directory")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Fetch and cache AkShare source data")
    fetch.add_argument("--limit", type=int, default=50, help="Stocks for smoke run; use 0 only with --full")
    fetch.add_argument("--full", action="store_true", help="Allow an explicit full-market run")
    fetch.add_argument("--refresh", action="store_true")
    fetch.add_argument("--workers", type=int, default=1, help="Concurrent per-stock fetch workers (max 2)")
    fetch.add_argument("--stock-timeout", type=int, default=120, help="Hard timeout per stock in seconds")
    fetch.add_argument("--max-memory-mb", type=int, default=512)
    fetch.add_argument("--industry-map", help="Static code-to-industry CSV override")
    fetch.add_argument("--quality", action="store_true", help="Also fetch disclosed quality indicators")
    fetch.set_defaults(func=cmd_fetch)

    fetch_one = commands.add_parser("fetch-one", help=argparse.SUPPRESS)
    fetch_one.add_argument("--code", required=True)
    fetch_one.add_argument("--refresh", action="store_true")
    fetch_one.add_argument("--quality", action="store_true")
    fetch_one.set_defaults(func=cmd_fetch_one)

    build = commands.add_parser("build-snapshots", help="Create monthly PIT snapshots from cached sources")
    build.add_argument("--start", default="2024-01-01", help="Inclusive start date")
    build.add_argument("--end", default="2025-12-31", help="Inclusive end date")
    build.add_argument("--output", default="data/pit_snapshots.parquet")
    build.add_argument("--industry-map", help="Static code-to-industry CSV override")
    build.add_argument("--universe-dir", help="Monthly BaoStock universe directory")
    build.add_argument("--limit", type=int, default=50, help="Maximum stocks to load; use 0 only with --full")
    build.add_argument("--full", action="store_true", help="Allow an explicit full-universe run")
    build.add_argument("--batch-size", type=int, default=10, help="Stocks loaded per batch")
    build.add_argument("--max-memory-mb", type=int, default=512, help="Stop safely above this RSS limit")
    build.add_argument("--volatility-window", type=int, default=120)
    build.add_argument("--rebalance-position", choices=["first", "middle", "last"], default="first")
    build.set_defaults(func=cmd_build_snapshots)

    audit = commands.add_parser("audit-dividends", help="Audit reconstructed dividend yields")
    audit.add_argument("--events", required=True)
    audit.add_argument("--prices", required=True)
    audit.add_argument("--code", required=True)
    audit.add_argument("--as-of", required=True)
    audit.add_argument("--output", default="reports/dividend_audit.csv")
    audit.set_defaults(func=cmd_audit_dividends)

    audit_sample = commands.add_parser("audit-dividend-sample", help="Audit up to 50 cached dividend histories")
    audit_sample.add_argument("--as-of", default="2024-06-30")
    audit_sample.add_argument("--limit", type=int, default=50)
    audit_sample.add_argument("--output", default="reports/dividend_audit_sample.csv")
    audit_sample.add_argument("--max-memory-mb", type=int, default=512)
    audit_sample.set_defaults(func=cmd_audit_dividend_sample)

    coverage = commands.add_parser("coverage", help="Inspect source cache coverage and recommended target window")
    coverage.set_defaults(func=cmd_coverage)

    rank = commands.add_parser("rank-snapshot-parts", help="Cross-sectionally rank partitioned snapshot batches")
    rank.add_argument("--parts-dir", required=True)
    rank.add_argument("--output", default="data/selected_holdings.parquet")
    rank.add_argument("--max-memory-mb", type=int, default=512)
    rank.add_argument("--variant", default="quality_industry")
    rank.add_argument("--weighting", choices=["equal", "inverse_volatility"], default="inverse_volatility")
    rank.add_argument("--preset", choices=sorted(VARIANT_PRESETS), help="A–E ablation preset")
    rank.add_argument("--top-n", type=int, default=25)
    rank.add_argument("--volatility-window", type=int, default=120)
    rank.add_argument("--rebalance-position", choices=["first", "middle", "last"], default="first")
    rank.add_argument("--high-dividend-percentile", type=float, default=0.20)
    rank.add_argument("--dividend-signal", default="annual_dividend_yield")
    rank.add_argument("--exclude-industries", default="", help="Comma-separated industry exclusions")
    rank.add_argument("--max-industry-weight", type=float, default=0.20)
    rank.add_argument("--max-stock-weight", type=float, default=0.10)
    rank.set_defaults(func=cmd_rank_snapshot_parts)

    backtest = commands.add_parser("backtest", help="Run prebuilt PIT monthly snapshots")
    backtest.add_argument("--snapshots", required=True)
    backtest.add_argument("--prices", required=True)
    backtest.add_argument("--benchmark", help="Benchmark price parquet with date and adjusted_close")
    backtest.add_argument("--robustness", action="store_true", help="Run 20/25/30 holding-count sensitivity")
    backtest.set_defaults(func=cmd_backtest)

    cached_backtest = commands.add_parser(
        "backtest-cached-holdings", help="Backtest selected holdings using only per-stock cached prices"
    )
    cached_backtest.add_argument("--holdings", required=True)
    cached_backtest.set_defaults(func=cmd_backtest_cached_holdings)

    universe = commands.add_parser("build-universe", help="Build monthly BaoStock historical stock universes")
    universe.add_argument("--start", default="2019-01-01")
    universe.add_argument("--end", default=_rolling_data_end())
    universe.add_argument("--output", default="data/universes")
    universe.add_argument("--limit", type=int, default=2, help="Months for smoke run; use --full for all")
    universe.add_argument("--full", action="store_true", help="Build every monthly universe")
    universe.add_argument("--refresh", action="store_true")
    universe.add_argument("--pause-seconds", type=float, default=0.5)
    universe.add_argument("--max-memory-mb", type=int, default=512)
    universe.set_defaults(func=cmd_build_universe)

    status = commands.add_parser("fetch-baostock-status", help="Cache bounded historical ST and suspension status")
    status.add_argument("--codes", required=True, help="Parquet file containing a code column")
    status.add_argument("--start", default="2019-01-01")
    status.add_argument("--end", default=_rolling_data_end())
    status.add_argument("--limit", type=int, default=50)
    status.add_argument("--full", action="store_true")
    status.add_argument("--refresh", action="store_true")
    status.add_argument("--pause-seconds", type=float, default=0.5)
    status.add_argument("--max-memory-mb", type=int, default=512)
    status.set_defaults(func=cmd_fetch_baostock_status)

    historical = commands.add_parser(
        "fetch-historical-missing", help="Fill missing cached histories for historical-universe codes"
    )
    historical.add_argument("--universe-dir", required=True)
    historical.add_argument("--limit", type=int, default=50)
    historical.add_argument("--full", action="store_true")
    historical.add_argument("--refresh", action="store_true")
    historical.add_argument("--pause-seconds", type=float, default=0.5)
    historical.add_argument("--max-memory-mb", type=int, default=512)
    historical.add_argument("--source", choices=["baostock", "akshare"], default="baostock")
    historical.add_argument("--start", default="2018-01-01")
    historical.add_argument("--end", default=_rolling_data_end())
    historical.add_argument("--finance-start-year", type=int, default=2015)
    historical.add_argument("--finance-end-year", type=int, default=2026)
    historical.set_defaults(func=cmd_fetch_historical_missing)

    update = commands.add_parser(
        "update-monthly", help="Incrementally build one PIT STRICT_B monthly signal"
    )
    update.add_argument("--signal-month", help="YYYY-MM; defaults to the current calendar month")
    update.add_argument("--holdings", default="data/strict/holdings_STRICT_B.parquet")
    update.add_argument("--universe-dir", default="data/universes")
    update.add_argument("--batch-size", type=int, default=50)
    update.add_argument("--max-memory-mb", type=int, default=512)
    update.add_argument("--pause-seconds", type=float, default=0.5)
    update.add_argument("--refresh-universe", action="store_true")
    update.add_argument("--industry-map")
    update.add_argument("--preset", choices=["STRICT_B"], default="STRICT_B")
    update.add_argument("--top-n", type=int, default=25)
    update.add_argument("--volatility-window", type=int, default=120)
    update.add_argument("--rebalance-position", choices=["first"], default="first")
    update.add_argument("--high-dividend-percentile", type=float, default=0.20)
    update.add_argument("--max-industry-weight", type=float, default=0.20)
    update.add_argument("--max-stock-weight", type=float, default=0.10)
    update.set_defaults(func=cmd_update_monthly)

    refresh_verification = commands.add_parser(
        "refresh-strict-verification", help="Refresh STRICT_B final verification from cached periods"
    )
    refresh_verification.add_argument("--periods", default="reports/cached_periods.csv")
    refresh_verification.add_argument("--oos-start", default="2024-07-01")
    refresh_verification.set_defaults(func=cmd_refresh_strict_verification)

    compare = commands.add_parser("compare-variants", help="Sequentially backtest ranked variants with OOS split")
    compare.add_argument("--holdings", action="append", required=True, metavar="VARIANT=PATH")
    compare.add_argument("--oos-start", default="2024-07-01")
    compare.add_argument("--survivorship-audit")
    compare.add_argument("--benchmark", help="Daily benchmark parquet with date and close/adjusted_close")
    compare.set_defaults(func=cmd_compare_variants)

    market = commands.add_parser("prepare-regime-market", help="Cache regime indices and preselect ETF proxy")
    market.add_argument("--refresh", action="store_true")
    market.add_argument(
        "--etf-candidates",
        default="510300,159919,510500,159922,512100",
        help="Fixed comma-separated pre-2019 broad ETF candidates",
    )
    market.add_argument(
        "--required-end",
        default=_rolling_data_end(),
        help="Minimum ETF coverage date; pass a fixed value for historical reproduction",
    )
    market.set_defaults(func=cmd_prepare_regime_market)

    breadth = commands.add_parser("build-regime-breadth", help="Build bounded monthly T-1 MA120 breadth")
    breadth.add_argument("--holdings", default="data/strict/holdings_STRICT_B.parquet")
    breadth.add_argument("--universe-dir", default="data/universes")
    breadth.add_argument("--batch-size", type=int, default=50)
    breadth.add_argument("--max-memory-mb", type=int, default=512)
    breadth.set_defaults(func=cmd_build_regime_breadth)

    regime = commands.add_parser("regime-research", help="Run frozen STRICT_B regime overlays")
    regime.add_argument("--holdings", default="data/strict/holdings_STRICT_B.parquet")
    regime.add_argument("--oos-start", default="2024-07-01")
    regime.set_defaults(func=cmd_regime_research)

    exposure = commands.add_parser(
        "regime-exposure-research", help="Run fixed continuous STRICT_B/cash exposure schedules"
    )
    exposure.add_argument("--holdings", default="data/strict/holdings_STRICT_B.parquet")
    exposure.add_argument("--oos-start", default="2024-07-01")
    exposure.set_defaults(func=cmd_regime_exposure_research)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
