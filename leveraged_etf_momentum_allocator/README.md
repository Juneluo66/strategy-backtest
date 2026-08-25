# Leveraged ETF Momentum Allocator

Independent audit project for **QuantConnect Strategy #60**: [Leveraged ETF Momentum Allocator](https://www.quantconnect.com/strategies/60/Leveraged-ETF-Momentum-Allocator).

## Status

| Item | Status |
|------|--------|
| Project scaffold | **VERIFIED** — complete |
| Backtest / metrics / benchmark framework | **VERIFIED** — implemented |
| Original strategy rules (universe, momentum, rebalance, etc.) | **UNVERIFIED** — `REQUIRES_SOURCE_VERIFICATION` |
| Exact replication backtest | **BLOCKED** until source verified |
| Index performance targets (2016–2025) | **VERIFIED** — reconciliation targets only, not for parameter inference |

### Index reconciliation targets (NOT parameters)

| Metric | QuantConnect index |
|--------|-------------------|
| Period | ~2016-01 to 2025-12 |
| CAGR | 203.45% |
| Sharpe | 2.67 |
| Max Drawdown | -54.2% |
| Calmar | 3.75 |
| Sortino | 3.43 |

These numbers are stored in `configs/original.yaml` under `reconciliation_targets` for post-replication comparison only.

## Guardrails

1. **`configs/original.yaml`** keeps all strategy parameters as `null` / `REQUIRES_SOURCE_VERIFICATION`.
2. **`run_original.py`** refuses to run when `exact_rules_verified: false`.
3. No guessed ETF lists (TQQQ/SOXL/UPRO etc.) in original config.
4. Research extensions live in `configs/research.yaml` and are labeled `RESEARCH_EXTENSION`.
5. Frozen sibling projects in `strategy-backtest/` are not modified.

## Conventions (aligned with sibling projects)

- **Prices**: Yahoo `Adj Close`; open scaled by `AdjClose/Close` (see `dual_momentum_etf`).
- **Execution**: signal at rebalance close → fill at next session open (default).
- **Metrics**: daily returns, 252 trading days/year, Sharpe rf=0 by default (`low_max_defensive/metrics_ext.py` pattern).
- **Costs**: commission + slippage bps per leg (`configs/costs.yaml`).

## Quick start

```bash
cd strategy-backtest/leveraged_etf_momentum_allocator
pip install -e ".[dev]"
pytest -q
python scripts/run_original.py   # expected: abort with verification message
```

## Project layout

```
leveraged_etf_momentum_allocator/
├── configs/          original (frozen unknown), research, costs
├── data/             OHLCV cache
├── src/              core library
├── scripts/          CLI runners
├── tests/            pytest suite
└── reports/          audit outputs (stubs until replication)
```

## Next step

Obtain QuantConnect Strategy #60 official source code or verified rule documentation, then populate `configs/original.yaml` and set `exact_rules_verified: true`.
