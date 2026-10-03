"""会话轮次服务薄壳（v2.0.0 P4，ADR-011 §1）：实现已迁 services/session.py，
此处同名再导出不破既有 import（web_app 与既有用例的 `from lightcloudmaster import service`
继续可用）；唯一实现归新包，旧壳待下一大版本随 import 面收缩再删。"""

from .services.session import service_turn

__all__ = ["service_turn"]
