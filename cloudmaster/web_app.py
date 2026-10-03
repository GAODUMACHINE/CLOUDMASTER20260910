"""Web 薄壳（v2.0.0 P3，ADR-011 §1）：实现已迁入 cloudmaster/web/ 包，本模块只保留
create_app 同名再导出——既有 `from cloudmaster.web_app import create_app`（server.py
与全部集成测试）不破；660 行单文件的结束。历史：v0.5.0 起（ADR-005），v1.1.0 补匿名
隔离与申诉，v1.2.0 补计划书缺口，v1.3.0 补邮件收发（ADR-009），v2.0.0 P3 拆包。
"""

from .web import create_app

__all__ = ["create_app"]
