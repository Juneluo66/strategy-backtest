# SPY/QQQ Protect — Pre-registered Half-Protect Audit

## Verdict

- Gate: **`DEFENSIVE_SHADOW_CANDIDATE`** (8/9)
- half_protect CAGR `12.33%` vs full `10.09%` (cash drag cut: avg BIL `19.5%` → `9.7%`)
- half MaxDD `-25.51%` vs 80/20 `-38.95%`; Sharpe `0.8274` vs 80/20 `0.7505`
- **Not** a return primary; default paper remains **80% SPY + 20% D+C**; conservative shadow remains **60/40**. No IBKR config change. No further exit-ratio tests.

## Hypothesis (pre-registered)

Full trend exit may create excessive cash drag; cutting each broken leg by **50%** (half_protect) may improve return/drawdown balance vs full_protect, without searching other exit ratios.

- Price panel aligned from `2008-06-02`; strategy equity common interval `2008-07-01` → `2026-08-10` (first executable trade after SMA warmup)
- Base weights: 70% SPY + 30% QQQ; cash = BIL
- Signal: month-end close; execution: next session open; cost: 5 bp one-way
- Primary SMA: 10 months (8/12 only for continuity check)
- Frozen 80/20 and 60/40 **not** retuned; IBKR paper config **not** modified
- Run: `/home/ec2-user/strategy-backtest/us_equity_strategy_research/reports/runs/20260813T082913Z_spy_qqq_protect_audit_c4e302924dcb`

## Benchmark construction audit (fixes prior mislabel)

1. **Why D+C / 80/20 showed ann_turnover=0 previously:** comparison fed return series with empty trade tables; metrics defaulted turnover to 0. That was **NOT_COMPUTED**, not true zero.
2. **D+C costs:** `attribution_DC` `net_return` already deducts internal 5 bp costs (full-sample internal cost total ≈ `0.075000`).
3. **80/20 and 60/40:** `outer_blend_pit` — month-end signal → next open; weights **drift**; outer 5 bp only on sleeve L1 turnover; does **not** re-charge D+C internal costs. Rebalance frequency = **monthly target reset**.
4. **Challengers:** same month-end → next-open and 5 bp one-way on measured turnover.
5. **Buy&hold SPY/VTI:** `turnover_status=buy_and_hold` (activity truly zero).
6. **Adj Close anomaly flags (|ret|>25%):** `0` (sample `[]`).
7. Frozen D+C hash check: `{'config_hash': '8725aaf1874386e68016e9e7ad290f09b8528a34ecf7857f350acfa8a208b1c2', 'matches_known_freeze': True, 'prefix_ok': True, 'ok': True}`
8. **Relative underwater / max DD:** Metric C only (`relative_nav = nav_strategy/nav_benchmark`, both rebased to 1). See `reports/affected_reports_metric_c_fix.md`.

## Main results

