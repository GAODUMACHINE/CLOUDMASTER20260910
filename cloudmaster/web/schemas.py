"""Pydantic 请求模型（v2.0.0 P3，自 web_app.py 迁入；ADR-011 §1）。

ChatReq 自 v2.0.0 起不再含 profile_key：匿名标识改经 Authorization: Bearer 传递
（ADR-007「匿名 ID 即凭证」），请求体只剩 {"text"}；pydantic 默认忽略多余字段，
旧前端多传的 profile_key 不报错但不再被读取。EmailConfirmReq 随 /api/email/confirm
一并删除（处置表 #12）。红线：模型只描述请求形态，业务校验一律在 services/ 层。
"""

from __future__ import annotations

from pydantic import BaseModel


class RegisterReq(BaseModel):
    """注册请求：年龄（年龄门）、投递邮箱、监护人可用信号、依赖倾向自述。"""

    age: int
    email: str = ""
    guardian_contact_available: bool = False
    dependency_tendency: bool = False


class ChatReq(BaseModel):
    """对话请求：仅用户发言文本（匿名标识走 Bearer，不进请求体）。"""

    text: str


class AppealReq(BaseModel):
    """申诉请求：类型（四类词表）+ 内容 + 可选匿名标识（便于回查本人数据）。"""

    kind: str
    text: str
    profile_key: str = ""


class AssessmentReq(BaseModel):
    """自评请求：{item_id: choice_key}，纯规则计分（不调模型）。"""

    answers: dict[str, str]


class RetentionReq(BaseModel):
    """保留期设置请求：7 / 30 / 90 天（词表校验在存储层）。"""

    days: int


class ReviewDecisionReq(BaseModel):
    """审核裁决请求：结论（approve/block）+ 工单号 + 审核人署名 + 联络对象。"""

    decision: str
    ticket_id: str = ""
    reviewer: str = ""
    contact_kind: str = "guardian"


class ResourceRegisterReq(BaseModel):
    """热线录入请求：须审核人署名，未经人工审核的资源一律不下发（红线）。"""

    title: str
    detail: str = ""
    kind: str = "school"
    tel: str = ""
    reviewer: str = ""


class ReportSendReq(BaseModel):
    """报告发送确认请求（产品级 HITL）：报告编号 + 一次一密确认令牌 + 用户决定。"""

    report_id: str
    confirm_token: str
    decision: str = "approve"
