"""业务服务层（v2.0.0 P4，ADR-011 §1/§4）：编排存储 DAL 与图，web 路由只调本层。

- web/ 只做 HTTP 编解码、鉴权与异常翻译（领域异常 → HTTPException），业务规则收敛于此；
- 本层不 import web（禁止 services→web 反向依赖：图辅助函数两侧各自持有副本即为此取舍）；
- session=对话轮次、registration=注册三步写、assessment=自评开案、report=报告 HITL 全链路。

红线：
- 不直接开文件——唯一碰盘层是 storage/（checkpoint 库由 langgraph 自管，属唯一例外）；
- 不落对话原文进任何台账（开案只落截断摘要、报告只含聚合信息与建议）。
"""
