# Risk Prediction — BTC vs VIX / RV / Trend

## Judgment: `BTC_MARGINAL_OOS_RISK_INCREMENT`

Discovery window: `2014-11-05` → `2026-08-07` (OOS cutoff)

## P(QQQ 20d max DD ≤ −5%) — expanding OOS

| Spec | AUC | Brier | LogLoss | n |
|---|---:|---:|---:|---:|
| btc_only | 0.563 | 0.2378 | 0.674 | 2198 |
| vix_only | 0.589 | 0.2394 | 0.684 | 2198 |
| rv_only | 0.605 | 0.2344 | 0.666 | 2198 |
| vix_rv | 0.600 | 0.2390 | 0.684 | 2198 |
| vix_rv_trends | 0.592 | 0.2394 | 0.688 | 2198 |
| full_plus_btc | 0.606 | 0.2354 | 0.678 | 2198 |

- ΔAUC (full+BTC − VIX+RV+trends): `0.013622686175522647`
- ΔAUC (full+BTC − VIX only): `0.016453912466843468`

## Continuous forward risk R² (discovery IS, HAC)

| Target | Spec | R² | t_BTC |
|---|---|---:|---:|
| rv5 | btc_only | 0.04211455850535262 | -3.9566575969996114 |
| rv5 | vix_only | 0.44253221722138947 | None |
| rv5 | rv_only | 0.3033832607254229 | None |
| rv5 | vix_rv | 0.4450890809979129 | None |
| rv5 | vix_rv_trends | 0.4646838573554951 | None |
| rv5 | full_plus_btc | 0.46802751656422237 | -2.400013833346038 |
| rv20 | btc_only | 0.03957405150726512 | -3.6217408794679313 |
| rv20 | vix_only | 0.34073929797105484 | None |
| rv20 | rv_only | 0.26483325078425135 | None |
| rv20 | vix_rv | 0.34955327954828586 | None |
| rv20 | vix_rv_trends | 0.357550732986072 | None |
| rv20 | full_plus_btc | 0.3626361969325169 | -1.9724291718720885 |
| dvol20 | btc_only | 0.03437969023005438 | -3.5030845403532815 |
| dvol20 | vix_only | 0.20146316743964843 | None |
| dvol20 | rv_only | 0.1446850083082324 | None |
| dvol20 | vix_rv | 0.20373183399699757 | None |
| dvol20 | vix_rv_trends | 0.20617127448214279 | None |
| dvol20 | full_plus_btc | 0.21506566273041416 | -2.3002510386781228 |

If BTC does not improve OOS drawdown classification after VIX+RV+trends, treat the trading rule as an empirical gate — not a validated risk forecaster.
