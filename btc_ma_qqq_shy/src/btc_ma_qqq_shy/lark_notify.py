"""Lark / Feishu bot webhook notifier (no IBKR)."""
from __future__ import annotations

import hashlib
import base64
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional


def load_lark_env(project_root) -> dict[str, str]:
    """Load webhook from project .env or parent strategy-backtest/.env."""
    from pathlib import Path

    root = Path(project_root)
    candidates = [root / ".env", root.parent / ".env"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            from dotenv import load_dotenv

            load_dotenv(path, override=False)
        except ImportError:
            pass
    return {
        "webhook": (
            os.environ.get("lark_webhook_url")
            or os.environ.get("LARK_WEBHOOK_URL")
            or ""
        ).strip(),
        "secret": (
            os.environ.get("lark_signing_secret")
            or os.environ.get("LARK_SIGNING_SECRET")
            or ""
        ).strip(),
    }


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def send_lark_text(
    webhook: str,
    text: str,
    *,
    secret: str = "",
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    if not webhook:
        raise RuntimeError("lark_webhook_url not set in .env")

    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(secret, ts)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            return {"http_status": resp.status, "body": parsed}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Lark HTTP {exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Lark request failed: {exc}") from exc


def format_weekly_notify_text(payload: dict[str, Any]) -> str:
    sig = payload["signal"]
    capital = payload.get("capital_summary") or {}
    lines = [
        "【v1 周提示 · 不登录 IBKR】",
        f"时间(北京): {payload.get('now_beijing', '')}",
        f"周次: {sig.get('week_id')}",
        "",
        f"👉 本周应买: {sig.get('target')}  (signal={sig.get('signal')})",
        f"规则: {sig.get('rule_id')}",
        f"BTC收盘: {sig.get('btc_close')}  SMA50: {sig.get('sma50')}  MOM20: {sig.get('mom20')}",
        "",
        "—— 资金池摘要 ——",
    ]
    if not capital.get("pool_initialized"):
        lines.append("资金池未锁定（本地记录）。")
    else:
        lines.append(f"锁定本金: ${capital.get('capital_basis', 0):,.2f}")
        lines.append(f"最新池NAV: ${capital.get('latest_pool_nav', 0):,.2f}")
        ret = capital.get("return_since_start")
        if ret is not None:
            lines.append(f"累计收益: {100 * float(ret):.2f}%")
        wr = capital.get("last_weekly_return")
        if wr is not None and wr != "":
            lines.append(f"上周周收益: {100 * float(wr):.2f}%")
        lines.append(
            f"持仓: QQQ={capital.get('qqq_shares', 0)}  "
            f"SHY={capital.get('shy_shares', 0)}  "
            f"现金=${capital.get('strategy_cash', 0):,.2f}"
        )
        if capital.get("shy_shares", 0) and capital.get("shy_cost_basis_per_share"):
            lines.append(
                f"SHY成本价(含费): ${float(capital['shy_cost_basis_per_share']):,.4f}/股"
            )
        if capital.get("qqq_shares", 0) and capital.get("qqq_cost_basis_per_share"):
            lines.append(
                f"QQQ成本价(含费): ${float(capital['qqq_cost_basis_per_share']):,.4f}/股"
            )
        if capital.get("fees_paid_total"):
            lines.append(f"累计手续费: ${float(capital['fees_paid_total']):,.4f}")
        if capital.get("last_week_id"):
            lines.append(
                f"上笔记账: week={capital.get('last_week_id')}  "
                f"note={capital.get('last_order_note', '')}"
            )
    lines += [
        "",
        "说明: 仅通知，不会自动登录/下单。请自行在 IBKR 按提示操作。",
        "整股提醒: API/自动化不支持碎股；SHY≈$82+ 才够买 1 股。",
    ]
    return "\n".join(lines)
