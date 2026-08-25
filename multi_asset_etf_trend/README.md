# Multi-asset ETF trend (independent research track)

Absolute-momentum / multi-horizon trend on eight risk ETFs vs **BIL**.  
**No** relationship to D+C, 80/20, 60/40 D+C, or half_protect for parameter choice.

## Universe

Risk: SPY, EFA, EEM, IEF, TLT, GLD, DBC, VNQ  
Cash: BIL

## Pre-registered versions (only)

1. `base_12m_equal`
2. `ensemble_equal` (3/6/12 score)
3. `ensemble_risk_balanced` (same score × inverse-vol base; no renormalize-to-full-risk)

## Commands

```bash
cd /home/ec2-user/strategy-backtest/multi_asset_etf_trend
python3 -m pip install -e '.[dev]'
multi-asset-etf-trend fetch
multi-asset-etf-trend audit-data
multi-asset-etf-trend full-audit
pytest -q
```

## Outputs

- `reports/multi_asset_etf_trend_audit.md`
- `reports/multi_asset_etf_trend_metrics.csv`
- `reports/multi_asset_etf_trend_rolling.csv`
- `reports/multi_asset_etf_trend_asset_contributions.csv`
- `reports/multi_asset_etf_trend_return_adequacy.md` (return sufficiency vs BIL / 60-40)

Gate labels: `MULTI_ASSET_TREND_CANDIDATE` or `REJECTED` (research only; not a live PnL claim).

Return-adequacy labels: `CAPITAL_PRESERVATION_CANDIDATE` | `MULTI_ASSET_RETURN_CANDIDATE` | `REJECTED`.

```bash
multi-asset-etf-trend return-adequacy-audit
```
