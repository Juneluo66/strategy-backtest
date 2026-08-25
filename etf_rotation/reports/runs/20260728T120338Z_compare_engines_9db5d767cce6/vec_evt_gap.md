# VEC vs EVT daily reconciliation

The first divergence is a candidate for execution audit. Likely categories are integer lots, residual cash, open-vs-close timing, fees, or unavailable/failed fills; classify only after inspecting trade logs.

## First divergence

| date                |   vec_return |   vec_exposure |   turnover |   vec_nav |   evt_value |   evt_cash |   holdings |   evt_return |   evt_nav |   nav_difference |   return_difference |
|:--------------------|-------------:|---------------:|-----------:|----------:|------------:|-----------:|-----------:|-------------:|----------:|-----------------:|--------------------:|
| 2012-06-14 00:00:00 |  -0.00580852 |              1 |          1 |  0.994191 |      996428 |     2.0404 |     510050 |  -0.00357196 |  0.996428 |      -0.00223657 |         -0.00223657 |

The VEC engine uses float weights; EVT uses 100-share lots and cash. Any unfilled or partial order must be recorded in EVT trades, not converted to zero-return fills.
