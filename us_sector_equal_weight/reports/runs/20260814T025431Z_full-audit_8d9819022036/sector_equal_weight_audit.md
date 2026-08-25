# Sector Equal-Weight (EW9) — Pre-registered Audit

## Research framing

- Independent track: **equal-weight rebalancing**, not sector-momentum retuning.
- Forbidden: ranking, Top-N, SMA/trend, BIL sleeve, vol-weight, leverage, XLRE/XLC.
- ETF common sample `1998-12-22` → `2026-08-12` is labeled **`DISCOVERY_SAMPLE`** (secondary observation from sector_momentum research).
- Leading on discovery alone is **not** independent validation.
- Run: `/home/ec2-user/strategy-backtest/us_sector_equal_weight/reports/runs/20260814T025431Z_full-audit_8d9819022036`

## Gate: `DISCOVERY_ONLY` (9/13)

```json
{
  "discovery_cagr_gt_spy": true,
  "majority_pseudo_oos_gt_spy": false,
  "majority_fixed_endpoints_gt_spy": true,
  "rolling_5y_ge_55": false,
  "rolling_10y_ge_60": false,
  "cost_10bp_not_flip": true,
  "cost_20bp_not_flip": true,
  "delay_not_flip": true,
  "french_same_direction": true,
  "not_single_sector_dominated": true,
  "vs_rsp_incremental": true,
  "monthly_covers_extra_cost_vs_q_a": false,
  "maxdd_not_worse_than_spy_by_5pp": true
}
```

- Notes: `{'pseudo_oos_win_frac': '0/5', 'endpoint_win_frac': '7/7', 'cagr_edge_vs_rsp_same_span': '-0.0027741523356892284', 'rsp_exposure_warning': 'EW9_close_to_RSP_general_equal_weight_exposure', 'prefer_lower_turnover_if_false': 'If monthly_covers_extra_cost_vs_q_a is false, prefer quarterly/annual; do not pick frequency by max historical CAGR alone.'}`
- RSP similarity: `EW9_close_to_RSP_general_equal_weight_exposure_not_sector_alpha`
- Frequency hint: `prefer_EW9_quarterly_or_annual_lower_turnover`

## Discovery sample metrics (DISCOVERY_SAMPLE)

| name | CAGR | Sharpe(rf) | MaxDD | final wealth | ann turnover | cost drag |
|---|---:|---:|---:|---:|---:|---:|
| EW9_monthly | 9.24% | 0.4730 | -53.01% | 11.4768 | 0.1746 | 0.02% |
| EW9_quarterly | 9.33% | 0.4782 | -52.39% | 11.7178 | 0.1104 | 0.01% |
| EW9_annual | 9.28% | 0.4781 | -52.38% | 11.5757 | 0.0620 | 0.01% |
| ew9_no_rebalance_basket | 8.59% | 0.4368 | -52.51% | 9.7307 | 0.0181 | 0.00% |
| spy_bh | 8.81% | 0.4341 | -55.19% | 10.3248 | 0.0000 | 0.00% |
| spy_monthly_reset | 8.71% | 0.4293 | -55.40% | 10.0235 | 0.0181 | 0.00% |
| rsp_bh | 11.42% | 0.5651 | -59.92% | 12.3940 | 0.0000 | 0.00% |
| EW9_monthly_on_rsp_span | 11.14% | 0.5937 | -53.01% | 11.5908 | 0.1676 | 0.02% |
| sector_cap_weight_proxy | NOT_COMPUTED | — | — | — | — | — |

## Metric C (formal relative NAV)

- **vs_spy**: final_rel `1.1397`, rel CAGR `0.47%`, max rel UW `-22.48%`, UW sessions `3754.0000`, UW months `180.0000`, current `-19.51%`
- **vs_no_rebalance**: final_rel `1.1794`, rel CAGR `0.60%`, max rel UW `-8.70%`, UW sessions `2059.0000`, UW months `99.0000`, current `-1.53%`
- **monthly_vs_quarterly**: final_rel `0.9794`, rel CAGR `-0.08%`, max rel UW `-2.92%`, UW sessions `6585.0000`, UW months `315.0000`, current `-2.63%`
- **monthly_vs_annual**: final_rel `0.9915`, rel CAGR `-0.03%`, max rel UW `-3.00%`, UW sessions `5182.0000`, UW months `249.0000`, current `-1.82%`
- **vs_rsp**: final_rel `1.0380`, rel CAGR `0.16%`, max rel UW `-24.35%`, UW sessions `4456.0000`, UW months `214.0000`, current `-12.57%`

## Attribution

