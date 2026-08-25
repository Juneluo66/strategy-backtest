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
| `rzye`, `rzmre` | 上交所融资融券明细，经 AkShare `stock_margin_detail_sse(date)` | 日频，含标的代码、融资余额、融资买入额、融资偿还额 | 上交所明确为券商申报汇总；盘后形成。研究层保守取 `available_at = trade_date` 后一个交易所交易日开盘前 | 可作为沪市 ETF 的候选原始源，须逐日缓存、记录请求日及 `available_at` |
| `rzye`, `rzmre` | 深交所融资融券明细，经 AkShare `stock_margin_detail_szse(date)` | 日频明细 | 同为盘后交易所数据；接口可用性需要逐日期验证 | 可作为深市 ETF 的候选原始源，须与上交所同一 PIT 规则 |
| `rzye`, `rzmre` | TuShare `margin_detail` | 日频、证券级，字段 `rzye`、`rzmre` | 文档说明交易所于下一日约 08:30 更新上一日；需要至少 2000 积分 | 可靠备选，但当前环境无 `TUSHARE_TOKEN`，未接入 |
| ETF 总份额 | TuShare `etf_share_size` / `fund_share` | 日频，`total_share` 或 `fd_share` | `etf_share_size` 文档说明交易所于次日约 08:30 更新前一日；需要 800 积分（`fund_share` 需要 2000） | 理想日频源，但当前环境无 token；缺少 token 前不得回填 |
| ETF 总份额 | 上交所 ETF 规模披露，经 AkShare `fund_etf_scale_sse(date)` | 按日期基金份额 | 历史端点有覆盖/返回完整性不确定，且未提供机器可读发布时间 | 仅作交叉审计候选，不作为生产因子源 |
| ETF 总份额 | 深交所 ETF 规模披露，经 AkShare `fund_scale_daily_szse` | 日频规模/份额 | 端点在本机探测发生连接重置；未验证历史完整性和发布时间 | 不接入 |
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

当前可验证的是两融原始日明细来源，不是完整四因子生产数据：

- 没有配置 TuShare token，无法取得并验证全历史 ETF 日份额。
- 上交所/深交所公开份额端点在覆盖、历史连续性和发布时间上未达到接入标准。
- 因此四个因子仍为 `partial_unavailable`，C1/C4 仍不得标为完整复现。

下一步只有在获得具有历史日份额、明确更新时间和授权的 TuShare/QMT 数据后才允许启动下载；下载后须先跑 PIT、覆盖率、单位和前视测试，再改变 partial 状态。
