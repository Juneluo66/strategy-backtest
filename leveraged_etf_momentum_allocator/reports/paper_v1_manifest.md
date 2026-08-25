# PAPER_V1 Manifest (immutable)

> **Status:** FROZEN

## Identity

- strategy_version: `PAPER_V1`
- base_tree: `ABLATION_DROP_SPY_RSI`
- frozen_date: `2026-08-24`
- classification: `PAPER_TRADING_CANDIDATE`
- allow_parameter_changes: `False`
- allow_tree_changes: `False`
- allow_universe_changes: `False`

## Hashes

- `paper_config_sha256`: `136df27b900bd57534cb8fa49c2ef008420e91ef21a587b3875f76b60ec9c5ad`
- `strategy_logic_sha256`: `7525a334580aff24b318167fb9276f5059d07fd7dfbfc63600f336c6eb6cce95`
- `asset_mapping_sha256`: `a385c6b9386d573a460d6f398fd2242ef48f7682a14f762dc0875c194cd404d1`
- `composite_sha256`: `3c869428b5c4557b670c871dae796645728229b1ddce410ef3d3dccc53ec9b54`

## Signal Parameters

- RSI period: 10
- SPY SMA: 200
- QQQ SMA: 20
- TQQQ SMA: 20
- thresholds: `{'qqq_rsi_overbought': 80, 'spy_rsi_overbought': 80, 'tqqq_rsi_oversold': 30, 'spy_rsi_oversold': 30, 'uvxy_high': 70, 'uvxy_extreme': 80, 'sqqq_rsi_branch_1': 30, 'sqqq_rsi_branch_2': 30}`
- ablations: `{'drop_spy_rsi': True, 'drop_sqqq_rsi': False, 'drop_uvxy_rsi': False, 'drop_qqq_sma': False, 'drop_tqqq_sma': False, 'drop_qqq_rsi': False, 'prune_branches': []}`

## Exposure

- definition: `underlying_equity_beta`
- target_underlying_beta: **1.5**
- 3x ETF target weight: **0.5**
- defensive sleeve: `BSV` @ 0.5
- UVXY max weight: **0.25** (`PAPER_EXECUTION_OVERLAY`)

## Position Construction Examples

- TQQQ: weights={'TQQQ': 0.5, 'BSV': 0.5} implied_beta=1.5 overlay=None
- TECL: weights={'TECL': 0.5, 'BSV': 0.5} implied_beta=1.5 overlay=None
- TECS: weights={'TECS': 0.5, 'BSV': 0.5} implied_beta=-1.5 overlay=None
- SPXL: weights={'SPXL': 0.5, 'BSV': 0.5} implied_beta=1.5 overlay=None
- BSV: weights={'BSV': 1.0} implied_beta=0.0 overlay=None
- UVXY: weights={'UVXY': 0.25, 'BSV': 0.75} implied_beta=None overlay=PAPER_EXECUTION_OVERLAY

## Execution

- signal: `daily_close`
- fill: `next_market_open`
- same_close_fill: `False`
- base cost: `5 bps`

## Versioning Policy

PAPER_V1 is immutable. Any logic/config/universe change requires PAPER_Vn with a new frozen_date and independent forward clock. Never rewrite logs.

## Init Timestamp (local)

2026-08-25
