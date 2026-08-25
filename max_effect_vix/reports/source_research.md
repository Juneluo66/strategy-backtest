# MAX Effect + VIX 来源与复现说明

## 原始公开规则

QuantConnect Research《The MAX Effect with VIX-Based Leverage Scaling》：
<https://www.quantconnect.com/research/20886/the-max-effect-with-vix-based-leverage-scaling/>

- 因子为前 21 个交易日最高 5 个日收益的均值（MAX5）。
- 在满足基本面、价格、市值和流动性过滤的股票中选择 **MAX 最低十分位，且最多 25 只**；不是无条件固定选 25 只。
- VIX 敞口为分段线性函数，而非简单分档：

  `L=1.5`（VIX ≤15）；`L=1.5-(VIX-15)/15*0.5`（15<VIX<30）；`L=1.0`（VIX ≥30）。

- 公开回测为 1998-01 至 2026-06，策略 Sharpe 0.57，SPY Sharpe 0.335。该数值尚未由本机独立验证。

## 学术来源

Bali, T. G., Cakici, N., & Whitelaw, R. F. (2011), *Maxing out: Stocks as
lotteries and the cross-section of expected returns*, Journal of Financial
Economics 99(2), 427–446. DOI: 10.1016/j.jfineco.2010.07.014。

论文发现过去一个月极端正日收益高的股票，后续平均收益较低；MAX5 是比 MAX1 更平滑的实现之一。论文的多空因子证据不等同于此处仅做低 MAX 多头组合的结果。

## 双轨限制

QuantConnect 路径能使用点时基本面、历史退市证券及 CBOE VIX。免费路径只使用 Yahoo Finance 的当前静态股票清单，标记为 `SURVIVORSHIP_BIASED_PILOT`。它只能验证程序逻辑、成本敏感性和 VIX 消融，不能比较或宣称复现公开 Sharpe。
