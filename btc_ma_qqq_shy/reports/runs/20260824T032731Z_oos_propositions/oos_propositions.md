# OOS Proposition Tracker

OOS cutoff: `2026-08-07` | Frozen w_QQQ: `0.56`
Ledger: `/home/ec2-user/strategy-backtest/btc_ma_qqq_shy/reports/frozen_oos_ledger.csv` (1 rows)

Three propositions to watch as OOS accumulates:

1. **Risk-on exposure value** — BTC=ON: QQQ beats SHY?
2. **Risk-off downside** — BTC=OFF: QQQ higher vol / worse tails?
3. **Active vs vol-matched static** — cumulative active return > 0?

## `discovery_pre_cutoff` (n=613, status=TRACKING)

| Prop | Metric | Value | Pass? |
|---|---|---|---|
| ① ON spread (QQQ−SHY) | mean when ON | 0.619% | ✓ |
| ① | win rate QQQ>SHY when ON | 61.5% | |
| ② | QQQ week vol OFF vs ON | 3.04% vs 2.41% | ✓ |
| ② | QQQ neg week frac OFF vs ON | 44.9% vs 38.5% | |
| ② | QQQ 10% tail OFF vs ON | -3.71% vs -2.27% | |
| ③ | cum active vs static | 71.181% | ✓ |
| ③ | mean weekly active | 0.098% | |

## `frozen_oos_ledger` (n=1, status=INSUFFICIENT_OOS)

| Prop | Metric | Value | Pass? |
|---|---|---|---|
| ① ON spread (QQQ−SHY) | mean when ON | nan% | ✗ |
| ① | win rate QQQ>SHY when ON | nan% | |
| ② | QQQ week vol OFF vs ON | nan% vs nan% | ✗ |
| ② | QQQ neg week frac OFF vs ON | 0.0% vs nan% | |
| ② | QQQ 10% tail OFF vs ON | nan% vs nan% | |
| ③ | cum active vs static | -0.698% | ✗ |
| ③ | mean weekly active | -0.698% | |

## `combo_discovery` (n=613, status=TRACKING)

| Prop | Metric | Value | Pass? |
|---|---|---|---|
| ① ON spread (QQQ−SHY) | mean when ON | 0.143% | ✓ |
| ① | win rate QQQ>SHY when ON | 57.2% | |
| ② | QQQ week vol OFF vs ON | 3.61% vs 2.21% | ✗ |
| ② | QQQ neg week frac OFF vs ON | 40.8% vs 42.5% | |
| ② | QQQ 10% tail OFF vs ON | -3.78% vs -2.63% | |
| ③ | cum active vs static | -48.513% | ✗ |
| ③ | mean weekly active | -0.098% | |

## `combo_oos_weeks` (n=1, status=INSUFFICIENT_OOS)

| Prop | Metric | Value | Pass? |
|---|---|---|---|
| ① ON spread (QQQ−SHY) | mean when ON | 1.014% | ✓ |
| ① | win rate QQQ>SHY when ON | 100.0% | |
| ② | QQQ week vol OFF vs ON | nan% vs nan% | ✗ |
| ② | QQQ neg week frac OFF vs ON | nan% vs 0.0% | |
| ② | QQQ 10% tail OFF vs ON | nan% vs nan% | |
| ③ | cum active vs static | 0.446% | ✓ |
| ③ | mean weekly active | 0.446% | |
