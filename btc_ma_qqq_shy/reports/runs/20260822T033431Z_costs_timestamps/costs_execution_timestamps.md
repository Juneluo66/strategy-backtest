# Costs, Execution & Timestamp Look-Ahead Audit

## Judgment: `EDGE_SURVIVES_REALISTIC_COSTS_UNDER_LOCAL_ENGINE__STILL_NOT_QC_0_838`

Sample: `2014-11-05` → `2026-08-21`

## Timestamp audit (Sunday BTC candle vs Mon 08:00 ET)

- Weeks: `659`
- Sunday UTC candle complete before Mon 08:00 ET: **`100.0%`**
- Monday UTC bar complete before Mon 08:00 ET: **`0.0%`** (must be ~0%)
- Safe-asof == Sunday proxy: `100.0%`
- Median hours Sunday close → Mon 08:00 ET: `12.0h`
- Look-ahead judgment: **`SUNDAY_UTC_CANDLE_SAFE_AT_MON_08ET__MONDAY_BAR_NOT_VISIBLE`**

Interpretation: Bitfinex Sunday 00:00–Monday 00:00 UTC candle finishes ~12–13h before US equity open / QC 08:00 ET decision. Using that bar is **not** look-ahead. Using the Monday UTC daily bar at Mon 08:00 ET **would** be look-ahead.

## Holidays / week-start mapping

- Week-starts: `659`
- % Monday: `90.3%`
- Non-Monday week-starts (holidays): `64` e.g. `['2014-01-21', '2014-02-18', '2014-05-27', '2014-09-02', '2015-01-20', '2015-02-17', '2015-05-26', '2015-09-08', '2016-01-19', '2016-02-16', '2016-05-31', '2016-07-05']`

## Dividend / SHY–QQQ total return

- SHY CAGR Adj−Close: `1.83` pp
- QQQ CAGR Adj−Close: `0.89` pp
- Strategy research path should use **Adj Close (total return)** for both legs.

## Cost sweep (QC week-start Bitfinex, next-open proxy)

Half-spread assumptions: `{'QQQ': 1.0, 'SHY': 2.0}` (not NBBO).

| One-way bps | +half-spreads | Eff RT bps | Switches | Sharpe | CAGR | Vol | MaxDD |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | False | 0.0 | 134 | 1.290 | 15.44% | 11.69% | -13.35% |
| 0 | True | 3.0 | 134 | 1.260 | 15.05% | 11.69% | -13.40% |
| 1 | False | 2.0 | 134 | 1.270 | 15.18% | 11.69% | -13.38% |
| 1 | True | 5.0 | 134 | 1.240 | 14.79% | 11.70% | -13.44% |
| 2 | False | 4.0 | 134 | 1.250 | 14.92% | 11.70% | -13.42% |
| 2 | True | 7.0 | 134 | 1.221 | 14.53% | 11.70% | -13.47% |
| 5 | False | 10.0 | 134 | 1.191 | 14.14% | 11.70% | -13.52% |
| 5 | True | 13.0 | 134 | 1.161 | 13.75% | 11.71% | -13.58% |
| 10 | False | 20.0 | 134 | 1.091 | 12.84% | 11.73% | -13.70% |
| 10 | True | 23.0 | 134 | 1.062 | 12.46% | 11.74% | -13.78% |

Baseline Adj C2C 0bps Sharpe `1.361` (not open-fill).

## Tradability notes (SHY)

- SHY is highly liquid short-Treasury ETF; 1–2 bps half-spread assumption is conservative for size.
- Main friction is **switch count × (commission + spread + open slippage)**, not SHY borrow.
- 0 bps is not admissible for live claims; quote ≥5 bps one-way (+spreads) as stress.
