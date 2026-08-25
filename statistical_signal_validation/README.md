# Statistical Signal Validation

Cross-project statistical tests for strategy active returns. **Does not** modify
strategy rules, parameters, IBKR, or production configs.

## Focus (this run)

`us_sector_equal_weight` EW9 formal results vs SPY / RSP / no-rebalance, plus a
monorepo **trial registry** (including failed versions) for multiple-testing
deflation.

```bash
cd strategy-backtest/statistical_signal_validation
pip install -e .
ssv-validate run-ew9
ssv-validate full-report
```