- Avg weights: `{'XLB': 0.11109489023798796, 'XLE': 0.11116665623459815, 'XLF': 0.11096103045719119, 'XLI': 0.11115652229270367, 'XLK': 0.11132106337789674, 'XLP': 0.11114624301553333, 'XLU': 0.11087081255853208, 'XLV': 0.11120295106749291, 'XLY': 0.11107983075806396}`
- Dominance: `{'top_sector': 'XLK', 'top_share': 0.14069121272797605, 'dominated': False, 'threshold': 0.4}`
- Tech/cap-weight: `{'ew9_avg_xlk': 0.11132106337789674, 'ew9_target_xlk': 0.1111111111111111, 'spy_tech_weight_pit': 'NOT_COMPUTED', 'spy_tech_proxy_note': None, 'sector_cap_weight_proxy': 'NOT_COMPUTED_no_reliable_PIT_sector_weights'}`
- Rebalance vs hold: `{'status': 'OK', 'ew_cagr': 0.09243376442908957, 'hold_cagr': 0.08592138209911737, 'rebalance_cagr_edge': 0.0065123823299721995, 'final_rel_ew_over_hold': 1.1794446637920046}`

## Pseudo-OOS starts (pre-registered; all kept)

- `2003-01-02`: monthly `11.42%` vs SPY `11.63%`
- `2008-01-02`: monthly `10.46%` vs SPY `11.37%`
- `2013-01-02`: monthly `13.47%` vs SPY `15.17%`
- `2018-01-02`: monthly `12.69%` vs SPY `14.87%`
- `2021-01-04`: monthly `14.46%` vs SPY `15.35%`

## Fixed endpoints

- `2005-12-30`: monthly `5.10%` vs SPY `1.92%`
- `2008-12-31`: monthly `1.63%` vs SPY `-1.27%`
- `2012-12-31`: monthly `5.29%` vs SPY `2.99%`
- `2016-12-30`: monthly `7.12%` vs SPY `5.38%`
- `2020-12-31`: monthly `7.96%` vs SPY `7.22%`
- `2024-12-31`: monthly `8.69%` vs SPY `8.16%`
- `latest`: monthly `9.24%` vs SPY `8.81%`

## Robustness

