"""注册服务（v2.0.0 P4，ADR-011 §1）：年龄门校验 → 匿名 ID → 三步写（画像/保留期/协议签署）。

- ADR-005 年龄门：<14 拒绝处理；未成年须声明监护人可用；注册邮箱为最小必要唯一例外。
- ADR-007 匿名身份：每人唯一随机匿名 ID（"anon-" + token_urlsafe(12) = 96 位熵），
  不含任何可回溯身份的信息。
- 《办法》协议签署留痕（v2.0.0 新增）：agreements DAL sign() 记录
  AGREEMENT_VERSION="v2.0.0" 的签署版本，注册即签署、可审计。
- 校验纯函数 register() 保留在 cloudmaster/registration.py 原位，本层复用不迁移。

设计取舍：画像、保留期、协议签署三步写经三个 DAL，任一步失败不产生半开账户——
画像先落（此后失败则匿名 ID 从未返回给用户，废键无隐私后果）；保留期设置失败按旧
web_app.register 语义静默放过（PrivacyError 兜底，惰性默认 30 天仍生效）；协议签署
放最后（其失败向上抛，账户三件套不完整即注册失败，用户重试换新匿名 ID 即可）。
不做跨 DAL 大事务：统一 SQLite 单写者串行（每库一连接一锁，ADR-012）下，顺序写
无中间态可见性问题，跨库事务反而引入新依赖——如实写明该取舍。

红线：不落对话原文（本模块不触对话数据）；匿名 ID 生成后到 store.put 前不外发。
"""

from __future__ import annotations

import secrets
from typing import Any

from ..registration import register
from ..storage.privacy import DEFAULT_RETENTION_DAYS, PrivacyError

# DAL 参数不注解具体类型：agreements 尚由并行任务落地（storage/agreements.py），且
# 测试一贯注入 fake（web_app 既有约定），鸭子类型即契约；注解写死反成耦合点。


def register_profile(
    *,
    store: Any,
    privacy: Any,
    agreements: Any,
    age: int,
    guardian_contact_available: bool = False,
    dependency_tendency: bool = False,
    email: str,
) -> tuple[str, dict[str, Any]]:
    """注册并落三处存储，返回 (匿名标识, 最小画像)。

    RegistrationError（年龄门/邮箱校验）原样向上抛，路由翻译 400；
    保留期设置失败静默放过——与旧 web_app.register 端点语义逐字一致
    （DEFAULT_RETENTION_DAYS 恒合法，except 属防御性兜底）。
    """
    profile = register(
        age=age,
        guardian_contact_available=guardian_contact_available,
        dependency_tendency=dependency_tendency,
        email=email,
    )
    key = "anon-" + secrets.token_urlsafe(12)
    store.put(key, profile)
    try:
        privacy.set_retention(key, DEFAULT_RETENTION_DAYS)
    except PrivacyError:
        pass
    # 协议签署留痕（《办法》v2.0.0 新增）：签署当前 AGREEMENT_VERSION。
    agreements.sign(key)
    return key, profile
