"""到期回访交付执行器：run_due。

执行器语义 = 「到期交付」：把 pending 回访翻成 done（审核台待办区可见条目）。
回访本身是线下人工动作，系统职责是可见性而非执行——不代打电话、不催办、
不向用户发消息。保持纯函数，队列由调用方构造传入。
"""

from __future__ import annotations

from typing import Any


def run_due(*, queue: Any, now: str | None = None) -> dict[str, Any]:
    """交付全部到期回访（pending→done；幂等，重跑安全）。

    返回 {"due", "delivered", "failed"}：due=本轮到期条数，delivered=成功标记的
    条目 dict 列表（含 id/ticket_id/scheduled_at/kind），failed=标记失败的 id 列表
    （单条失败不中断整体）。
    """
    due_items = queue.due(now=now)
    delivered: list[dict[str, Any]] = []
    failed: list[int] = []
    for item in due_items:
        try:
            done = queue.mark_done(item["id"])
        except Exception:  # noqa: BLE001 -- 单条失败不中断整体交付
            failed.append(item["id"])
            continue
        if done is None:
            # 已被并发标记（或非 pending）：幂等语义下不算失败。
            continue
        delivered.append(done)
    return {"due": len(due_items), "delivered": delivered, "failed": failed}