- Rolling: `{'3y': {'n': 99, 'win_rate': 0.5656565656565656, 'years': 3}, '5y': {'n': 91, 'win_rate': 0.5164835164835165, 'years': 5}, '10y': {'n': 71, 'win_rate': 0.5211267605633803, 'years': 10}}`
- Cost stress: `{'5.0': {'EW9_monthly': {'status': 'OK', 'cagr': 0.09243376442908957, 'final_wealth': 11.476799545689133, 'max_drawdown': -0.5300521971316585, 'start': '1999-01-04', 'end': '2026-08-12'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.09325650630574, 'final_wealth': 11.717791511542199, 'max_drawdown': -0.5239327925042452, 'start': '1999-01-04', 'end': '2026-08-12'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.09277337680186615, 'final_wealth': 11.575691866658138, 'max_drawdown': -0.5237761540248604, 'start': '1999-01-04', 'end': '2026-08-12'}}, '10.0': {'EW9_monthly': {'status': 'OK', 'cagr': 0.09224302879138979, 'final_wealth': 11.421616493099318, 'max_drawdown': -0.530203474087207, 'start': '1999-01-04', 'end': '2026-08-12'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.09313580020642842, 'final_wealth': 11.68213230286815, 'max_drawdown': -0.524019778639838, 'start': '1999-01-04', 'end': '2026-08-12'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.09270558551041175, 'final_wealth': 11.555886225684075, 'max_drawdown': -0.5238363015593273, 'start': '1999-01-04', 'end': '2026-08-12'}}, '20.0': {'EW9_monthly': {'status': 'OK', 'cagr': 0.09186161913970703, 'final_wealth': 11.312034163958609, 'max_drawdown': -0.5305058914977211, 'start': '1999-01-04', 'end': '2026-08-12'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.09289438929493965, 'final_wealth': 11.611127759137926, 'max_drawdown': -0.5241937137885408, 'start': '1999-01-04', 'end': '2026-08-12'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.0925699777188238, 'final_wealth': 11.516365540949726, 'max_drawdown': -0.5239565853216932, 'start': '1999-01-04', 'end': '2026-08-12'}}}`
- Delay+1 session: `{'EW9_monthly': {'status': 'OK', 'cagr': 0.09285881574579924, 'final_wealth': 11.597880040981968, 'max_drawdown': -0.52823367584878, 'start': '1999-01-05', 'end': '2026-08-12'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.09345663274309701, 'final_wealth': 11.774264024179894, 'max_drawdown': -0.5229047644193026, 'start': '1999-01-05', 'end': '2026-08-12'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.09281203911867775, 'final_wealth': 11.58418669335357, 'max_drawdown': -0.5235549355189308, 'start': '1999-01-05', 'end': '2026-08-12'}}`
- Exclude recent years: `{'1': {'EW9_monthly': {'status': 'OK', 'cagr': 0.08791908638192769, 'final_wealth': 9.410327102159428, 'max_drawdown': -0.5300521971316585, 'start': '1999-01-04', 'end': '2025-08-12'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.08864024108555046, 'final_wealth': 9.57769353995974, 'max_drawdown': -0.5239327925042452, 'start': '1999-01-04', 'end': '2025-08-12'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.08858274840844382, 'final_wealth': 9.564246166351564, 'max_drawdown': -0.5237761540248604, 'start': '1999-01-04', 'end': '2025-08-12'}, 'spy_bh': {'status': 'OK', 'cagr': 0.08363869756945808, 'final_wealth': 8.495772788853985, 'max_drawdown': -0.5518943935996453, 'start': '1998-12-23', 'end': '2025-08-12'}}, '2': {'EW9_monthly': {'status': 'OK', 'cagr': 0.08576710913111762, 'final_wealth': 8.22272174903541, 'max_drawdown': -0.5300521971316585, 'start': '1999-01-04', 'end': '2024-08-12'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.08634748943636783, 'final_wealth': 8.336004652305379, 'max_drawdown': -0.5239327925042452, 'start': '1999-01-04', 'end': '2024-08-12'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.08651969673203053, 'final_wealth': 8.369904845084944, 'max_drawdown': -0.5237761540248604, 'start': '1999-01-04', 'end': '2024-08-12'}, 'spy_bh': {'status': 'OK', 'cagr': 0.07863124443678116, 'final_wealth': 6.96262046098678, 'max_drawdown': -0.5518943935996453, 'start': '1998-12-23', 'end': '2024-08-12'}}, '3': {'EW9_monthly': {'status': 'OK', 'cagr': 0.08393735141251302, 'final_wealth': 7.262539365533136, 'max_drawdown': -0.5300521971316585, 'start': '1999-01-04', 'end': '2023-08-11'}, 'EW9_quarterly': {'status': 'OK', 'cagr': 0.08451928987058177, 'final_wealth': 7.359065053237159, 'max_drawdown': -0.5239327925042452, 'start': '1999-01-04', 'end': '2023-08-11'}, 'EW9_annual': {'status': 'OK', 'cagr': 0.0846025974610598, 'final_wealth': 7.372983522891352, 'max_drawdown': -0.5237761540248604, 'start': '1999-01-04', 'end': '2023-08-11'}, 'spy_bh': {'status': 'OK', 'cagr': 0.07350572863295479, 'final_wealth': 5.738347101808527, 'max_drawdown': -0.5518943935996453, 'start': '1998-12-23', 'end': '2023-08-11'}}}`
- Leave-one-out: `{'XLB': {'cagr': 0.09312584130985657, 'final_wealth': 11.679194903037397, 'max_drawdown': -0.5258050884836657, 'n_sectors': 8}, 'XLE': {'cagr': 0.09050019472643478, 'final_wealth': 10.929088558938385, 'max_drawdown': -0.5375831132002332, 'n_sectors': 8}, 'XLF': {'cagr': 0.09513311758762732, 'final_wealth': 12.285862364993438, 'max_drawdown': -0.47934147468704347, 'n_sectors': 8}, 'XLI': {'cagr': 0.09179893158312691, 'final_wealth': 11.294120711710823, 'max_drawdown': -0.519192615703133, 'n_sectors': 8}, 'XLK': {'cagr': 0.08876206312168988, 'final_wealth': 10.458309098734977, 'max_drawdown': -0.5337574244113277, 'n_sectors': 8}, 'XLP': {'cagr': 0.09457434808191212, 'final_wealth': 12.113999023019092, 'max_drawdown': -0.5564490020014929, 'n_sectors': 8}, 'XLU': {'cagr': 0.09316726508834994, 'final_wealth': 11.691417622654622, 'max_drawdown': -0.5427471970939004, 'n_sectors': 8}, 'XLV': {'cagr': 0.09253134357438886, 'final_wealth': 11.505130111194994, 'max_drawdown': -0.5470716803410836, 'n_sectors': 8}, 'XLY': {'cagr': 0.09129965998277312, 'final_wealth': 11.152422720403704, 'max_drawdown': -0.5277502871030033, 'n_sectors': 8}}`
- Bootstrap: `{'status': 'OK', 'n_boot': 500, 'block': 21, 'mean_edge': 0.001007620648167942, 'p05': -0.012747294372162153, 'p50': 0.0008607620602810728, 'p95': 0.014511315342633176, 'frac_positive': 0.538}`

## French external mechanism validation

- Disclaimer: `ETF Select Sector SPDRs and French 12 industries cannot be perfectly aligned. Mapping frozen prior to result inspection; do not retune to raise returns.
`
- Columns: `['NoDur', 'Durbl', 'Manuf', 'Enrgy', 'Chems', 'BusEq', 'Telcm', 'Utils', 'Shops', 'Hlth', 'Money', 'Other']`
- `pre_etf` EW9_monthly CAGR `11.66%` (tradable=`False`)
- `post_etf` EW9_monthly CAGR `9.92%` (tradable=`False`)
- `full` EW9_monthly CAGR `11.23%` (tradable=`False`)

## Hard constraints respected

- IBKR not modified
- Sector-momentum buffer not promoted; momentum not retuned
- No claim of guaranteed profits
- Cap-weight proxy NOT_COMPUTED without PIT weights
