"""注册年龄门（ADR-005）：拒绝<14 岁数据处理；仅采集最小画像白名单；未成年须声明监护人可用。
ADR-009：注册邮箱（计划书 3.1.3-8）——报告投递所需，属最小必要采集的例外，须格式校验。"""

from __future__ import annotations

import re
from typing import Any

MIN_AGE = 14

# 宽松但明确的邮箱格式校验：本地部分@域名.顶级域。拒绝空格、连续点、无顶级域等常见错填。
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}$"
)


class RegistrationError(ValueError):
    pass


def valid_email(raw: str) -> str:
    """校验并归一化邮箱（去空白 + 小写域名部分不做强改，仅去首尾空白）。不合法抛错。"""
    value = (raw or "").strip()
    if not value:
        raise RegistrationError("请填写邮箱：疏导报告需要投递地址")
    if len(value) > 254 or ".." in value:
        raise RegistrationError("邮箱格式不正确")
    if not _EMAIL_RE.match(value):
        raise RegistrationError("邮箱格式不正确")
    return value


def register(
    *,
    age: int,
    guardian_contact_available: bool = False,
    dependency_tendency: bool = False,
    email: str = "",
) -> dict[str, Any]:
    """校验并构造最小画像；<14 岁抛错（红线：<14 数据不处理）。

    email：计划书 3.1.3-8 的注册邮箱。为「最小必要」的例外项，必填且须格式合法；
    报告默认开启（report_opt_in=True），用户可随时退订。
    """
    if not isinstance(age, int):
        raise RegistrationError("age 必须为整数")
    if age < MIN_AGE:
        raise RegistrationError("年龄不足 14 岁，不处理该用户数据")
    is_minor = age < 18
    if is_minor and not guardian_contact_available:
        raise RegistrationError("未成年须声明监护人可用信号")
    address = valid_email(email)
    profile: dict[str, Any] = {"age": age, "is_minor": is_minor, "email": address, "report_opt_in": True}
    if is_minor:
        profile["guardian_contact_available"] = True
    if dependency_tendency:
        profile["dependency_tendency"] = True
    return profile
