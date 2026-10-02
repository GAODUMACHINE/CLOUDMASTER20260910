"""保留期到期清除执行器（v2.0.0 P7，ADR-011 §6）：jobs.run_purge。

修「到期假删除」：旧版 PrivacyStore.purge_schedule 只**计算**到期时间、从不执行
删除，保留期承诺形同虚设。本执行器扫描全部已落库保留期键，对到期者执行四件套：

1) 图 thread 删除（checkpointer.delete_thread，尽力而为）；
2) 画像删除（profiles.delete，reason=retention_purge，落 data_deleted 审计）；
3) 保留期记录清除（privacy.forget）；
4) 报告草稿与发送台账清除（reports.delete_for_profile）。

隐私红线：删除范围 = 会话数据（thread / 画像 / 保留期记录 / 报告台账）；
**申诉台账不参与**——申诉是运营数据、有独立处理期（《办法》第 21 条），且其中不含
可指向个体的会话内容；audit_events 本身 append-only 不可删（这正是它能证明
「删除确实发生过」的原因）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _delete_thread(graph: Any, thread_id: str) -> bool:
    """尽力而为删除图 thread（与 web/deps._delete_thread 同款容错；jobs 不依赖 web 层）。"""
    fn = getattr(getattr(graph, "checkpointer", None), "delete_thread", None)
    if fn is None:
        return False
    try:
        fn(thread_id)
    except Exception:  # noqa: BLE001 -- 清除流程不因单个 thread 失败中断
        return False
    return True


def _thread_has_data(graph: Any, thread_id: str) -> bool:
    """thread 是否还有可删数据（state 读得到且 values 非空）。"""
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return bool(snap.values)
    except Exception:  # noqa: BLE001 -- 无 thread / 读失败均视为无数据
        return False


def run_purge(
    *, graph: Any, profiles: Any, privacy: Any, reports: Any, now: datetime | None = None
) -> dict[str, Any]:
    """执行一轮到期清除（幂等；单键失败不中断整体）。

    返回 {"scanned", "purged", "failed"}：scanned=扫描的保留期键数，purged=完成
    四件套删除的键，failed=中途失败计入的键（键已到期且确有数据才会进入这两类）。
    每轮结束经 privacy.log_purge 落一条 purge_executed 汇总审计。
    """
    moment = now if now is not None else datetime.now(UTC)
    keys = privacy.all_keys()
    purged: list[str] = []
    failed: list[str] = []
    for key in keys:
        try:
            schedule = privacy.purge_schedule(key, now=moment)
            if not schedule.get("expired"):
                continue
            # 键到期但画像与 thread 均已无数据（如用户此前手动删除）→ 只清保留期记录。
            if profiles.has(key) or _thread_has_data(graph, key):
                _delete_thread(graph, key)
                profiles.delete(key, reason="retention_purge")
                reports.delete_for_profile(key)
                privacy.forget(key)
            else:
                privacy.forget(key)
            purged.append(key)
        except Exception:  # noqa: BLE001 -- 单键失败计入 failed，继续处理其余键
            failed.append(key)
    if purged or failed:
        # 只在有实际动作时落汇总审计（空转不产生噪声事件）。
        privacy.log_purge(purged)
    return {"scanned": len(keys), "purged": purged, "failed": failed}
