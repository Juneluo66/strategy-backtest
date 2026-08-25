# OFF Sleeve Tiny Rule (QQQ risk-on frozen)

Rule: `OFF → IEF if IEF>SMA200 else SHY (train-selected tiny rule)`
Judgment: **`OFF_RULE_MIXED`**

## Train (selection allowed)

| Variant | Sharpe | MaxDD | Cum active |
|---|---:|---:|---:|
| SHY fixed | 1.370 | -16.2% | 18.2% |
| IEF trend rule | 1.364 | -14.1% | 17.7% |

Train Sharpe winner: **SHY_fixed**

## Test (locked — no re-selection)

| Variant | Sharpe | MaxDD | Cum active | Pass |
|---|---:|---:|---:|---|
| SHY fixed | 1.342 | -13.3% | 38.8% | ✓ |
| IEF trend rule | 1.273 | -14.5% | 35.1% | ✓ |
