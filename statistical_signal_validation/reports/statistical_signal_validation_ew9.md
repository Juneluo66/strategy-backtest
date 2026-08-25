# Statistical Signal Validation — EW9 Focus

## Scope

- Cross-project SSV; **no** strategy/parameter/IBKR/production changes.
- Discovery sample: `1998-12-22` → `2026-08-12` (**DISCOVERY_SAMPLE**)
- Source audit run: `/home/ec2-user/strategy-backtest/us_sector_equal_weight/reports/runs/20260814T025431Z_full-audit_8d9819022036`
- SSV run: `/home/ec2-user/strategy-backtest/statistical_signal_validation/reports/runs/20260814T031429Z_ew9_statval`

## Classification (mandatory)

- EW9 hypothesis source: `sector_momentum_audit_secondary_discovery`
- EW9_monthly: `DISCOVERY_ONLY`
- EW9_quarterly: `PRE_REGISTERED_SECONDARY` (**not** promoted to primary despite higher discovery CAGR)
- EW9_annual: `PRE_REGISTERED_SECONDARY`
- Pseudo-OOS: `0/5` (enters final judgment)
- Fixed endpoints: `All 7 fixed endpoints share the 1998 discovery common start; they are not independent start-date validations.`
- French: `MECHANISM_SUPPORT_not_tradable_OOS`

## Trial registry

- **n_trials (incl. failures) = 36**
- By project: `{'dual_momentum_etf': 7, 'us_equity_strategy_research': 12, 'multi_asset_etf_trend': 3, 'us_sector_momentum': 3, 'us_sector_equal_weight': 5, 'max_effect_vix': 3, 'etf_rotation': 1, 'dividend_lowvol_quality': 1, 'low_max_defensive': 1}`

## Overall judgment: `FORWARD_EVIDENCE_REQUIRED_NO_EW9_RETURN_CLAIM`

## Batteries

### EW9_monthly vs SPY

- CAGR edge: `0.52%`; relative CAGR `0.47%`; final rel wealth `1.1397`
- Arithmetic active mean (ann): `0.24%`
- Information ratio: `0.0435`; TE `5.49%`
- Newey-West t: `0.2897` (p=`0.7721`, lags=10)
- Bootstrap P(CAGR edge>0): 1m `73.00%`, 3m `70.70%`, 12m `67.80%`
- Bootstrap P(final rel>1): 12m `67.80%`
- PSR(active): `59.03%`; DSR(active, n_trials=36): `2.75%`
- MinTRL(active): `1430.4110` years (observed `27.5556`, sufficient=`False`)
- Skew/kurt/acf1: `-0.3709` / `12.1872` / `-0.1453`
- Effective n: `9305.6792` (n=`6944`, ρ1=`-0.1453`)
- Power years (80%): `888.2545`

### EW9_monthly vs no-rebalance (rebalance premium)

- CAGR edge: `0.65%`; relative CAGR `0.60%`; final rel wealth `1.1794`
- Arithmetic active mean (ann): `0.56%`
- Information ratio: `0.2712`; TE `2.05%`
- Newey-West t: `1.5934` (p=`0.1111`, lags=10)
- Bootstrap P(CAGR edge>0): 1m `96.10%`, 3m `97.30%`, 12m `97.30%`
- Bootstrap P(final rel>1): 12m `97.30%`
- PSR(active): `92.39%`; DSR(active, n_trials=36): `23.34%`
- MinTRL(active): `36.3745` years (observed `27.5556`, sufficient=`False`)
- Skew/kurt/acf1: `0.7045` / `12.8699` / `-0.0152`
- Effective n: `7158.3010` (n=`6944`, ρ1=`-0.0152`)
- Power years (80%): `77.8449`

### EW9_monthly vs RSP (same span)

- CAGR edge: `0.18%`; relative CAGR `0.16%`; final rel wealth `1.0380`
- Arithmetic active mean (ann): `-0.26%`
- Information ratio: `-0.0608`; TE `4.35%`
- Newey-West t: `-0.3267` (p=`0.7439`, lags=9)
- Bootstrap P(CAGR edge>0): 1m `56.60%`, 3m `61.20%`, 12m `67.70%`
- Bootstrap P(final rel>1): 12m `67.70%`
- PSR(active): `38.48%`; DSR(active, n_trials=36): `0.73%`
- MinTRL(active): `730.4177` years (observed `23.1627`, sufficient=`False`)
- Skew/kurt/acf1: `-0.2030` / `6.3952` / `-0.0625`
- Effective n: `6615.4981` (n=`5837`, ρ1=`-0.0625`)
- Power years (80%): `4651.7587`

