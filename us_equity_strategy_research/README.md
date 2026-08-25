# US Equity Strategy Research

Independent research package comparing US equity multifactor / 12-1 momentum / PEAD
against the frozen ETF dual-momentum sleeve in `dual_momentum_etf`.

## Hard constraints

- **H1** `INDEX_EXIT` ≠ `DELISTING`
- **H2** SEC facts PIT uses `filed` / `available_at` only
- **H3** Single return basis: Yahoo Adj Close (+ Open scaled by AdjClose/Close)
- **H4** SGOV pre-history uses BIL; comparisons use common interval
- **H5** Fixed portfolio construction order
- **H6** Phase stop / downgrade gates (no surprise → PEAD BLOCKED; no PIT fundamentals → A/B1–B3 BLOCKED)

## Quick start

```bash
cd /home/ec2-user/strategy-backtest/us_equity_strategy_research
python3 -m pip install -e '.[dev]'
# optional: editable sibling packages for frozen D+C runner + membership provider
python3 -m pip install -e ../max_effect_vix -e ../dual_momentum_etf
```

## Commands

```bash
us-equity-research audit-data
us-equity-research fetch
us-equity-research backtest --strategy all --limit 80
us-equity-research robustness
us-equity-research compare
us-equity-research etf-trend-sleeves              # rotation / SPY-QQQ protect / F3 vs 80/20
us-equity-research spy-qqq-protect-audit          # pre-registered full/half/joint_half protect audit
us-equity-research half-protect-relative-audit    # Metric C relative audit of frozen half_protect
us-equity-research final-audit
pytest -q
```

## Reports

- `reports/us_equity_strategy_data_audit.md`
- `reports/us_equity_multifactor_report.md`
- `reports/us_equity_momentum_report.md`
- `reports/us_equity_pead_report.md`
- `reports/us_equity_etf_comparison.md`
- `reports/us_equity_portfolio_comparison.md`
- `reports/us_equity_final_audit.md`
- `reports/PROJECT_STATUS.md`
