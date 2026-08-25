"""PAPER_V1 forward paper trading engine.

Immutable rules:
- Signal at daily close; fill at next open only
- Append-only signal log (never rewrite history)
- Exposure via underlying equity beta (50% 3x ETF + 50% BSV)
- Parameter/tree/universe changes forbidden for PAPER_V1
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml

from exposure import target_weight_for_beta
from indicators import build_indicator_panels, indicators_ready
from original_strategy import state_from_row
from robust_core import make_selector


ROOT_DEFAULT = Path(__file__).resolve().parents[1]


def load_paper_config(project_root: Optional[Path] = None) -> dict[str, Any]:
    root = Path(project_root or ROOT_DEFAULT)
    path = root / "configs" / "paper_v1.yaml"
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if cfg.get("strategy_version") != "PAPER_V1":
        raise ValueError("expected strategy_version PAPER_V1")
    if cfg.get("allow_parameter_changes") or cfg.get("allow_tree_changes") or cfg.get("allow_universe_changes"):
        raise ValueError("PAPER_V1 must disallow parameter/tree/universe changes")
    return cfg


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def compute_paper_hashes(project_root: Optional[Path] = None) -> dict[str, str]:
    root = Path(project_root or ROOT_DEFAULT)
    cfg_path = root / "configs" / "paper_v1.yaml"
    logic_files = [
        root / "src" / "robust_core.py",
        root / "src" / "original_strategy.py",
        root / "src" / "exposure.py",
        root / "src" / "paper_trading.py",
        root / "src" / "indicators.py",
    ]
    logic_blob = b"".join(p.read_bytes() for p in logic_files if p.exists())
    cfg = load_paper_config(root)
    mapping = {
        "asset_underlying_beta": cfg.get("asset_underlying_beta"),
        "exposure": cfg.get("exposure"),
        "universe": cfg.get("universe"),
        "ablations": cfg.get("ablations"),
        "thresholds": cfg.get("thresholds"),
        "parameters": cfg.get("parameters"),
    }
    return {
        "paper_config_sha256": _sha256_file(cfg_path),
        "strategy_logic_sha256": _sha256_bytes(logic_blob),
        "asset_mapping_sha256": _sha256_text(json.dumps(mapping, sort_keys=True, default=str)),
        "composite_sha256": _sha256_text(
            _sha256_file(cfg_path)
            + _sha256_bytes(logic_blob)
            + _sha256_text(json.dumps(mapping, sort_keys=True, default=str))
        ),
    }


def paper_selector(cfg: dict):
    abl = cfg.get("ablations") or {}
    return make_selector(
        drop_spy_rsi=bool(abl.get("drop_spy_rsi", True)),
        drop_sqqq_rsi=bool(abl.get("drop_sqqq_rsi", False)),
        drop_uvxy_rsi=bool(abl.get("drop_uvxy_rsi", False)),
        drop_qqq_sma=bool(abl.get("drop_qqq_sma", False)),
        drop_tqqq_sma=bool(abl.get("drop_tqqq_sma", False)),
        drop_qqq_rsi=bool(abl.get("drop_qqq_rsi", False)),
        prune_branches=list(abl.get("prune_branches") or []),
    )


SIGNAL_COLUMNS = [
    "date",
    "SPY",
    "QQQ",
    "TQQQ",
    "rsi_spy",
    "rsi_qqq",
    "rsi_tqqq",
    "rsi_sqqq",
    "rsi_uvxy",
    "rsi_tecs",
    "rsi_bsv",
    "spy_sma_200",
    "qqq_sma_20",
    "tqqq_sma_20",
    "regime",
    "branch_id",
    "branch_path",
    "raw_target",
    "paper_target",
    "weights_json",
    "implied_underlying_beta",
    "exposure_target_beta",
    "three_x_etf_weight",
    "uvxy_overlay",
    "previous_raw_target",
    "target_changed",
    "version",
]


def append_signal_row(log_path: Path, row: dict[str, Any]) -> None:
    """Append-only CSV write. Refuses to rewrite existing dates."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    date = str(row["date"])
    if log_path.exists():
        existing = pd.read_csv(log_path)
        if not existing.empty and date in set(existing["date"].astype(str)):
            raise ValueError(
                f"Refuse overwrite of existing paper signal date {date}. "
                "Append-only; create PAPER_V2 for logic changes."
            )
        if existing.empty or len(existing.columns) == 0:
            df = pd.DataFrame([row], columns=SIGNAL_COLUMNS)
        else:
            df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row], columns=SIGNAL_COLUMNS)
    # Preserve column order
    for c in SIGNAL_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[SIGNAL_COLUMNS]
    df.to_csv(log_path, index=False)


@dataclass
class PaperState:
    cash: float
    weights: dict[str, float]
    shares: dict[str, float]
    raw_target: Optional[str]
    nav: float
    peak_nav: float


def _apply_costs(notional: float, total_bps: float) -> float:
    return abs(notional) * total_bps / 10_000.0


