# A股高股息低波质量策略

本策略以“已公开、已实施”的普通现金分红构建股息率，再以低波动、连续分红、自由现金流和盈利稳定性过滤。支持纯股息、股息低波、股息质量和行业约束四种消融变体，以及等权与逆波动率加权。

## 关键口径

- 信号日仅使用公告/披露日不晚于该日的数据；禁止把最新财务快照回填历史。
- 选股使用“最新已完整披露方案年度”的普通每股现金分红 ÷ 信号日未复权收盘价。
- 同时输出公告日 TTM 股息率作为诊断字段，但不直接用于选股。
- 特别/中期分红、未实施分红和无法确认时点的记录被写入审计结果，不会静默混入信号。
- 组合收益用前复权价计算；信号成交为信号日后的下一交易日开盘，并计入佣金和滑点。
- BaoStock 月度历史股票池用于缓解“只使用今天仍上市股票”的幸存者偏差；退市股覆盖率会单独审计，不宣称完全无偏。
- 财务可能包含事后修订，行业历史、自由流通股、完整涨跌停委托簿仍有免费数据源缺口。

公开的年化收益、Sharpe 和回撤只能作为待复现基准；本项目不会把它们写成预期结果。

## 安装

```bash
cd /home/ec2-user/strategy-backtest/dividend_lowvol_quality
python3 -m pip install -e '.[dev]'
```

## 使用

先用少量股票验证数据接口与缓存：

```bash
dividend-lowvol fetch --limit 5
```

所有长任务默认仅处理小样本，单进程 RSS 硬上限为 512MB。全市场运行必须显式传 `--full`，建议降低 CPU/IO 优先级：

```bash
nice -n 19 ionice -c3 dividend-lowvol build-universe --full
```

先构建两个月的历史股票池冒烟：

```bash
dividend-lowvol build-universe --start 2019-01-01 --end 2019-03-01
```

快照分片建好后，使用预设 A–E 串行排名；每次只运行一个命令并落盘后再运行下一项：

```bash
dividend-lowvol rank-snapshot-parts --parts-dir data/pit_snapshots_parts --preset A --output data/holdings_A.parquet
dividend-lowvol rank-snapshot-parts --parts-dir data/pit_snapshots_parts --preset E --output data/holdings_E.parquet
dividend-lowvol compare-variants \
  --holdings A=data/holdings_A.parquet --holdings E=data/holdings_E.parquet \
  --oos-start 2024-07-01 --survivorship-audit data/universes/survivorship_audit.csv
```

分红审计需要事件和价格 Parquet 文件：

```bash
dividend-lowvol audit-dividends \
  --events data/cache/dividends/600519.parquet \
  --prices data/cache/prices/600519_raw.parquet \
  --code 600519 --as-of 2025-01-02
```

回测入口接收已经按公告/披露日构建好的月度 PIT 快照：

```bash
dividend-lowvol backtest \
  --snapshots data/pit_snapshots.parquet \
  --prices data/prices.parquet
```

`fetch` 的全 A 首次运行会很慢。免费数据仍可能有历史披露日缺失、财务修订和上游接口变动；先审计 PIT 事件、退市覆盖和执行失败，再解读回测结果。