### EW9_quarterly vs SPY (secondary; not primary)

- CAGR edge: `0.60%`; relative CAGR `0.55%`; final rel wealth `1.1637`
- Arithmetic active mean (ann): `0.30%`
- Information ratio: `0.0551`; TE `5.53%`
- Newey-West t: `0.3676` (p=`0.7132`, lags=10)
- Bootstrap P(CAGR edge>0): 1m `76.60%`, 3m `74.50%`, 12m `71.20%`
- Bootstrap P(final rel>1): 12m `71.20%`
- PSR(active): `61.36%`; DSR(active, n_trials=36): `3.16%`
- MinTRL(active): `893.6890` years (observed `27.5556`, sufficient=`False`)
- Skew/kurt/acf1: `-0.3840` / `12.1435` / `-0.1441`
- Effective n: `9282.0485` (n=`6944`, ρ1=`-0.1441`)
- Power years (80%): `668.5070`

### EW9_annual vs SPY (secondary; not primary)

- CAGR edge: `0.55%`; relative CAGR `0.51%`; final rel wealth `1.1495`
- Arithmetic active mean (ann): `0.23%`
- Information ratio: `0.0420`; TE `5.56%`
- Newey-West t: `0.2779` (p=`0.7811`, lags=10)
- Bootstrap P(CAGR edge>0): 1m `73.40%`, 3m `71.90%`, 12m `69.80%`
- Bootstrap P(final rel>1): 12m `69.80%`
- PSR(active): `58.72%`; DSR(active, n_trials=36): `2.71%`
- MinTRL(active): `1534.9233` years (observed `27.5556`, sufficient=`False`)
- Skew/kurt/acf1: `-0.4943` / `12.6075` / `-0.1424`
- Effective n: `9250.8107` (n=`6944`, ρ1=`-0.1424`)
- Power years (80%): `801.7298`

## Multiple-testing adjustments (Newey-West p-values)

```json
{
  "bonferroni": {
    "EW9_monthly_vs_SPY": 1.0,
    "EW9_monthly_vs_no_rebalance": 0.5555987229140402,
    "EW9_monthly_vs_RSP_same_span": 1.0,
    "EW9_quarterly_vs_SPY": 1.0,
    "EW9_annual_vs_SPY": 1.0
  },
  "bh_fdr": {
    "EW9_annual_vs_SPY": 0.7810742305043876,
    "EW9_monthly_vs_SPY": 0.7810742305043876,
    "EW9_monthly_vs_RSP_same_span": 0.7810742305043876,
    "EW9_quarterly_vs_SPY": 0.7810742305043876,
    "EW9_monthly_vs_no_rebalance": 0.5555987229140402
  },
  "m": 5
}
```

## Answers to the six questions

1. **CAGR vs SPY noise?** `NO` — edge `0.52%`, NW p=`0.7721`, boot12=`67.80%`, DSR=`2.75%`. Discovery sample only; pseudo-OOS 0/5 must override naive full-sample edge.
2. **Rebalance premium noise?** `NO` — edge `0.65%`, NW p=`0.1111`, boot12=`97.30%`, DSR=`23.34%`.
3. **Independent vs RSP?** `NO_MATERIAL_INDEPENDENT_INCREMENT` — same-span edge `0.18%` (EW9_close_to_RSP_general_equal_weight_exposure_not_sector_alpha).
4. **Added sample needed?** Need ~888 years at current IR/TE for 80% power (MinTRL sufficient=`False`).
5. **Forward evidence only?** `YES` — EW9 hypothesis is a secondary discovery after sector_momentum audit (DISCOVERY_SAMPLE).; Pseudo-OOS fixed starts beat SPY in 0/5 cases.; Fixed-endpoint 7/7 all share 1998 start (not independent starts).; French support is MECHANISM_SUPPORT only, not tradable OOS.; DSR uses full monorepo trial budget including failures.
6. **Any statistically evidenced return strategy?** `NO_STATISTICAL_RETURN_EDGE_CLEARED` — dual_momentum 80/20 remains paper default for process/diversifier thesis, not because DSR clears a return edge vs SPY.; multi_asset trend candidate label is audit-gate based, not this SSV battery.; EW9 is DISCOVERY_ONLY and fails noise-exclusion here.; half_protect is defensive shadow only, not a return primary.

## Hard constraints

- No strategy/parameter changes
- No IBKR / production config changes
- Quarterly not promoted to primary on CAGR
