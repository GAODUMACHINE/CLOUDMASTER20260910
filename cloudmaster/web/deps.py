"""Web 层公共依赖与图辅助（v2.0.0 P3，ADR-011 §1/§2）。

- AppContext：create_app 装配的全部协作对象（图 / 存储 / 邮件 / 台账 / 令牌 / 盐），
  经 app.state.ctx 注入、get_ctx 取用——路由函数不再闭包捕获单文件局部变量，
  这是 web_app.py 660 行单文件能按域拆成 8 个 router 的前提。
- Bearer 鉴权（ADR-011 §2 / ADR-007）：对话侧匿名 ID 即凭证（Authorization:
  Bearer <profile_key>，缺失 401）；审核侧 Bearer <CM_REVIEWER_TOKEN>（未配置或
  不匹配一律 403，不区分「未开通」与「令牌错误」，防探测链路是否启用；令牌不进 URL，
  URL 会进代理/访问日志）。
- 挂起检查（_awaiting_human_review 等）与危机升级开案（open_escalation）统一收口到
  本模块（功能对照表 #4：crisis 挂起语义单点化）——/api/chat 与 /api/chat/stream 必须
  共用同一份实现；旧 stream 端点各自漏掉挂起检查，正是 L2 可被流式端点绕过的根因。

红线：本模块不触网、不落盘；HTTPException 的中文文案即对外契约（测试锚定），改文案须同步测试。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

# L2 中断态下对用户的占位文案。
# 背景：`interrupt_before=["human_review"]` 在 human_review **之前**中断，此刻 state 里只有用户那条
# HumanMessage，若仍取 msgs[-1] 会把用户自己的话当成"AI 回复"回显。中断期间自动回复本就应该暂停，
# 故统一返回该占位文案（不含任何热线号码，仅给就地安全提示）。
REVIEW_HOLD_REPLY = (
    "你的表达可能涉及较高的风险。为保障你的安全，本轮自动回复已暂停，已转交人工审核台跟进。"
    "请先与信任的人、监护人或身边可信任的成年人待在一起；"
    "如有立即的危险，请立即拨打当地急救电话或前往就近医院急诊。"
)


@dataclass
class AppContext:
    """应用级依赖容器：路由经 get_ctx 取用，测试替换时只改这里、不动路由签名。

    除 reviewer_token / report_salt 外全部 Any——协作者由 storage/services 层供给，
    web 层只按鸭子类型调用（既有 246 例测试注入的 fake 同样满足）。
    inbox / agreements / followups 允许为 None（通道未配置 / 队列未启用），调用方须容错。
    """

    graph: Any
    store: Any
    mailer: Any
    review_ledger: Any
    privacy_store: Any
    resource_store: Any
    appeal_store: Any
    inbox_ledger: Any
    report_registry: Any
    inbox: Any = None
    reviewer_token: str = ""
    report_salt: str = ""
    agreements: Any = None
    followups: Any = None


def get_ctx(request: Request) -> AppContext:
    """从 app.state 取依赖容器（create_app 装配时写入）。"""
    return request.app.state.ctx


def _bearer(request: Request) -> str | None:
    """解析 Authorization: Bearer 凭证（scheme 大小写不敏感；缺失/畸形返回 None）。"""
    raw = request.headers.get("Authorization") or ""
    scheme, _, value = raw.partition(" ")
    token = value.strip()
    if scheme.strip().lower() != "bearer" or not token:
        return None
    return token


def require_profile(request: Request) -> str:
    """对话侧鉴权：Bearer 即匿名 ID（ADR-007），缺失/为空一律 401。"""
    token = _bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="缺少 Bearer 凭证（匿名 ID）")
    return token


def require_reviewer(request: Request, ctx: Annotated[AppContext, Depends(get_ctx)]) -> None:
    """审核台鉴权：Bearer 令牌与 CM_REVIEWER_TOKEN 常数时间比较。

    未配置令牌 / 缺凭证 / 不匹配一律同一 403 文案——不泄露「链路是否启用」这一信息本身。
    """
    token = _bearer(request)
    if not ctx.reviewer_token or not token or not secrets.compare_digest(token, ctx.reviewer_token):
        raise HTTPException(status_code=403, detail="审核台未授权")


def _reply_of(msgs: list[Any]) -> str:
    """取最后一条 AI 消息作为回复；无 AI 消息返回空串。

    v2.0.0 P2 回显守卫：裸取 msgs[-1] 在「图结束时最后一条是用户消息」的路径上
    （如防死循环强制 end）会把用户自己的话回显成 AI 回复；倒序找最近一条 AI 消息即可。
    time_guard 的非阻断提示也是 AI 消息：若其后无疏导回复（收尾短路），该提示本身
    就是当轮回复——语义正确。
    """
    for m in reversed(msgs):
        if getattr(m, "type", "") == "ai":
            return str(m.content)
    return ""


def _delete_thread(graph: Any, thread_id: str) -> bool:
    fn = getattr(getattr(graph, "checkpointer", None), "delete_thread", None)
    if fn is None:
        return False
    try:
        fn(thread_id)
    except Exception:  # noqa: BLE001 -- 用户退出优先
        return False
    return True


def _thread_messages(graph: Any, thread_id: str) -> list[Any]:
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return list((snap.values or {}).get("messages") or [])
    except Exception:  # noqa: BLE001 -- 导出/报告尽力而为
        return []


def _thread_state(graph: Any, thread_id: str) -> dict[str, Any]:
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return dict(snap.values or {})
    except Exception:  # noqa: BLE001
        return {}


def _last_user_text(messages: list[Any]) -> str:
    for m in reversed(messages):
        if getattr(m, "type", "") == "human":
            return str(getattr(m, "content", ""))
    return ""


def _context_summary(messages: list[Any], limit: int = 200) -> str:
    return _last_user_text(messages)[:limit]


def _context_for_review(messages: list[Any], limit: int = 6) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages[-limit:]:
        role = "user" if getattr(m, "type", "") == "human" else "ai"
        out.append({"role": role, "text": str(getattr(m, "content", ""))[:300]})
    return out


def _thread_next(graph: Any, thread_id: str) -> tuple[str, ...]:
    """该 thread 的下一步待执行节点；异常/无 thread 时返回空元组。"""
    try:
        snap = graph.get_state({"configurable": {"thread_id": thread_id}})
        return tuple(snap.next or ())
    except Exception:  # noqa: BLE001 -- 判定中断态尽力而为
        return ()


def _awaiting_human_review(graph: Any, thread_id: str) -> bool:
    """thread 是否停在 human_review 中断点（L2 待审、自动回复已暂停）。"""
    return "human_review" in _thread_next(graph, thread_id)


def _append_user_message(graph: Any, thread_id: str, text: str) -> bool:
    """把用户消息追加进 state（供审核台查看），但不推进图。"""
    from langchain_core.messages import HumanMessage

    try:
        graph.update_state({"configurable": {"thread_id": thread_id}}, {"messages": [HumanMessage(text)]})
    except Exception:  # noqa: BLE001 -- 留痕尽力而为，不阻断挂起态返回
        return False
    return True


def chat_payload(
    ctx: AppContext, profile_key: str, res: dict[str, Any], held: bool, escalation: dict[str, Any] | None
) -> dict[str, Any]:
    """组装 /api/chat 响应体（SSE 的 done 事件复用同一形态）。

    reply 取「held → 占位文案，否则最近一条 AI 消息」：L2 停在 human_review 中断点时
    state 里没有 AI 消息，裸取 msgs[-1] 会把用户自己的话当"AI 回复"回显（前端会把用户
    那条消息再显示一遍）。notices 为当轮非阻断通知（time_guard 的披露/提醒，P2 起随
    响应下发）：新增键不进旧键集，既有测试的子集断言不破。
    """
    basis = res.get("crisis_basis") or {}
    reply = REVIEW_HOLD_REPLY if held else _reply_of(res.get("messages") or [])
    return {
        "reply": reply,
        "risk_level": res.get("risk_level"),
        "next_agent": res.get("next_agent"),
        "review_decision": res.get("review_decision"),
        "basis_reason": basis.get("reason"),
        "escalation": escalation,
        "held_for_review": held,
        "notices": res.get("turn_notices") or [],
    }


def open_escalation(ctx: AppContext, profile_key: str, res: dict[str, Any]) -> dict[str, Any] | None:
    """risk=high 时登记待审案件（source 缺省 chat）；其余返回 None。

    台账保证同一 thread 未决唯一（不重复登记、返回既有案件），故两个端点（chat /
    chat.stream）抢开案是安全的。摘要只取最近一条用户消息的前 200 字——台账不落对话
    原文（红线）。
    """
    basis = res.get("crisis_basis") or {}
    if res.get("risk_level") != "high":
        return None
    return ctx.review_ledger.open_case(
        thread_id=profile_key,
        risk_level=res.get("risk_level"),
        basis_level=basis.get("final_level", ""),
        basis_reason=basis.get("reason", ""),
        profile_key=profile_key,
        context_summary=_context_summary(_thread_messages(ctx.graph, profile_key)),
    )
