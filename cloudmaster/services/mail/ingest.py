"""收件编排（ADR-009 / v2.0.0 P6）：拉取 → 解析入库 → STOP 自动退订。

自 web_app.api_inbox_poll 端点抽离的编排逻辑（去掉 HTTP 层）：路由只做鉴权与
503/502 翻译，本函数对 web 之外的调用方（如定时任务）同样可复用。

隐私红线：正文截断由 parse 侧负责（本模块不再触碰正文长度）；台账只落
storage/inbox 的 9 列白名单（uid / kind / from_addr / subject / date / ticket /
body / stop_requested / fetched_at，ledger.record 收口）。

依赖注入：inbox（fetch_unseen）/ ledger（record 去重入库）/ store
（find_keys_by_email / get / put 回查退订）均为鸭子类型，测试注入 fake
（与 web_app.create_app 同款约定）。stop 命中时**profile 存在且当前
report_opt_in 为 True** 才写回 False 并计入 unsubscribed——已退订用户重复
STOP 不产生写放大，也不虚增退订计数。
"""

from __future__ import annotations

from typing import Any


def poll_inbox(*, inbox: Any, ledger: Any, store: Any) -> dict[str, Any]:
    """拉取新来信：解析入库并处理 STOP 退订。

    InboxError 上抛（由调用方翻译，如路由 → 502）；重复 uid 由 ledger 判重跳过。
    返回 {"fetched", "stored", "unsubscribed", "mails"} 四键。
    """
    mails = inbox.fetch_unseen(limit=20)
    stored: list[dict[str, Any]] = []
    unsubscribed: list[str] = []
    for mail in mails:
        record = mail.to_record()
        outcome = ledger.record(record)
        if not outcome.get("recorded"):
            continue
        stored.append(record)
        # 退订：按发件地址回查匿名标识，置 report_opt_in=False
        if record["stop_requested"] and record["from_addr"]:
            for key in store.find_keys_by_email(record["from_addr"]):
                profile = store.get(key)
                if profile and profile.get("report_opt_in", True):
                    profile["report_opt_in"] = False
                    store.put(key, profile)
                    unsubscribed.append(key)
    return {
        "fetched": len(mails),
        "stored": len(stored),
        "unsubscribed": unsubscribed,
        "mails": stored,
    }
