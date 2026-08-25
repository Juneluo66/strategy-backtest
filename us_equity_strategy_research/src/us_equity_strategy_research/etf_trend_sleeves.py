"""Price-only ETF trend rotation and SPY/QQQ protection sleeves."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml
import yfinance as yf

from .analytics import performance_report
from .artifacts import new_run_directory
from .backtest.costs import etf_flat_cost
from .config import load_config
from .data.prices import cash_symbol_on, load_adj_panels, sgov_inception
from .data.universe import month_end_index, next_trading_day
from .etf_adapter import verify_frozen_hash


ROTATION_RISK = [
    "SPY", "QQQ", "IWM",
    "XLK", "XLF", "XLI", "XLE", "XLV", "XLP", "XLY", "XLU",
    "VEA", "VWO",
    "IEF", "TLT", "GLD",
]
ALL_SYMBOLS = ROTATION_RISK + ["BIL", "SGOV", "VTI"]


def _safe(symbol: str) -> str:
    return symbol.replace("-", "_")


def fetch_missing_etfs(cache_dir: Path, start: str = "2005-01-01") -> dict:
    etf_dir = cache_dir / "etf"
    etf_dir.mkdir(parents=True, exist_ok=True)
    completed, failures = [], {}
    for symbol in ALL_SYMBOLS:
        path = etf_dir / f"{_safe(symbol)}.parquet"
        if path.exists():
            completed.append(symbol)
            continue
        try:
            frame = yf.download(symbol, start=start, auto_adjust=False, progress=False, threads=False)
            if frame.empty:
                raise ValueError("empty")
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
            frame.to_parquet(path)
            completed.append(symbol)
        except Exception as exc:  # noqa: BLE001
            failures[symbol] = str(exc)
    manifest = {
        "completed_symbols": completed,
        "failures": failures,
        "return_basis": "Yahoo_AdjClose_scaled_Open",
    }
    (cache_dir / "etf_trend_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _month_panel(closes: pd.DataFrame) -> pd.DataFrame:
    ends = month_end_index(closes.index)
    return closes.reindex(ends)


def momentum_12_1(month_closes: pd.DataFrame) -> pd.DataFrame:
    """Skip most recent month; use prior 11 months (t-12 -> t-1)."""
    return month_closes.shift(1) / month_closes.shift(12) - 1.0


def above_sma10(month_closes: pd.DataFrame) -> pd.DataFrame:
    sma = month_closes.rolling(10, min_periods=10).mean()
    return month_closes > sma


def _run_weight_schedule(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    target_on_signal: dict[pd.Timestamp, pd.Series],
    *,
    one_way_bps: float = 5.0,
) -> dict:
    common = opens.index.intersection(closes.index).sort_values()
    execute_map = {}
    for signal, _ in target_on_signal.items():
        nxt = next_trading_day(common, signal)
        if nxt is not None:
            execute_map[nxt] = signal

    weights = pd.Series(dtype=float)
    pending = None
    prev_close = None
    rows, trades, targets = [], [], []
    for date in common:
        gross = 0.0
        cost = 0.0
        if prev_close is not None and not weights.empty:
            overnight = (opens.loc[date] / prev_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())
        if date in execute_map and pending is not None:
            turnover = float(pending.sub(weights, fill_value=0.0).abs().sum())
            cost += etf_flat_cost(turnover, one_way_bps)
            trades.append({"date": date, "signal_date": execute_map[date], "turnover": turnover, "cost": cost})
            for symbol, w in pending.items():
                targets.append(
                    {"signal_date": execute_map[date], "execution_date": date, "symbol": symbol, "weight": float(w)}
                )
            weights = pending
            pending = None
        if not weights.empty:
            intraday = (closes.loc[date] / opens.loc[date] - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            gross += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())
        if date in target_on_signal:
            pending = target_on_signal[date]
        rows.append({"date": date, "gross_return": gross, "cost": cost, "net_return": gross - cost})
        prev_close = closes.loc[date]

    equity = pd.DataFrame(rows).set_index("date")
    if trades:
        first = pd.Timestamp(min(t["date"] for t in trades))
        equity = equity.loc[equity.index >= first]
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()
    equity["equity_gross"] = (1 + equity["gross_return"]).cumprod()
    return {
        "equity": equity,
        "trades": pd.DataFrame(trades),
        "targets": pd.DataFrame(targets),
        "return_basis": "Yahoo_AdjClose_scaled_Open",
    }


def build_rotation_targets(
    closes: pd.DataFrame,
    risk: list[str],
    *,
    top_k: int = 2,
    cash: str = "BIL",
) -> dict[pd.Timestamp, pd.Series]:
    me = _month_panel(closes[risk + [cash]])
    mom = momentum_12_1(me[risk])
    trend = above_sma10(me[risk])
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in me.index:
        if mom.loc[date].isna().all():
            continue
        eligible = []
        for symbol in risk:
            m = mom.at[date, symbol]
            ok = trend.at[date, symbol]
            if pd.notna(m) and bool(ok) and pd.notna(me.at[date, symbol]):
                eligible.append((symbol, float(m)))
        eligible.sort(key=lambda x: x[1], reverse=True)
        chosen = [s for s, _ in eligible[:top_k]]
        if not chosen:
            targets[date] = pd.Series({cash: 1.0})
        else:
            w = {s: 1.0 / len(chosen) for s in chosen}
            residual = 1.0 - sum(w.values())
            if residual > 1e-12:
                w[cash] = residual
            targets[date] = pd.Series(w, dtype=float)
    return targets


def build_spy_qqq_protect_targets(
    closes: pd.DataFrame,
    *,
    spy_w: float = 0.70,
    qqq_w: float = 0.30,
    cash: str = "BIL",
) -> dict[pd.Timestamp, pd.Series]:
    me = _month_panel(closes[["SPY", "QQQ", cash]])
    trend = above_sma10(me[["SPY", "QQQ"]])
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in me.index:
        if pd.isna(trend.at[date, "SPY"]) or pd.isna(me.at[date, "SPY"]):
            continue
        w = {}
        if bool(trend.at[date, "SPY"]):
            w["SPY"] = spy_w
        if bool(trend.at[date, "QQQ"]):
            w["QQQ"] = qqq_w
        cash_w = 1.0 - sum(w.values())
        if cash_w > 1e-12:
            w[cash] = cash_w
        targets[date] = pd.Series(w, dtype=float)
    return targets


def build_f3_targets(
    closes: pd.DataFrame,
    risk: list[str],
    *,
    rotation_w: float = 0.70,
    spy_w: float = 0.30,
    top_k: int = 2,
    cash: str = "BIL",
) -> dict[pd.Timestamp, pd.Series]:
    """70% ETF rotation + 30% SPY sleeve; only the SPY sleeve is SMA-gated to cash."""
    rot = build_rotation_targets(closes, risk, top_k=top_k, cash=cash)
    me = _month_panel(closes[["SPY", cash]])
    trend = above_sma10(me[["SPY"]])
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date, rot_wts in rot.items():
        if date not in trend.index or pd.isna(trend.at[date, "SPY"]):
            continue
        blended = (rot_wts * rotation_w).copy()
        if bool(trend.at[date, "SPY"]):
            blended["SPY"] = blended.get("SPY", 0.0) + spy_w
        else:
            blended[cash] = blended.get(cash, 0.0) + spy_w
        # renormalize tiny float drift
        blended = blended[blended > 0]
        blended = blended / blended.sum()
        targets[date] = blended
    return targets


def run_etf_trend_experiments(project_root: Optional[Path] = None) -> Path:
    config = load_config(project_root)
    sleeve_cfg = yaml.safe_load(
        (config.project_root / "configs" / "etf_trend_sleeves.yaml").read_text(encoding="utf-8")
    )
    manifest = fetch_missing_etfs(config.cache_dir, start=sleeve_cfg.get("data_start", "2005-01-01"))
    if manifest["failures"]:
        raise RuntimeError(f"ETF fetch failures: {manifest['failures']}")

    opens, closes, _ = load_adj_panels(config.cache_dir, ALL_SYMBOLS, subdir="etf")
    cash = sleeve_cfg["cash"]
    # Require cash history before any backtest day (H4).
    cash_start = closes[cash].dropna().index.min()
    opens = opens.loc[opens.index >= cash_start]
    closes = closes.loc[closes.index >= cash_start]
    risk = [s for s in ROTATION_RISK if s in closes.columns and closes[s].notna().any()]
    bps = float(sleeve_cfg["one_way_bps"])

    rotation_targets = build_rotation_targets(closes, risk, top_k=int(sleeve_cfg["top_k"]), cash=cash)
    protect_targets = build_spy_qqq_protect_targets(
        closes,
        spy_w=float(sleeve_cfg["spy_qqq_protect"]["spy_weight"]),
        qqq_w=float(sleeve_cfg["spy_qqq_protect"]["qqq_weight"]),
        cash=cash,
    )
    f3_targets = build_f3_targets(
        closes,
        risk,
        rotation_w=float(sleeve_cfg["f3"]["rotation_weight"]),
        spy_w=float(sleeve_cfg["f3"]["spy_weight"]),
        top_k=int(sleeve_cfg["top_k"]),
        cash=cash,
    )

    results = {
        "rotation_12_1": _run_weight_schedule(opens, closes, rotation_targets, one_way_bps=bps),
        "spy_qqq_protect": _run_weight_schedule(opens, closes, protect_targets, one_way_bps=bps),
        "f3_rot70_spy30_protect": _run_weight_schedule(opens, closes, f3_targets, one_way_bps=bps),
    }

    # Benchmarks
    vti_r = closes["VTI"].pct_change(fill_method=None).fillna(0.0)
    spy_r = closes["SPY"].pct_change(fill_method=None).fillna(0.0)

    # Frozen D+C + 80/20 if importable
    dc_r = None
    try:
        from dual_momentum_etf.backtest import run_variant
        from dual_momentum_etf.config import load_config as load_dm
        from dual_momentum_etf.data import load_ohlc

        dm = load_dm()
        o, c = load_ohlc(dm)
        dc_out = run_variant(o, c, dm, "attribution_DC")
        dc_r = dc_out["equity"]["net_return"]
    except Exception as exc:  # noqa: BLE001
        dc_r = None
        dc_err = str(exc)
    else:
        dc_err = None

    hash_check = verify_frozen_hash()
    run_dir = new_run_directory(config, "etf_trend_sleeves", {"experiment": "etf_trend_sleeves_v1"})

    series = {name: out["equity"]["net_return"] for name, out in results.items()}
    series["vti_bh"] = vti_r
    series["spy_bh"] = spy_r
    if dc_r is not None:
        series["dc"] = dc_r
        aligned = pd.concat([spy_r.rename("spy"), dc_r.rename("dc")], axis=1).dropna()
        series["frozen_80_20_spy_dc"] = 0.8 * aligned["spy"] + 0.2 * aligned["dc"]

    # Common interval across strategies + VTI + SPY (+ frozen if present)
    keys = ["rotation_12_1", "spy_qqq_protect", "f3_rot70_spy30_protect", "vti_bh", "spy_bh"]
    if "frozen_80_20_spy_dc" in series:
        keys.append("frozen_80_20_spy_dc")
    start = max(series[k].dropna().index.min() for k in keys)
    end = min(series[k].dropna().index.max() for k in keys)

    rows = []
    for name in keys + ([k for k in series if k not in keys]):
        s = series[name].loc[start:end].dropna()
        eq = pd.DataFrame({"gross_return": s, "net_return": s, "n_holdings": np.nan}, index=s.index)
        trades = results.get(name, {}).get("trades", pd.DataFrame()) if name in results else pd.DataFrame()
        metrics = performance_report(eq, trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(), closes["VTI"])
        rows.append({"name": name, **metrics})

    frame = pd.DataFrame(rows)
    frame.to_csv(run_dir / "comparison.csv", index=False)
    for name, out in results.items():
        out["equity"].to_csv(run_dir / f"equity_{name}.csv")
        out["targets"].to_csv(run_dir / f"targets_{name}.csv", index=False)
        out["trades"].to_csv(run_dir / f"trades_{name}.csv", index=False)

    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "common_start": str(start.date()),
                "common_end": str(end.date()),
                "cash": cash,
                "bil_start": str(closes["BIL"].dropna().index.min().date()),
                "sgov_inception": str(sgov_inception(closes).date()) if sgov_inception(closes) is not None else None,
                "hash_check": hash_check,
                "dc_adapter_error": dc_err,
                "risk_pool": risk,
                "one_way_bps": bps,
                "rules": {
                    "rotation": "12-1 mom + price>10m SMA; top2 EW; residual BIL; next open",
                    "spy_qqq_protect": "70/30 SPY/QQQ; each leg SMA-gated to BIL; next open",
                    "f3": "70% rotation + 30% SPY SMA-gated to BIL; next open",
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    # Markdown report
    def _fmt(row, col):
        val = row.get(col)
        if pd.isna(val):
            return "n/a"
        if "drawdown" in col or "cagr" in col or "sharpe" in col:
            return f"{val:.4f}"
        return str(val)

    lines = [
        "# ETF Trend Sleeve Experiments",
        "",
        f"- Common interval: `{start.date()}` → `{end.date()}`",
        f"- Cash: `{cash}` (not SGOV; avoids H4 inception hole)",
        f"- Cost: `{bps}` bp one-way",
        f"- return_basis: `Yahoo_AdjClose_scaled_Open`",
        f"- Frozen D+C hash check: `{hash_check}`",
        f"- Run dir: `{run_dir}`",
        "",
        "## Rules (frozen for this experiment)",
        "",
        "1. **rotation_12_1**: month-end 12-1 momentum; keep only ETFs above 10-month SMA; buy top-2 EW; residual → BIL; next session open.",
        "2. **spy_qqq_protect**: 70% SPY + 30% QQQ; each leg below 10m SMA → that weight to BIL; next open.",
        "3. **f3_rot70_spy30_protect**: 70% rotation sleeve + 30% SPY; only the SPY 30% is SMA-gated to BIL.",
        "",
        "## Net results (common interval vs VTI)",
        "",
        "| name | net_cagr | net_sharpe | net_max_drawdown | ann_turnover |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, row in frame.iterrows():
        lines.append(
            f"| {row['name']} | {_fmt(row,'net_cagr')} | {_fmt(row,'net_sharpe')} | "
            f"{_fmt(row,'net_max_drawdown')} | {_fmt(row,'annualized_turnover')} |"
        )

    # Explicit vs frozen 80/20
    lines.extend(["", "## Versus frozen 80% SPY + 20% D+C", ""])
    if "frozen_80_20_spy_dc" in frame["name"].values:
        base = frame.loc[frame["name"] == "frozen_80_20_spy_dc"].iloc[0]
        for name in ["rotation_12_1", "spy_qqq_protect", "f3_rot70_spy30_protect"]:
            row = frame.loc[frame["name"] == name].iloc[0]
            cagr_edge = float(row["net_cagr"] - base["net_cagr"])
            dd_edge = float(row["net_max_drawdown"] - base["net_max_drawdown"])  # less negative is better
            sharpe_edge = float(row["net_sharpe"] - base["net_sharpe"])
            lines.append(
                f"- **{name}**: CAGR edge `{cagr_edge:+.4f}`, Sharpe edge `{sharpe_edge:+.4f}`, "
                f"MaxDD edge `{dd_edge:+.4f}` (positive MaxDD edge = shallower drawdown)."
            )
        # Winner note without declaring paper PASS unless dominates carefully
        lines.extend(
            [
                "",
                "### Interpretation",
                "",
                "- These are price-only ETF rules; data gap risk is low vs equity multifactor/PEAD.",
                "- Do **not** retune the frozen D+C 80/20 on these results.",
                "- Prefer a challenger only if it improves risk-adjusted outcomes without relying on a single subperiod.",
                "",
            ]
        )
    else:
        lines.append("- Frozen 80/20 unavailable in this run (D+C adapter failed).")
        if dc_err:
            lines.append(f"- Adapter error: `{dc_err}`")

    report_path = config.reports_dir / "etf_trend_sleeve_comparison.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run_dir / "etf_trend_sleeve_comparison.md").write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
    return report_path