| name | cagr | volatility | sharpe | sortino | max_drawdown | max_dd_duration_days | calmar | worst_year | worst_rolling_12m | month_win_rate | year_win_rate | annualized_turnover | avg_trades_per_year | cost_drag_cagr | corr_spy | beta_spy | up_capture | down_capture | rel_spy_max_dd | rel_spy_final_relative_nav | rel_spy_underwater_trading_sessions | rel_spy_underwater_months | rel_8020_max_dd | rel_8020_final_relative_nav | rel_8020_underwater_trading_sessions | rel_8020_underwater_months | turnover_status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full_protect | 10.09% | 13.36% | 0.7880 | 0.9211 | -20.50% | 698.0000 | 0.4922 | -17.04% | -18.39% | 63.76% | 73.68% | 1.7395 | 12.0388 | 0.19% | 0.6762 | 0.4568 | 68.46% | 67.19% | -63.91% | 0.6698 | 4382.0000 | 210.0000 | -55.45% | 0.7346 | 4382.0000 | 210.0000 | measured |
| half_protect | 12.33% | 15.54% | 0.8274 | 1.0466 | -25.51% | 496.0000 | 0.4833 | -19.38% | -20.96% | 65.60% | 78.95% | 0.8836 | 12.0388 | 0.10% | 0.9349 | 0.7348 | 86.06% | 84.92% | -31.31% | 0.9654 | 4382.0000 | 210.0000 | -15.30% | 1.0487 | 4382.0000 | 210.0000 | measured |
| joint_half_protect | 12.00% | 16.55% | 0.7689 | 0.9437 | -32.33% | 517.0000 | 0.3711 | -23.00% | -24.77% | 66.06% | 78.95% | 0.8836 | 12.0388 | 0.10% | 0.9375 | 0.7849 | 88.56% | 87.92% | -34.88% | 0.9152 | 4382.0000 | 210.0000 | -20.20% | 0.9942 | 4070.0000 | 195.0000 | measured |
| spy_bh | 12.47% | 19.77% | 0.6945 | 0.8427 | -47.17% | 588.0000 | 0.2644 | -28.51% | -28.97% | 67.43% | 84.21% | 0.0000 | 0.0000 | 0.00% | 1.0000 | 1.0000 | 100.00% | 100.00% | 0.00% | 1.0000 | 0.0000 | 0.0000 | -13.46% | 1.0780 | 1812.0000 | 87.0000 | buy_and_hold |
| vti_bh | 12.34% | 19.96% | 0.6844 | 0.8333 | -48.02% | 563.0000 | 0.2571 | -29.31% | -28.79% | 66.97% | 84.21% | 0.0000 | 0.0000 | 0.00% | 0.9940 | 1.0034 | 101.65% | 102.00% | -7.24% | 0.9820 | 1744.0000 | 84.0000 | -14.88% | 1.0550 | 1190.0000 | 58.0000 | buy_and_hold |
| dc | 9.31% | 13.03% | 0.7496 | 0.8966 | -17.97% | 635.0000 | 0.5180 | -4.95% | -10.91% | 63.30% | 78.95% | 3.5895 | 12.0388 | 0.39% | 0.4760 | 0.3137 | 50.26% | 47.23% | -73.37% | 0.5863 | 4382.0000 | 210.0000 | -65.94% | 0.6448 | 4382.0000 | 210.0000 | measured |
| frozen_80_20_spy_dc | 12.00% | 17.08% | 0.7505 | 0.9288 | -38.95% | 494.0000 | 0.3081 | -22.34% | -22.80% | 66.51% | 84.21% | 0.0540 | 12.0388 | 0.01% | 0.9901 | 0.8552 | 89.78% | 89.26% | -21.83% | 0.9239 | 4382.0000 | 210.0000 | 0.00% | 1.0000 | 0.0000 | 0.0000 | measured |
| frozen_60_40_spy_dc | 11.45% | 14.90% | 0.8035 | 1.0107 | -29.76% | 517.0000 | 0.3846 | -15.85% | -16.41% | 68.81% | 78.95% | 0.0808 | 12.0388 | 0.01% | 0.9483 | 0.7146 | 79.71% | 78.62% | -39.45% | 0.8417 | 4382.0000 | 210.0000 | -22.54% | 0.9148 | 4382.0000 | 210.0000 | measured |

### Cash drag diagnostic

- full_protect avg BIL weight: `0.19493087557603686`
- half_protect avg BIL weight: `0.09746543778801843`
- joint_half_protect avg BIL weight: `0.08294930875576037`

## Stability (pre-registered only)

### SMA 8 / 10 / 12

- SMA8: full CAGR/Sharpe/MaxDD = `0.1145` / `0.9131` / `-0.2050`; half = `0.1303` / `0.8830` / `-0.2551`
- SMA10: full CAGR/Sharpe/MaxDD = `0.1009` / `0.7880` / `-0.2050`; half = `0.1233` / `0.8274` / `-0.2551`
- SMA12: full CAGR/Sharpe/MaxDD = `0.1060` / `0.8235` / `-0.2046`; half = `0.1259` / `0.8426` / `-0.2551`
### Cost ×2

```json
{
  "full_protect": {
    "cagr": 0.09897103474339164,
    "sharpe": 0.7750161403610099,
    "max_drawdown": -0.20877159193647943
  },
  "half_protect": {
    "cagr": 0.12228187364573095,
    "sharpe": 0.821797991758945,
    "max_drawdown": -0.2550816732770598
  }
}
```

### Extra +1 session delay

