"""Markdown reports with explicit data-quality disclosures."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def render_backtest_report(result: dict[str, object], data_notes: dict[str, object] | None = None) -> str:
    metrics = result["metrics"]
    periods: pd.DataFrame = result["periods"]  # type: ignore[assignment]
    lines = [
        "# 高股息低波质量策略回测",
        "",
        "## 绩效",
        f"- 期间数：{len(periods)}",
        f"- 年化收益：{metrics['annual_return']:.2%}",
        f"- 年化波动：{metrics['annual_volatility']:.2%}",
        f"- Sharpe：{metrics['sharpe']:.2f}",
        f"- 最大回撤：{metrics['max_drawdown']:.2%}",
        f"- 总收益：{metrics['total_return']:.2%}",
        f"- Sortino：{metrics.get('sortino', float('nan')):.2f}",
        f"- Calmar：{metrics.get('calmar', float('nan')):.2f}",
        f"- 月度胜率：{metrics.get('win_rate', float('nan')):.1%}",
        f"- 最佳/最差月：{metrics.get('best_period', float('nan')):.2%} / {metrics.get('worst_period', float('nan')):.2%}",
        "",
        "## 数据与风险提示",
        "- 信号只应使用公告/披露日不晚于信号日的数据；请核对 PIT 审计输出。",
        "- 免费数据仅支持研究级复现：幸存者偏差已通过历史股票池缓解，但未被宣称完全消除。",
        "- 财务历史可能含事后修订；自由流通股、完整委托簿和北交所状态并不完整。",
        "- 收益是本地复现结果，不代表公开版本或未来表现。",
    ]
    if data_notes:
        lines.extend(["", "## 数据质量"])
        lines.extend(f"- {key}: {value}" for key, value in data_notes.items())
    return "\n".join(lines) + "\n"


def save_report(text: str, destination: Path, name: str = "backtest.md") -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / name
    path.write_text(text, encoding="utf-8")
    return path


def render_comparative_report(
    summary: pd.DataFrame, survivorship: pd.DataFrame | None = None
) -> str:
    """Render a compact, explicit research-only multi-variant conclusion."""
    lines = [
        "# 红利低波策略对比研究",
        "",
        "## 研究口径",
        "- 免费数据源、月频 T+1 开盘、成本与可交易性约束均已纳入。",
        "- 2024-07-01 起为锁定样本外；不得据此再次调整参数。",
        "- 本报告是研究级近似复现，不构成实盘建议。",
        "",
        "## 变体结果",
        summary.to_markdown(index=False),
    ]
    if survivorship is not None and not survivorship.empty:
        lines.extend(
            [
                "",
                "## 幸存者覆盖",
                f"- 月度历史股票池数范围：{int(survivorship['historical_codes'].min())}–{int(survivorship['historical_codes'].max())}",
                f"- 历史池中不在当前活股票缓存的代码合计：{int(survivorship['outside_live_cache'].sum())}",
                "- 上述差额已被披露；缺失历史行情或财务的退市代码不会被伪装为已覆盖。",
            ]
        )
    return "\n".join(lines) + "\n"


def render_readiness_report(coverage: pd.DataFrame, summary: dict[str, object]) -> str:
    """Render a factual pre-backtest conclusion when strict PIT inputs are absent."""
    sources = coverage.set_index("source")["files"].to_dict()
    required = ("prices_raw", "prices_adjusted", "dividends", "cashflow", "profit")
    missing = [name for name in required if not sources.get(name, 0)]
    lines = [
        "# 回测数据就绪性结论",
        "",
        f"- 严格 PIT 回测就绪：{'是' if summary['strict_pit_ready'] else '否'}",
        f"- 目标窗口：{summary['recommended_target_start']} 至 {summary['recommended_target_end']}",
        f"- 窗口选择规则：{summary['selection_rule']}",
        "",
        "## 结论",
    ]
    if missing:
        lines.append(f"- 缺失核心来源：{', '.join(missing)}。因此不能计算可信策略收益、Sharpe 或回撤。")
        lines.append("- 不使用当前价格缓存或最新财务快照去伪造完整高股息策略结果。")
    else:
        lines.append("- 数据已具备扫描资格；仍须以每月候选池和 PIT 审计确定最终起止日。")
    return "\n".join(lines) + "\n"