def rebalance_to_weights(
    state: PaperState,
    prices: dict[str, float],
    new_weights: dict[str, float],
    *,
    total_bps: float,
) -> tuple[PaperState, float, list[dict]]:
    """Rebalance at given prices; returns new state, cost, trade legs."""
    nav = float(state.cash)
    for t, sh in state.shares.items():
        px = prices.get(t)
        if px is not None and np.isfinite(px) and sh:
            nav += sh * px
    if nav <= 0:
        return state, 0.0, []

    trades: list[dict] = []
    cost = 0.0
    cash = nav
    for t, sh in list(state.shares.items()):
        if not sh:
            continue
        px = prices.get(t)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        notional = sh * px
        fee = _apply_costs(notional, total_bps)
        cost += fee
        cash += notional - fee
        trades.append({"ticker": t, "side": "sell", "shares": sh, "price": px, "fee": fee})

    # After full liquidation, cash holds NAV net of sell fees; buy target weights
    new_shares: dict[str, float] = {}
    buy_budget = cash
    for t, w in new_weights.items():
        if t == "CASH" or w <= 0:
            continue
        px = prices.get(t)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        alloc = buy_budget * float(w)
        fee = _apply_costs(alloc, total_bps)
        spend = alloc - fee
        if spend <= 0:
            continue
        sh = spend / px
        cost += fee
        cash -= alloc
        new_shares[t] = new_shares.get(t, 0.0) + sh
        trades.append({"ticker": t, "side": "buy", "shares": sh, "price": px, "fee": fee})

    marked = cash + sum(
        new_shares.get(t, 0.0) * prices[t] for t in new_shares if t in prices and np.isfinite(prices[t])
    )
    new_state = PaperState(
        cash=cash,
        weights=dict(new_weights),
        shares=new_shares,
        raw_target=state.raw_target,
        nav=marked,
        peak_nav=max(state.peak_nav, marked),
    )
    return new_state, cost, trades


def mark_nav(state: PaperState, prices: dict[str, float]) -> float:
    nav = float(state.cash)
    for t, sh in state.shares.items():
        px = prices.get(t)
        if px is not None and np.isfinite(px):
            nav += sh * float(px)
    return nav


def build_signal_row(
    date: pd.Timestamp,
    closes: pd.DataFrame,
    indicators: dict,
    decision,
    prev_raw: Optional[str],
    paper_cfg: dict,
) -> dict[str, Any]:
    exp = paper_cfg["exposure"]
    pos = target_weight_for_beta(
        decision.target,
        target_underlying_beta=float(exp["target_underlying_beta"]),
        asset_beta=paper_cfg.get("asset_underlying_beta"),
        uvxy_max_weight=float(exp["uvxy_max_portfolio_weight"]),
        defensive=str(exp.get("defensive_sleeve", "BSV")),
    )
    d = date
    return {
        "date": str(pd.Timestamp(d).date()),
        "SPY": float(closes.loc[d, "SPY"]),
        "QQQ": float(closes.loc[d, "QQQ"]),
        "TQQQ": float(closes.loc[d, "TQQQ"]),
        "rsi_spy": float(indicators["rsi"].loc[d, "SPY"]),
        "rsi_qqq": float(indicators["rsi"].loc[d, "QQQ"]),
        "rsi_tqqq": float(indicators["rsi"].loc[d, "TQQQ"]),
        "rsi_sqqq": float(indicators["rsi"].loc[d, "SQQQ"]),
        "rsi_uvxy": float(indicators["rsi"].loc[d, "UVXY"]),
        "rsi_tecs": float(indicators["rsi"].loc[d, "TECS"]),
        "rsi_bsv": float(indicators["rsi"].loc[d, "BSV"]),
        "spy_sma_200": float(indicators["sma"]["SPY_SMA200"].loc[d]),
        "qqq_sma_20": float(indicators["sma"]["QQQ_SMA20"].loc[d]),
        "tqqq_sma_20": float(indicators["sma"]["TQQQ_SMA20"].loc[d]),
        "regime": decision.regime,
        "branch_id": decision.branch_id,
        "branch_path": " → ".join(decision.branch_path),
        "raw_target": decision.target,
        "paper_target": pos["paper_target"],
        "weights_json": json.dumps(pos["weights"], sort_keys=True),
        "implied_underlying_beta": pos["implied_underlying_beta"],
        "exposure_target_beta": float(exp["target_underlying_beta"]),
        "three_x_etf_weight": pos.get("three_x_etf_weight"),
        "uvxy_overlay": pos.get("overlay"),
        "previous_raw_target": prev_raw,
        "target_changed": bool(prev_raw is None or decision.target != prev_raw),
        "version": "PAPER_V1",
    }


def rolling_metrics(nav: pd.Series, spy: pd.Series, qqq: pd.Series) -> dict[str, float]:
    rets = nav.pct_change()
    out: dict[str, float] = {}
    for w in (20, 60):
        if len(rets.dropna()) >= w:
            r = rets.dropna().iloc[-w:]
            out[f"vol_{w}d"] = float(r.std(ddof=1) * np.sqrt(252)) if len(r) > 1 else float("nan")
            out[f"sharpe_{w}d"] = (
                float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else float("nan")
            )
        else:
            out[f"vol_{w}d"] = float("nan")
            out[f"sharpe_{w}d"] = float("nan")
    # beta
    for name, bench in (("spy", spy), ("qqq", qqq)):
        br = bench.pct_change().reindex(rets.index)
        aligned = pd.concat([rets.rename("r"), br.rename("b")], axis=1).dropna()
        if len(aligned) >= 20 and aligned["b"].var() > 0:
            out[f"beta_{name}"] = float(np.cov(aligned["r"], aligned["b"])[0, 1] / aligned["b"].var())
        else:
            out[f"beta_{name}"] = float("nan")
    peak = nav.cummax()
    out["drawdown"] = float(nav.iloc[-1] / peak.iloc[-1] - 1) if len(nav) else float("nan")
    return out