```json
{
  "full_protect": {
    "cagr": 0.1008547344296633,
    "sharpe": 0.7844989552105726,
    "max_drawdown": -0.21675069097800903
  },
  "half_protect": {
    "cagr": 0.12262641401472907,
    "sharpe": 0.8219961967711303,
    "max_drawdown": -0.2550816732770601
  }
}
```

### Exclude last year

```json
{
  "full_protect": {
    "cagr": 0.10039998761225744,
    "sharpe": 0.7862665333011203,
    "max_drawdown": -0.20497375890273684
  },
  "half_protect": {
    "cagr": 0.12048705777906799,
    "sharpe": 0.8078435843574414,
    "max_drawdown": -0.2550816732770601
  }
}
```

### Restart 2009-03-01

```json
{
  "full_protect": {
    "cagr": 0.10454729332867951,
    "sharpe": 0.8005121822749571,
    "max_drawdown": -0.2049737589027364
  },
  "half_protect": {
    "cagr": 0.14351435002787727,
    "sharpe": 0.9652493760161973,
    "max_drawdown": -0.246026957451578
  }
}
```

### 2008 window

```json
{
  "full_protect": {
    "cagr": 0.008309333600830193,
    "sharpe": 0.46923461860360416,
    "max_drawdown": -0.007582460036545835
  },
  "half_protect": {
    "cagr": -0.22452003489280636,
    "sharpe": -0.9311045361936369,
    "max_drawdown": -0.2550816732770601
  },
  "joint_half_protect": {
    "cagr": -0.22452003489280636,
    "sharpe": -0.9311045361936369,
    "max_drawdown": -0.2550816732770601
  }
}
```

### 2020 window

```json
{
  "full_protect": {
    "cagr": -0.3377515951654628,
    "sharpe": -1.7482388615305888,
    "max_drawdown": -0.16922616001145185
  },
  "half_protect": {
    "cagr": -0.2869091964729905,
    "sharpe": -0.6479492073931314,
    "max_drawdown": -0.24602695745157777
  },
  "joint_half_protect": {
    "cagr": -0.4763188297227615,
    "sharpe": -0.8405553187017291,
    "max_drawdown": -0.3232540541185597
  }
}
```

### 2022 window

```json
{
  "full_protect": {
    "cagr": -0.17224552537207405,
    "sharpe": -1.8949924075090776,
    "max_drawdown": -0.18493402811127124
  },
  "half_protect": {
    "cagr": -0.19582177488574581,
    "sharpe": -1.2583892962448862,
    "max_drawdown": -0.21061872579858443
  },
  "joint_half_protect": {
    "cagr": -0.23233607134260115,
    "sharpe": -1.4075165600804236,
    "max_drawdown": -0.24864861430694185
  }
}
```

### Rolling windows

- 3y: half Sharpe ≥ full in `0.8032786885245902` of `61` windows
- 5y: half Sharpe ≥ full in `0.8490566037735849` of `53` windows

## Gate decision

- Label: **`DEFENSIVE_SHADOW_CANDIDATE`** (8/9 checks)

```json
{
  "cagr_above_full": true,
  "sharpe_ge_8020": true,
  "maxdd_target": true,
  "not_only_2008": true,
  "sma_continuity": true,
  "cost_double_stable": true,
  "delay_stable": true,
  "rel_8020_uw_ok": false,
  "rolling_stable": true
}
```

## Final recommendation

- Keep **80% SPY + 20% D+C** as default paper / return candidate.
- Keep **60% SPY + 40% D+C** as conservative shadow.
- Mark **half_protect** as `DEFENSIVE_SHADOW_CANDIDATE` only (not return primary).
- Failed check `rel_8020_uw_ok`: Metric C relative underwater vs 80/20 peak still long (`rel_8020_underwater_trading_sessions=4382.0`, final_rel_nav=`1.048729698321955`); treat as defensive complement, not a replacement.
- **Stop** further spy_qqq_protect exit-ratio / parameter tuning (hypothesis already tested).
- Do **not** purchase Sharadar for this line of work.
- Do **not** change IBKR paper books.

## Erratum — relative underwater days

Prior `rel_8020_underwater_days=4382` used `(1+r_s-r_b).cumprod()` (not Metric C). That approximation ended **below** 1 while true `nav_half/nav_80` ends **above** 1. See `reports/half_protect_relative_audit.md` for the corrected Metric C audit.
