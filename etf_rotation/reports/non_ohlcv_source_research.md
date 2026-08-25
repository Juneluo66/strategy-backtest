# v8 非 OHLCV 数据源调研

调研日期：2026-08-04  
范围：`MARGIN_BUY_RATIO`、`MARGIN_CHG_10D`、`SHARE_CHG_5D`、`SHARE_CHG_20D`。  
结论：**当前保持 `BLOCKED_BY_DATA`。** 不将缺失字段替代为 0，也不将低频或无法验证可用时点的数据扩展为日频。

## 原版定义

原版 `non_ohlcv_factors.py` 的原始定义为：

| 因子 | 原始字段 | 计算 |
|---|---|---|
| `MARGIN_CHG_10D` | `rzye`（融资余额） | `(rzye[t] - rzye[t-10]) / abs(rzye[t-10])` |
| `MARGIN_BUY_RATIO` | `rzmre`（融资买入额）及 `close * volume` | `rzmre[t] / (close[t] * volume[t])` |
| `SHARE_CHG_5D` | ETF 总份额 | `(share[t] - share[t-5]) / abs(share[t-5])` |
| `SHARE_CHG_20D` | ETF 总份额 | `(share[t] - share[t-20]) / abs(share[t-20])` |

分母为零或任一输入缺失时应为 `NaN`。原版使用 QMT 本地源；其原始数据未公开分发。

## 候选来源

| 字段 | 候选源 | 频率 / 字段 | PIT 证据与可用时点 | 结论 |
|---|---|---|---|---|
| `rzye`, `rzmre` | **东方财富** `RPTA_WEB_RZRQ_GGMX`（免费） | 按代码日频历史，`RZYE`/`RZMRE` | 盘后入库；研究层 `available_at=下一交易日 08:30` | **已实测**：49 池中 48 只有历史（缺 `159985`）；`fetch-non-ohlcv --source free` 主源 |
| `rzye`, `rzmre` | 上交所明细 AkShare `stock_margin_detail_sse` | 按日全市场明细 | 盘后；需逐日请求 | 可用作交叉校验；深交所端点本机偶发 RST |
| ETF 总份额 | **上交所** AkShare `fund_etf_scale_sse(date)` | 日频，`基金份额`（份） | 按日快照，无机器可读发布时间 → 保守次日 08:30 | **已实测**：沪市 37/37 覆盖；全历史需按交易日循环（可断点续传） |
| ETF 总份额 | **深交所** AkShare `fund_scale_daily_szse` | 日频，`基金份额`（份），单次窗口 ≤6 个月 | 同上保守 PIT | **已实测**：深市 12/12 覆盖 |
| `rzye`, `rzmre` | TuShare `margin_detail` | 日频 | 次日约 08:30；≥2000 积分 | 有 token 时可选 `--source tushare` |
| ETF 总份额 | TuShare `etf_share_size` | 日频，`total_share`（万份）；≥8000 积分 | 次日约 08:30 | 有 token 时可选；禁止用季度规模页替代 |
| ETF 总份额 | 天天基金 / 东方财富规模变动 | 季度或报告期总份额、申购、赎回 | 报告期披露不是每日已知份额；公布日与期末日不同 | 不可用于 5D/20D 日频因子；仅可用于数据质量交叉检查 |
| 两融 | 东方财富融资融券页面 | 页面可查 ETF 类别 | 页面抓取无法保证历史端点版本与发布时间 | 不接入 |

## point-in-time 规则

所有缓存行必须具有：

```text
code, observation_date, available_at, value, source, source_version, retrieved_at
```

- 仅当 `available_at <= signal_date` 时可参加信号。
- 若交易所只提供交易日值而没有公告时间，采用保守规则：`available_at` 为下一个交易所交易日。
- 不得用后续修订值覆盖旧文件；按 `source_version` / `retrieved_at` 保存版本。
- ETF 非两融标的并不代表零融资余额；它是 **缺失**，不参与相应因子的截面。

## 与 QMT 原版的差异

1. QMT 本地桥接源、字段修订处理和文件入库时刻未公开；公开交易所/TuShare 数据不能证明逐行一致。
2. 上交所/深交所标的范围和调入调出历史会影响 `rzye` / `rzmre` 覆盖；不能把不在当日明细中的 ETF 视作零。
3. QMT 的份额数据可能与 TuShare `etf_share_size` 的数据入库时点、单位和修订版本不同。
4. QDII 的份额形成与海外净值时区不同；在 `A_SHARE_ONLY` 下仍不交易，且不应以此绕过 PIT 校验。

## 当前阻塞结论

免费源已实际下载并校验（`free_20260804T110028Z`）：

| 字段 | 行数 | 代码数 | 网格缺失率 |
|---|---:|---:|---:|
| rzye / rzmre | 73,694 | 47 | ~24.1% |
| total_share | 95,956 | 49 | ~4.5% |

因子门控：

| 因子 | missing_ratio | production |
|---|---:|---|
| SHARE_CHG_5D | 4.76% | 通过 |
| SHARE_CHG_20D | 5.46% | 略超 5% 门槛 |
| MARGIN_* | ~24% | 未通过（两融标的稀疏，缺失不填 0） |

结论：raw 已用免费源补齐；**整体仍 `BLOCKED_BY_DATA`**（不降门槛、不填 0）。命令：

```bash
etf-rotation fetch-non-ohlcv --full --source free
```

报告：`reports/non_ohlcv_validation.md`。TuShare 仍可选作交叉校验。
