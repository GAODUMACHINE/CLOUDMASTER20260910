"""按域拆分的 API 路由（v2.0.0 P3，计划 §21 / ADR-011 §1）。

web_app.py 单文件 660 行的终结：HTTP 端点按业务域拆入 8 个 router——
chat / register / report / review / assessment / privacy / appeals / resources。
装配（create_app）在 web/__init__.py，鉴权与图辅助在 web/deps.py，请求模型在 web/schemas.py。

24 路由处置表（功能对照表 §二）自本阶段落地：/api/email/confirm 删除（#12——以 body
传完整收件人/主题/正文、仅凭单一静态令牌放行，等于开放中继；前端零调用，真实流程由
/api/report/send 的 HITL + 报告令牌覆盖），其余 23 路由行为不变（鉴权契约除外）。

红线：路由函数只做「鉴权 → 调服务/DAL → 组装响应」，业务规则一律在 services/ 与
storage/ 层；审核台全部端点必须经 require_reviewer（令牌走 Authorization header，不进 URL）。
"""
