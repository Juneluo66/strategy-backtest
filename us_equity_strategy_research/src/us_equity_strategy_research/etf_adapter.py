"""Read-only adapter for frozen dual_momentum_etf D+C and sleeve (do not retune)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from .backtest.costs import etf_flat_cost
from .data.prices import cash_symbol_on
from .data.universe import month_end_index, next_trading_day


def dual_momentum_root() -> Path:
    return Path(__file__).resolve().parents[3] / "dual_momentum_etf"


def load_frozen_dc_config() -> tuple[dict, dict, str]:
    root = dual_momentum_root()
    frozen = yaml.safe_load((root / "configs" / "frozen.yaml").read_text(encoding="utf-8"))
    universe = yaml.safe_load((root / "configs" / "universe.yaml").read_text(encoding="utf-8"))
    payload = yaml.safe_dump({"frozen": frozen, "universe": universe}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return frozen, universe, digest


def verify_frozen_hash(expected_prefix: str = "8725aaf18743") -> dict:
    _, _, digest = load_frozen_dc_config()
    known = "8725aaf1874386e68016e9e7ad290f09b8528a34ecf7857f350acfa8a208b1c2"
    return {
        "config_hash": digest,
        "matches_known_freeze": digest == known,
        "prefix_ok": digest.startswith(expected_prefix),
        "ok": digest == known,
    }


def simple_dual_momentum(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    risk_symbols: list[str],
    *,
    one_way_bps: float = 5.0,
    require_trend_consistency: bool = True,
    category_map: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """Lightweight D+C-like runner for VTI/VXUS experiments; not a retune of attribution_DC."""
    common = opens.index.intersection(closes.index).sort_values()
    opens, closes = opens.reindex(common), closes.reindex(common)
    month_ends = month_end_index(common)
    execute_map = {}
    for signal in month_ends:
        nxt = next_trading_day(common, signal)
        if nxt is not None:
            execute_map[nxt] = signal

    weights = pd.Series(dtype=float)
    pending = None
    prev_close = None
    rows = []
    for date in common:
        gross = 0.0
        cost = 0.0
        if prev_close is not None and not weights.empty:
            overnight = (opens.loc[date] / prev_close - 1).replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
            gross += float((weights.reindex(overnight.index, fill_value=0.0) * overnight).sum())
        if date in execute_map and pending is not None:
            turnover = float(pending.sub(weights, fill_value=0.0).abs().sum())
            cost += etf_flat_cost(turnover, one_way_bps)
            weights = pending
            pending = None
        if not weights.empty:
            intraday = (closes.loc[date] / opens.loc[date] - 1).replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
            gross += float((weights.reindex(intraday.index, fill_value=0.0) * intraday).sum())
        if date in set(month_ends):
            pending = _dc_like_target(
                closes,
                date,
                risk_symbols,
                require_trend_consistency=require_trend_consistency,
                category_map=category_map or {},
            )
        rows.append({"date": date, "gross_return": gross, "cost": cost, "net_return": gross - cost})
        prev_close = closes.loc[date]
    equity = pd.DataFrame(rows).set_index("date")
    equity["equity_net"] = (1 + equity["net_return"]).cumprod()
    return equity


def _dc_like_target(
    closes: pd.DataFrame,
    date: pd.Timestamp,
    risk_symbols: list[str],
    *,
    require_trend_consistency: bool,
    category_map: dict[str, str],
) -> pd.Series:
    # Score 0.6*R5M + 0.4*R12M; 10m SMA; optional 3/6/12 consistency; category max 1; top2
    hist = closes.loc[:date]
    if len(hist) < 252:
        cash = cash_symbol_on(date, closes)
        return pd.Series({cash: 1.0})
    # month-end sampling approx via 21-day steps
    px = hist.iloc[::-21][::-1]
    if len(px) < 13:
        cash = cash_symbol_on(date, closes)
        return pd.Series({cash: 1.0})
    last = px.iloc[-1]
    r5 = last / px.iloc[-6] - 1 if len(px) >= 6 else pd.Series(dtype=float)
    r12 = last / px.iloc[-13] - 1 if len(px) >= 13 else pd.Series(dtype=float)
    score = 0.6 * r5 + 0.4 * r12
    sma10 = px.iloc[-10:].mean() if len(px) >= 10 else last
    eligible = []
    for symbol in risk_symbols:
        if symbol not in score.index or pd.isna(score[symbol]):
            continue
        if last[symbol] <= sma10[symbol]:
            continue
        if require_trend_consistency:
            r3 = last[symbol] / px.iloc[-4][symbol] - 1 if len(px) >= 4 else float("nan")
            r6 = last[symbol] / px.iloc[-7][symbol] - 1 if len(px) >= 7 else float("nan")
            r12v = r12.get(symbol, float("nan"))
            if not (r3 > 0 and r6 > 0 and r12v > 0):
                continue
        eligible.append((symbol, float(score[symbol])))
    eligible.sort(key=lambda x: x[1], reverse=True)
    chosen = []
    used_cat = set()
    for symbol, _ in eligible:
        cat = category_map.get(symbol, symbol)
        if cat in used_cat:
            continue
        chosen.append(symbol)
        used_cat.add(cat)
        if len(chosen) == 2:
            break
    cash = cash_symbol_on(date, closes)
    if not chosen:
        return pd.Series({cash: 1.0})
    w = {s: 1.0 / len(chosen) for s in chosen}
    if len(chosen) < 2:
        w[cash] = 1.0 - sum(w.values())
    return pd.Series(w, dtype=float)


def buy_and_hold(closes: pd.Series) -> pd.Series:
    return closes.pct_change(fill_method=None).fillna(0.0)


def sixty_forty(spy: pd.Series, ief: pd.Series) -> pd.Series:
    aligned = pd.concat([spy.rename("spy"), ief.rename("ief")], axis=1).dropna()
    r = aligned.pct_change(fill_method=None).fillna(0.0)
    return 0.6 * r["spy"] + 0.4 * r["ief"]


def trend_vti_sgov(closes: pd.DataFrame) -> pd.Series:
    """VTI vs cash using prior-day 10-month SMA regime (no same-close fill)."""
    vti = closes["VTI"]
    cash_rets = []
    prev = None
    for date in closes.index:
        cash_sym = cash_symbol_on(date, closes)
        if prev is None:
            cash_rets.append(0.0)
        else:
            cash_rets.append(float(closes.loc[date, cash_sym] / closes.loc[prev, cash_sym] - 1))
        prev = date
    cash_r = pd.Series(cash_rets, index=closes.index)
    # Regime known at prior close: VTI above 210-day SMA as of yesterday
    sma = vti.rolling(210, min_periods=100).mean()
    risk_on = (vti > sma).shift(1).fillna(False).astype(bool)
    vti_r = vti.pct_change(fill_method=None).fillna(0.0)
    return risk_on.astype(float) * vti_r + (~risk_on).astype(float) * cash_r


def outer_blend(leg_a: pd.Series, leg_b: pd.Series, w_a: float, w_b: float) -> pd.Series:
    """Constant-mix daily returns approximation with monthly reset drag ignored here;
    comparison layer documents this as research blend, while frozen sleeve remains in dual_momentum_etf.
    """
    aligned = pd.concat([leg_a.rename("a"), leg_b.rename("b")], axis=1).dropna()
    return w_a * aligned["a"] + w_b * aligned["b"]
