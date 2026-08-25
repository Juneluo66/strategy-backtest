# A 股 ETF 轮动策略研究级复现

本项目复现公开 `zhangsensen/etf-rotation-strategy` v8.0 的研究框架：49 只 ETF
截面打分、5 个交易日调仓、Top-2、Exp4 迟滞、510300 波动率门控，以及浮点
向量化和整手事件驱动两层核对。它是免费数据下的研究级近似，不是 QMT 数据的
精确复刻，也不构成投资建议。

## 已冻结的生产参考

- `FREQ=5`、`POS_SIZE=2`、每次最多替换 1 只
- `delta_rank=0.10`、最短持有 9 个交易日
- 510300 的 20 日波动率百分位门控：100% / 70% / 40% / 10%
- A 股 ETF 单边成本 2bp；T 日收盘信号、T+1 开盘执行
- 默认只交易 41 只 A 股 ETF；8 只 QDII 标记但不交易

`configs/frozen_v8.yaml` 是唯一的冻结参考。默认入口拒绝改动核心参数；研究
参数扫描必须显式传 `--allow-unfrozen`，且不能用 OOS 选择参数。

## 安装

```bash
cd /home/ec2-user/strategy-backtest/etf_rotation
python3 -m pip install -e '.[dev]'
```

## 工作流

默认仅缓存 8 只 ETF，单进程并在每个代码后检查 RSS。完整 49 池必须显式 `--full`：

```bash
etf-rotation fetch --limit 8
etf-rotation audit
etf-rotation run --variants M1,H1,R1

# 全池（建议低优先级运行）
nice -n 19 ionice -c3 etf-rotation fetch --full
etf-rotation audit
etf-rotation run --variants M1,H1,R1,C4,C1
etf-rotation robustness --variant R1
```

输出写入 `reports/`。`summary.md` 包含 VEC−EVT 差异；超过 5 个百分点时不能将
结果视为可发布结论，必须先审计信号、执行或成本假设。

## Variant definitions

All variants are predeclared research ablations; none are selected using OOS results.

| Variant | Definition | v8 status |
|---|---|---|
| `M1` | `MOM_20D`, Top-2, no hysteresis or regime gate | Price-only baseline, not v8 |
| `H1` | M1 plus 5-day schedule, `delta_rank=0.10`, 9-day minimum holding, and one replacement | Execution ablation |
| `R1` | H1 plus the frozen 510300 volatility gate | Risk-control ablation |
| `v8_reference` | Frozen `composite_1` declaration and execution settings | Partial unless all margin/share fields are supplied |
| `C4` | Frozen `core_4f` declaration and execution settings | Partial unless all margin/share fields are supplied |

Every invocation writes an immutable `reports/runs/<run_id>/` directory with its frozen
configuration snapshot, SHA-256 hash, metadata, and result artifacts. Use
`compare-engines`, `ablation`, `multiple-testing`, `fresh-oos`, and `cost-capacity`
for the corresponding validation stages.

## 数据与已知限制

- 日频 OHLCV/成交额来自 AkShare/东方财富，按代码缓存为 Parquet。
- ETF 首个缓存交易日是上市可用日的保守代理；候选至少需 252 个历史 bars。
- `MARGIN_*` / `SHARE_CHG_*`：`factor_panel` 会按 PIT 合并 production 或
  research staging（默认不填 0）。运行模式：`--mode baseline|research|strict`。
  份额因子在排除上市前与合法预热后可单独升 production；两融不缩小分母。
  C1/C4 在 research 下若用 staging 必标 `PARTIAL_REPRODUCTION`，不得称为完整 v8 复现。
  对比：`etf-rotation factor-wiring-compare`。
- QDII 时区、复权、停牌、涨跌停订单簿、真实 bid/ask 与冲击成本均未被完整复现。
- 样本内截止 2025-04-30，2025-05-01 起为冻结的样本外窗口。
