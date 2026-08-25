"""Safe command line workflow for ETF rotation research."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

import pandas as pd

from etf_rotation.analysis import ablation_table, multiple_testing_report
from etf_rotation.artifacts import config_hash, new_run_directory
from etf_rotation.audit import data_audit, render_data_audit
from etf_rotation.backtest import event_backtest, variant_config, vector_backtest
from etf_rotation.compare import write_engine_gap, write_reproduction_comparison
from etf_rotation.config import (
    RotationConfig,
    frozen_config,
    sealed_parameter_check,
    strategy_definition,
)
from etf_rotation.data import (
    build_pit_universe,
    cached_prices,
    coverage_audit,
    fetch_many,
    universe_definition,
)
from etf_rotation.factors import (
    FactorAvailabilityError,
    FactorAudit,
    cross_sectional_scores,
    factor_panel,
)
from etf_rotation.non_ohlcv.fetch import fetch_non_ohlcv
from etf_rotation.non_ohlcv.loader import load_non_ohlcv_sources
from etf_rotation.non_ohlcv.tushare_source import TuShareTokenError
from etf_rotation.reporting import (
    cost_capacity_stress,
    cost_stress,
    environment_splits,
    oos_metrics,
    render_summary,
    rolling_oos_validation,
    save_result,
    serial_robustness,
)


def _rss_mb() -> float:
    try:
        return float(os.sysconf("SC_PAGE_SIZE") * int(Path("/proc/self/statm").read_text().split()[1]) / 1024**2)
    except (FileNotFoundError, ValueError, IndexError, OSError):
        return 0.0


def _safety(path: Path, max_memory_mb: int, **values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"peak_rss_mb": round(_rss_mb(), 1), "max_memory_mb": max_memory_mb,
                                **values}, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_rss(config: RotationConfig, max_memory_mb: int, command: str, **context: object) -> None:
    rss = _rss_mb()
    if rss > max_memory_mb:
        path = config.cache_dir / f"{command}_safety.json"
        _safety(path, max_memory_mb, stopped_for_memory=True, stopped_reason="rss_limit_exceeded", **context)
        raise RuntimeError(f"{command}: RSS {rss:.1f} MB exceeds {max_memory_mb} MB")


def _config(args: argparse.Namespace) -> RotationConfig:
    config = frozen_config()
    changes = {}
    for name in ("frequency", "position_size", "delta_rank", "min_hold_days"):
        value = getattr(args, name, None)
        if value is not None:
            changes[name] = value
    if getattr(args, "cache_dir", None):
        changes["cache_dir"] = Path(args.cache_dir)
    if getattr(args, "reports_dir", None):
        changes["reports_dir"] = Path(args.reports_dir)
    return replace(config, **changes)


def _load_scored(
    config: RotationConfig,
    variant: str,
    *,
    run_mode: str = "research",
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], RotationConfig, FactorAudit]:
    config = variant_config(config, variant)
    prices = cached_prices(config)
    if not prices:
        raise RuntimeError("no cached prices; run etf-rotation fetch first")
    definition = universe_definition(config)
    sources = load_non_ohlcv_sources(config)
    panel = factor_panel(prices, config, sources=sources)
    pit = build_pit_universe(prices, definition, config.lookback)
    scores, audit = _scores_for_config(panel, pit, config, run_mode=run_mode, sources=sources)
    return scores, prices, config, audit


def _scores_for_config(
    panel: pd.DataFrame,
    pit: pd.DataFrame,
    config: RotationConfig,
    *,
    run_mode: str = "research",
    sources=None,
) -> tuple[pd.DataFrame, FactorAudit]:
    factors, signs, icirs = strategy_definition(config, config.factor_set)
    # baseline mode + non-OHLCV factor_set is rejected inside cross_sectional_scores
    mode = "baseline" if (run_mode == "baseline" or config.factor_set == "momentum") and run_mode != "strict" else run_mode
    if run_mode == "baseline":
        mode = "baseline"
    elif config.factor_set == "momentum" and run_mode == "research":
        mode = "baseline"
    scores, audit = cross_sectional_scores(
        panel, factors, signs, icirs, run_mode=mode, sources=sources or {}
    )
    scores = scores.merge(pit[["date", "code", "eligible"]], on=["date", "code"], how="left")
    scores = scores.loc[scores.eligible.fillna(False)].drop(columns="eligible")
    return scores, audit


def _write_factor_audit(directory: Path, audit: FactorAudit, stem: str) -> None:
    (directory / f"{stem}_factor_audit.json").write_text(
        json.dumps(audit.to_jsonable(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not audit.daily_coverage.empty:
        audit.daily_coverage.to_csv(directory / f"{stem}_daily_factor_coverage.csv", index=False)
    pd.Series(audit.etf_participation_ratio, name="participation_ratio").to_csv(
        directory / f"{stem}_etf_participation.csv"
    )
    mismatch = list(audit.declared_factors) != list(audit.actual_factors)
    print(
        f"factor_audit[{stem}] mode={audit.run_mode} status={audit.reproduction_status} "
        f"declared={audit.declared_factors} actual={audit.actual_factors} "
        f"tiers={audit.factor_tiers} implicit_margin_screen={audit.implicit_margin_screen} "
        f"mismatch={mismatch}"
    )
    if mismatch:
        print(f"WARNING: declared factors != actual factors for {stem}")
    for note in audit.notes:
        print(f"factor_audit_note[{stem}]: {note}")


def _variant_definitions() -> pd.DataFrame:
    """Predeclared research variants; none are selected from OOS performance."""
    rows = [
        ("M1", "Price momentum baseline", "MOM_20D; Top-2; no hysteresis or regime gate",
         "Not v8; predeclared ablation baseline."),
        ("H1", "M1 plus hysteresis", "MOM_20D; delta-rank 0.10; min hold 9; max replace 1",
         "Predeclared execution ablation."),
        ("R1", "H1 plus regime gate", "H1 plus 510300 volatility exposure gate",
         "Predeclared risk-control ablation."),
        ("v8_reference", "Frozen v8 reference", "composite_1 factor declaration and all frozen execution settings",
         "Partial unless non-OHLCV files are supplied; never labelled full reproduction."),
        ("C4", "Frozen core_4f reference", "core_4f declaration and all frozen execution settings",
         "Partial unless margin/share fields are supplied."),
    ]
    return pd.DataFrame(rows, columns=["variant", "baseline", "definition", "v8_difference_and_status"])


def _write_frozen_parameters(config: RotationConfig, directory: Path) -> None:
    data = pd.DataFrame([
        ("ETF pool", "49 symbols; 41 A-share / 8 QDII; A_SHARE_ONLY trading"),
        ("Factors", "Read from configs/frozen_v8.yaml; ICIR absolute weights normalized in score"),
        ("Frequency / positions", f"{config.frequency} trading days / {config.position_size}"),
        ("Hysteresis", f"delta_rank={config.delta_rank}; min_hold_days={config.min_hold_days}; max_replace={config.max_replacements}"),
        ("Regime gate", f"{config.regime_proxy}, {config.regime_window}D, {config.regime_thresholds} -> {config.regime_exposures}"),
        ("Costs", f"A-share={config.commission_a_share}; QDII={config.commission_qdii}"),
        ("Timing", "T close signal; next available session open execution"),
        ("Periods", f"IS through {config.training_end}; original OOS from {config.oos_start}; fresh OOS after 2026-02-10"),
        ("Config hash", config_hash(config)),
    ], columns=["parameter", "value"])
    data.to_csv(directory / "frozen_parameters.csv", index=False)
    (directory / "frozen_parameters.md").write_text(
        "# Frozen parameters\n\n" + data.to_markdown(index=False) + "\n", encoding="utf-8"
    )
    definitions = _variant_definitions()
    definitions.to_csv(directory / "variant_definitions.csv", index=False)
    (directory / "variant_definitions.md").write_text(
        "# Variant definitions\n\n" + definitions.to_markdown(index=False) +
        "\n\nAll variants were defined before execution and are not selected by sample-outcome.\n",
        encoding="utf-8",
    )


def cmd_fetch(args: argparse.Namespace) -> None:
    config = _config(args)
    if args.full is False and args.limit <= 0:
        raise RuntimeError("fetch: specify --limit for smoke work or --full for the 49-ETF universe")
    run_id, directory, digest = new_run_directory(config, "fetch")
    failures = fetch_many(
        config, limit=args.limit, full=args.full, refresh=args.refresh, sleep_seconds=args.sleep_seconds,
        rss_check=lambda **context: _check_rss(config, args.max_memory_mb, "fetch", **context),
        request_timeout=args.request_timeout,
        retries=args.retries,
    )
    failures.to_csv(directory / "fetch_failures.csv", index=False)
    _safety(directory / "fetch_safety.json", args.max_memory_mb, stopped_for_memory=False,
            requested="full" if args.full else args.limit, failures=len(failures))
    print(f"run_id={run_id} config_hash={digest} fetch complete; failures={len(failures)} cache={config.cache_dir}")


def cmd_fetch_non_ohlcv(args: argparse.Namespace) -> None:
    config = _config(args)
    if not args.full:
        raise SystemExit("fetch-non-ohlcv: refuse to run without --full")
    run_id, directory, digest = new_run_directory(config, "fetch_non_ohlcv")
    try:
        result = fetch_non_ohlcv(
            config,
            full=True,
            sleep_seconds=args.sleep_seconds,
            token=os.environ.get("TUSHARE_TOKEN"),
            source=args.source,
        )
    except TuShareTokenError as exc:
        (directory / "fetch_non_ohlcv_error.txt").write_text(str(exc) + "\n", encoding="utf-8")
        raise SystemExit(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - persist failure into run dir
        (directory / "fetch_non_ohlcv_error.txt").write_text(str(exc) + "\n", encoding="utf-8")
        raise
    meta = {
        "run_id": run_id,
        "config_hash": digest,
        "source": str(result.get("source")),
        "source_version": str(result["source_version"]),
        "status": str(result["status"]),
        "promoted": bool(result["promoted"]),
        "raw_dir": str(result["raw_dir"]),
        "staging_dir": str(result["staging_dir"]),
        "validation_path": str(result["validation_path"]),
    }
    (directory / "fetch_non_ohlcv_result.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    validation = Path(str(result["validation_path"]))
    if validation.exists():
        (directory / "non_ohlcv_validation.md").write_text(
            validation.read_text(encoding="utf-8"), encoding="utf-8"
        )
    errors = result.get("errors")
    if isinstance(errors, pd.DataFrame) and not errors.empty:
        errors.to_csv(directory / "download_errors.csv", index=False)
    print(
        f"run_id={run_id} config_hash={digest} source={result.get('source')} "
        f"status={result['status']} promoted={result['promoted']} "
        f"validation={result['validation_path']}"
    )


def cmd_audit(args: argparse.Namespace) -> None:
    config = _config(args)
    run_id, directory, digest = new_run_directory(config, "audit")
    summary, detail = coverage_audit(config)
    audited, coverage, partial_factors = data_audit(config)
    pit = build_pit_universe(cached_prices(config), universe_definition(config), config.lookback)
    detail.to_csv(directory / "coverage_detail.csv", index=False)
    summary.to_csv(directory / "coverage_summary.csv", index=False)
    audited.to_csv(directory / "data_audit.csv", index=False)
    coverage.to_csv(directory / "data_coverage.csv", index=False)
    partial_factors.to_csv(directory / "partial_factors.csv", index=False)
    render_data_audit(audited, partial_factors, directory / "data_audit.md")
    research = Path(__file__).resolve().parents[2] / "reports" / "non_ohlcv_source_research.md"
    if research.exists():
        (directory / "non_ohlcv_source_research.md").write_text(
            research.read_text(encoding="utf-8"), encoding="utf-8"
        )
    pit.to_parquet(config.cache_dir / "pit_universe.parquet", index=False)
    (directory / "coverage_audit.md").write_text(
        "# ETF universe coverage audit\n\n" + summary.to_markdown(index=False) +
        "\n\nEligibility starts only after each cached ETF has the configured lookback bars; "
        "this is the conservative point-in-time listing proxy.\n", encoding="utf-8")
    blocked = int(partial_factors.status.ne("available").sum())
    print(
        f"run_id={run_id} config_hash={digest} wrote data audit to {directory}; "
        f"partial_non_ohlcv={blocked}/4 status="
        f"{'BLOCKED_BY_DATA' if blocked else 'non_ohlcv_ready'}"
    )


def cmd_run(args: argparse.Namespace) -> None:
    base = _config(args)
    sealed_parameter_check(base, allow_unfrozen=args.allow_unfrozen)
    run_id, directory, digest = new_run_directory(base, "run")
    _write_frozen_parameters(base, directory)
    variants = [item.strip() for item in args.variants.split(",")]
    results = {}
    prices = cached_prices(base)
    if not prices:
        raise RuntimeError("no cached prices; run etf-rotation fetch first")
    sources = load_non_ohlcv_sources(base)
    pit = build_pit_universe(prices, universe_definition(base), base.lookback)
    panel = factor_panel(prices, base, sources=sources)
    run_mode = getattr(args, "mode", "research")
    for variant in variants:
        config = variant_config(base, variant)
        try:
            scores, audit = _scores_for_config(
                panel, pit, config, run_mode=run_mode, sources=sources
            )
        except FactorAvailabilityError as exc:
            (directory / f"{variant}_factor_error.txt").write_text(str(exc) + "\n", encoding="utf-8")
            raise SystemExit(f"{variant}: {exc}") from exc
        _write_factor_audit(directory, audit, variant)
        vec, evt = vector_backtest(scores, prices, config), event_backtest(scores, prices, config)
        results[f"{variant}_VEC"], results[f"{variant}_EVT"] = vec, evt
        scores.to_csv(directory / f"{variant}_factor_scores_and_ranks.csv", index=False)
        save_result(vec, directory, f"{variant}_vec")
        save_result(evt, directory, f"{variant}_evt")
        oos_metrics(evt, config).to_csv(directory / f"{variant}_evt_is_oos.csv", index=False)
        environment_splits(evt).to_csv(
            directory / f"{variant}_evt_environment.csv", index=False
        )
        rolling_oos_validation(evt).to_csv(
            directory / f"{variant}_evt_rolling_oos.csv", index=False
        )
        _check_rss(config, args.max_memory_mb, "run", variant=variant)
    table = render_summary(results, directory / "summary.md")
    table.to_csv(directory / "variant_summary.csv", index=False)
    print(f"run_id={run_id} config_hash={digest} completed {len(variants)} variant(s); summary={directory / 'summary.md'}")


def cmd_robustness(args: argparse.Namespace) -> None:
    config = _config(args)
    sealed_parameter_check(config, allow_unfrozen=args.allow_unfrozen)
    scores, prices, config, audit = _load_scored(config, args.variant, run_mode=getattr(args, "mode", "research"))
    result = serial_robustness(scores, prices, config)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(config.reports_dir / "robustness.csv", index=False)
    _write_factor_audit(config.reports_dir, audit, args.variant)
    cost_stress(scores, prices, config).to_csv(config.reports_dir / "cost_stress.csv", index=False)
    print(config.reports_dir / "robustness.csv")


def cmd_compare_engines(args: argparse.Namespace) -> None:
    base = _config(args)
    sealed_parameter_check(base, allow_unfrozen=args.allow_unfrozen)
    run_id, directory, digest = new_run_directory(base, "compare_engines")
    scores, prices, config, audit = _load_scored(
        base, args.variant, run_mode=getattr(args, "mode", "research")
    )
    _write_factor_audit(directory, audit, args.variant)
    vec, evt = vector_backtest(scores, prices, config), event_backtest(scores, prices, config)
    save_result(vec, directory, f"{args.variant}_vec")
    save_result(evt, directory, f"{args.variant}_evt")
    write_engine_gap(vec, evt, directory)
    write_reproduction_comparison(vec, evt, config, directory)
    print(f"run_id={run_id} config_hash={digest} comparison={directory}")


def cmd_ablation(args: argparse.Namespace) -> None:
    base = _config(args)
    sealed_parameter_check(base, allow_unfrozen=args.allow_unfrozen)
    run_id, directory, digest = new_run_directory(base, "ablation")
    mode = getattr(args, "mode", "research")
    momentum, prices, _, audit_m = _load_scored(base, "M1", run_mode=mode)
    composite, _, _, audit_c = _load_scored(base, "v8_reference", run_mode=mode)
    _write_factor_audit(directory, audit_m, "M1")
    _write_factor_audit(directory, audit_c, "v8_reference")
    table = ablation_table({"momentum": momentum, "composite_1": composite}, prices, base)
    table.to_csv(directory / "ablation.csv", index=False)
    (directory / "ablation.md").write_text(
        "# Frozen ablation\n\n" + table.to_markdown(index=False) +
        "\n\nThese are predeclared module removals, not an optimization search. "
        "C1-derived rows remain partial whenever non-OHLCV fields are unavailable.\n",
        encoding="utf-8",
    )
    print(f"run_id={run_id} config_hash={digest} ablation={directory}")


def cmd_multiple_testing(args: argparse.Namespace) -> None:
    config = _config(args)
    run_id, directory, digest = new_run_directory(config, "multiple_testing")
    table, markdown = multiple_testing_report()
    table.to_csv(directory / "candidate_distribution.csv", index=False)
    (directory / "multiple_testing.md").write_text(markdown + "\n", encoding="utf-8")
    print(f"run_id={run_id} config_hash={digest} multiple_testing={directory}")


def cmd_fresh_oos(args: argparse.Namespace) -> None:
    base = _config(args)
    sealed_parameter_check(base, allow_unfrozen=args.allow_unfrozen)
    run_id, directory, digest = new_run_directory(base, "fresh_oos")
    scores, prices, config, audit = _load_scored(
        base, args.variant, run_mode=getattr(args, "mode", "research")
    )
    _write_factor_audit(directory, audit, args.variant)
    evt = event_backtest(scores, prices, config)
    cutoff = pd.Timestamp("2026-02-10")
    equity = evt["equity"].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    fresh = equity.loc[equity.date > cutoff]
    fresh.to_csv(directory / "fresh_oos_daily.csv", index=False)
    trades = evt["trades"].copy()
    if not trades.empty:
        trades["date"] = pd.to_datetime(trades["date"])
        trades = trades.loc[trades.date > cutoff]
    trades.to_csv(directory / "fresh_oos_trades.csv", index=False)
    from etf_rotation.backtest import metrics
    report = pd.DataFrame([{"cutoff": cutoff, "observations": len(fresh), **metrics(fresh["return"])}])
    report.to_csv(directory / "fresh_oos_summary.csv", index=False)
    (directory / "fresh_oos.md").write_text(
        "# Untouched fresh OOS\n\n" + report.to_markdown(index=False) +
        "\n\nParameters, factors, and thresholds are frozen at the v8 reference. "
        "If no post-cutoff vendor data exists, results are unavailable rather than zero.\n",
        encoding="utf-8",
    )
    print(f"run_id={run_id} config_hash={digest} fresh_oos={directory}")


def cmd_cost_capacity(args: argparse.Namespace) -> None:
    base = _config(args)
    sealed_parameter_check(base, allow_unfrozen=args.allow_unfrozen)
    run_id, directory, digest = new_run_directory(base, "cost_capacity")
    scores, prices, config, audit = _load_scored(
        base, args.variant, run_mode=getattr(args, "mode", "research")
    )
    _write_factor_audit(directory, audit, args.variant)
    table = cost_capacity_stress(scores, prices, config)
    table.to_csv(directory / "cost_capacity.csv", index=False)
    (directory / "cost_capacity.md").write_text(
        "# Cost and capacity pressure test\n\n" + table.to_markdown(index=False) +
        "\n\nVWAP and first-5-minute VWAP are unavailable because no minute-level source is cached. "
        "The tested rule is next-session open with 100-share lots, cash constraints, and 20-day ADV caps.\n",
        encoding="utf-8",
    )
    print(f"run_id={run_id} config_hash={digest} cost_capacity={directory}")



def cmd_factor_wiring_compare(args: argparse.Namespace) -> None:
    """Compare OHLCV baseline vs share/C1/C4 research-partial factor sets."""
    from etf_rotation.backtest import metrics

    base = _config(args)
    sealed_parameter_check(base, allow_unfrozen=True)
    run_id, directory, digest = new_run_directory(base, "factor_wiring_compare")
    prices = cached_prices(base)
    if not prices:
        raise RuntimeError("no cached prices")
    sources = load_non_ohlcv_sources(base)
    panel = factor_panel(prices, base, sources=sources)
    pit = build_pit_universe(prices, universe_definition(base), base.lookback)
    experiments = [
        ("ohlcv_baseline", "momentum", ["MOM_20D"], [1.0], [1.0], "baseline"),
        (
            "share_chg_5d_only",
            "custom",
            ["MOM_20D", "SHARE_CHG_5D"],
            [1.0, -1.0],
            [1.0, 2.306],
            "research",
        ),
        (
            "both_share_factors",
            "custom",
            ["MOM_20D", "SHARE_CHG_5D", "SHARE_CHG_20D"],
            [1.0, -1.0, -1.0],
            [1.0, 2.306, 1.807],
            "research",
        ),
        ("C1_research_partial", "composite_1", None, None, None, "research"),
        ("C4_research_partial", "core_4f", None, None, None, "research"),
    ]
    rows = []
    for name, factor_set, factors, signs, icirs, mode in experiments:
        if factor_set in {"composite_1", "core_4f"}:
            factors, signs, icirs = strategy_definition(base, factor_set)
            config = variant_config(base, "C1" if factor_set == "composite_1" else "C4")
        else:
            config = variant_config(base, "R1")
        try:
            scores, audit = cross_sectional_scores(
                panel, factors, signs, icirs, run_mode=mode, sources=sources
            )
        except FactorAvailabilityError as exc:
            rows.append({
                "experiment": name,
                "error": str(exc),
                "reproduction_status": "FAILED",
                "declared_factors": "|".join(factors or []),
                "actual_factors": "",
            })
            (directory / f"{name}_error.txt").write_text(str(exc) + "\n", encoding="utf-8")
            continue
        scores = scores.merge(pit[["date", "code", "eligible"]], on=["date", "code"], how="left")
        scores = scores.loc[scores.eligible.fillna(False)].drop(columns="eligible")
        _write_factor_audit(directory, audit, name)
        vec = vector_backtest(scores, prices, config)
        equity = vec["equity"].copy()
        equity["date"] = pd.to_datetime(equity["date"])
        yearly = (
            equity.set_index("date")["return"]
            .resample("YE")
            .apply(lambda s: float((1 + s).prod() - 1) if len(s) else float("nan"))
        )
        m = metrics(equity["return"])
        row = {
            "experiment": name,
            "reproduction_status": audit.reproduction_status,
            "run_mode": audit.run_mode,
            "declared_factors": "|".join(audit.declared_factors),
            "actual_factors": "|".join(audit.actual_factors),
            "factor_tiers": json.dumps(audit.factor_tiers, ensure_ascii=False),
            "implicit_margin_screen": audit.implicit_margin_screen,
            "mean_complete_score_ratio": (
                float(audit.daily_coverage["complete_score_ratio"].mean())
                if not audit.daily_coverage.empty else None
            ),
            "annual_return": m["annual_return"],
            "sharpe": m["sharpe"],
            "max_drawdown": m["max_drawdown"],
            "turnover": float(equity["turnover"].sum()) if "turnover" in equity else None,
            "total_return": m["total_return"],
        }
        for stamp, value in yearly.items():
            row[f"year_{pd.Timestamp(stamp).year}"] = value
        rows.append(row)
        save_result(vec, directory, name)
        print(
            f"{name}: status={audit.reproduction_status} factors={audit.actual_factors} "
            f"ann={m['annual_return']:.4f} sharpe={m['sharpe']:.4f} mdd={m['max_drawdown']:.4f}"
        )
    table = pd.DataFrame(rows)
    table.to_csv(directory / "factor_wiring_compare.csv", index=False)
    disclaimer = (
        "\n\n**These research-partial / baseline runs are not a full v8 reproduction.** "
        "Staging non-OHLCV factors and free-data PIT proxies mean C1/C4 rows must not be "
        "described as sealed production replication.\n"
    )
    (directory / "factor_wiring_compare.md").write_text(
        "# Factor wiring comparison\n\n" + table.to_markdown(index=False) + disclaimer,
        encoding="utf-8",
    )
    print(f"run_id={run_id} config_hash={digest} compare={directory}")


def cmd_reproduce(args: argparse.Namespace) -> None:
    """Run the fixed workflow without changing any frozen parameters."""
    base = _config(args)
    master_id, directory, digest = new_run_directory(base, "reproduce")
    common = {"cache_dir": args.cache_dir, "reports_dir": args.reports_dir, "max_memory_mb": args.max_memory_mb}
    cmd_fetch(argparse.Namespace(
        **common, full=True, limit=0, refresh=False, sleep_seconds=args.sleep_seconds,
        request_timeout=args.request_timeout, retries=args.retries,
    ))
    cmd_audit(argparse.Namespace(**common))
    cmd_run(argparse.Namespace(
        **common, variants="M1,H1,R1,v8_reference", frequency=None, position_size=None,
        delta_rank=None, min_hold_days=None, allow_unfrozen=False, mode="research",
    ))
    cmd_compare_engines(argparse.Namespace(**common, variant="v8_reference", allow_unfrozen=False))
    cmd_ablation(argparse.Namespace(**common, allow_unfrozen=False))
    cmd_multiple_testing(argparse.Namespace(**common))
    cmd_fresh_oos(argparse.Namespace(**common, variant="v8_reference", allow_unfrozen=False))
    cmd_cost_capacity(argparse.Namespace(**common, variant="v8_reference", allow_unfrozen=False))
    _, _, partial = data_audit(base)
    ready = partial.status.isin(["production", "available"]).all()
    status = "PARTIAL_REPRODUCTION" if ready else "BLOCKED_BY_DATA"
    report = [
        "# Final reproduction report",
        "",
        f"Status: **{status}**",
        "",
        f"Master run: `{master_id}`",
        f"Config hash: `{digest}`",
        "",
        (
            "This status is conservative: incomplete non-OHLCV data blocks full v8 reproduction. "
            "No conclusion about paper trading is made."
        ),
    ]
    (directory / "final_reproduction_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"master_run_id={master_id} config_hash={digest} final_report={directory}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="etf-rotation")
    parser.add_argument("--cache-dir")
    parser.add_argument("--reports-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="serially cache ETF OHLCV")
    fetch.add_argument("--limit", type=int, default=8)
    fetch.add_argument("--full", action="store_true")
    fetch.add_argument("--refresh", action="store_true")
    fetch.add_argument("--sleep-seconds", type=float, default=0.5)
    fetch.add_argument("--request-timeout", type=int, default=60)
    fetch.add_argument("--retries", type=int, default=4)
    fetch.add_argument("--max-memory-mb", type=int, default=512)
    fetch.set_defaults(func=cmd_fetch)
    fetch_non = sub.add_parser(
        "fetch-non-ohlcv",
        help="download margin/share PIT fields (free Eastmoney/SSE/SZSE or TuShare)",
    )
    fetch_non.add_argument("--full", action="store_true", required=True)
    fetch_non.add_argument(
        "--source",
        choices=["auto", "free", "tushare"],
        default="auto",
        help="auto uses free sources when TUSHARE_TOKEN is unset",
    )
    fetch_non.add_argument("--sleep-seconds", type=float, default=0.25)
    fetch_non.add_argument("--max-memory-mb", type=int, default=512)
    fetch_non.set_defaults(func=cmd_fetch_non_ohlcv)
    audit = sub.add_parser("audit", help="build PIT eligibility and coverage audit")
    audit.set_defaults(func=cmd_audit)
    run = sub.add_parser("run", help="run serial VEC and event backtests")
    run.add_argument("--variants", default="M1,H1,R1")
    run.add_argument("--frequency", type=int)
    run.add_argument("--position-size", type=int)
    run.add_argument("--delta-rank", type=float)
    run.add_argument("--min-hold-days", type=int)
    run.add_argument("--allow-unfrozen", action="store_true")
    run.add_argument("--max-memory-mb", type=int, default=512)
    run.add_argument("--mode", choices=["strict", "research", "baseline"], default="research")
    run.set_defaults(func=cmd_run)
    robust = sub.add_parser("robustness", help="serial OAT vector robustness")
    robust.add_argument("--variant", default="R1")
    robust.add_argument("--allow-unfrozen", action="store_true")
    robust.add_argument("--mode", choices=["strict", "research", "baseline"], default="research")
    robust.set_defaults(func=cmd_robustness)
    compare = sub.add_parser("compare-engines", help="audit daily VEC versus EVT divergence")
    compare.add_argument("--variant", default="v8_reference")
    compare.add_argument("--allow-unfrozen", action="store_true")
    compare.add_argument("--mode", choices=["strict", "research", "baseline"], default="research")
    compare.set_defaults(func=cmd_compare_engines)
    ablation = sub.add_parser("ablation", help="run fixed module-removal ablations")
    ablation.add_argument("--allow-unfrozen", action="store_true")
    ablation.add_argument("--mode", choices=["strict", "research", "baseline"], default="research")
    ablation.set_defaults(func=cmd_ablation)
    multiple = sub.add_parser("multiple-testing", help="report candidate-search availability honestly")
    multiple.set_defaults(func=cmd_multiple_testing)
    fresh = sub.add_parser("fresh-oos", help="report post-2026-02-10 untouched OOS")
    fresh.add_argument("--variant", default="v8_reference")
    fresh.add_argument("--allow-unfrozen", action="store_true")
    fresh.add_argument("--mode", choices=["strict", "research", "baseline"], default="research")
    fresh.set_defaults(func=cmd_fresh_oos)
    capacity = sub.add_parser("cost-capacity", help="run fixed cost and ADV capacity stress")
    capacity.add_argument("--variant", default="v8_reference")
    capacity.add_argument("--allow-unfrozen", action="store_true")
    capacity.add_argument("--mode", choices=["strict", "research", "baseline"], default="research")
    capacity.set_defaults(func=cmd_cost_capacity)
    wiring = sub.add_parser(
        "factor-wiring-compare",
        help="compare baseline vs share/C1/C4 research-partial wiring",
    )
    wiring.add_argument("--allow-unfrozen", action="store_true", default=True)
    wiring.add_argument("--max-memory-mb", type=int, default=512)
    wiring.set_defaults(func=cmd_factor_wiring_compare)
    reproduce = sub.add_parser("reproduce", help="run the immutable full reproduction workflow")
    reproduce.add_argument("--full", action="store_true", required=True)
    reproduce.add_argument("--sleep-seconds", type=float, default=0.7)
    reproduce.add_argument("--request-timeout", type=int, default=60)
    reproduce.add_argument("--retries", type=int, default=4)
    reproduce.add_argument("--max-memory-mb", type=int, default=512)
    reproduce.set_defaults(func=cmd_reproduce)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
