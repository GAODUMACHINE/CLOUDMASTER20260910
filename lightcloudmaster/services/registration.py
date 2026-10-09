"""注册服务：年龄门校验 → 匿名 ID → 三步写（画像/保留期/协议签署）。

- 年龄门：<14 拒绝处理；未成年须声明监护人可用；注册邮箱为最小必要唯一例外。
- 匿名身份：每人唯一随机匿名 ID（"anon-" + token_urlsafe(12)），不含任何可回溯
  身份的信息。
- 协议签署留痕：agreements DAL sign() 记录签署版本，注册即签署、可审计。

三步写取舍：画像先落（此后失败则匿名 ID 从未返回给用户，废键无隐私后果）；
保留期设置失败静默放过（惰性默认 30 天仍生效）；协议签署放最后（其失败向上抛，
三件套不完整即注册失败）。不做跨 DAL 大事务——统一 SQLite 单写者串行下，
顺序写无中间态可见性问题。

红线：不落对话原文；匿名 ID 生成后到 store.put 前不外发。
"""

from __future__ import annotations

import secrets
from typing import Any

from ..registration import register
from ..storage.privacy import DEFAULT_RETENTION_DAYS, PrivacyError


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
    保留期设置失败静默放过（DEFAULT_RETENTION_DAYS 恒合法，except 属防御性兜底）。
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
    # 协议签署留痕。
    agreements.sign(key)
    return key, profile
