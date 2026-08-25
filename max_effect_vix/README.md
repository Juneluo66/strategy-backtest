# MAX Effect + 历史 S&P500 近似验证

该项目研究美国股票 MAX 异象。默认研究路径使用 Wikipedia 历史 S&P 500 成分变更重建按月股票池，**不是** CRSP/Compustat 完整 PIT。

## 状态标签（硬约束）

```
DATA_TIER: HISTORICAL_SP500_APPROX
SURVIVORSHIP_BIAS: REDUCED_NOT_ELIMINATED
PIT_VALIDATED: false
SIZE_NEUTRAL: BLOCKED_BY_PIT_MARKET_CAP
DELISTING_RETURN: UNAVAILABLE
```

历史成分只能降低“当前成分回填”偏差，不能消除全市场幸存者偏差。禁止把该路径写成偏差已消除或 PIT 已验证。

## 工作流

```bash
cd /home/ec2-user/strategy-backtest/max_effect_vix
python3 -m pip install -e '.[dev]'

max-effect-vix universe-hist
max-effect-vix membership-audit
max-effect-vix fetch --full
max-effect-vix validate-hist
max-effect-vix pit-report
```

也保留 smoke 路径：`fetch --limit 8`、`run --variant raw|vol_neutral|beta_neutral|beta_hedged`、`robustness`、`cost-stress`。

## 执行与退出规则

- 信号：形成日前收盘；成交：下一交易日开盘。
- 只允许当时指数成员进入信号池。
- 指数退出：持仓保留到退出日，随后强制清仓并写 `INDEX_EXIT` 审计；禁止静默删除。
- 无 CRSP delisting return；限制写进报告。
- Size neutral 在无点时市值前保持 BLOCKED；vol/beta 用形成日前价格历史。

## 已知限制

- Wikipedia 变更表不完整。
- Yahoo 价格缺少完整退市样本。
- 无点时市值 → size 维度未验证。
- `quantconnect/main.py` 仅作参考，本阶段不执行。
