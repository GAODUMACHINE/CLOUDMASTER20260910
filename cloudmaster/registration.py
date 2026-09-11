"""注册年龄门（ADR-005）：拒绝<14 岁数据处理；仅采集最小画像白名单；未成年须声明监护人可用。"""

from __future__ import annotations

from typing import Any

MIN_AGE = 14


class RegistrationError(ValueError):
    pass


def register(
    *,
    age: int,
    guardian_contact_available: bool = False,
    dependency_tendency: bool = False,
) -> dict[str, Any]:
    """校验并构造最小画像；<14 岁抛错（红线：<14 数据不处理）。"""
    if not isinstance(age, int):
        raise RegistrationError("age 必须为整数")
    if age < MIN_AGE:
        raise RegistrationError("年龄不足 14 岁，不处理该用户数据")
    is_minor = age < 18
    if is_minor and not guardian_contact_available:
        raise RegistrationError("未成年须声明监护人可用信号")
    profile: dict[str, Any] = {"age": age, "is_minor": is_minor}
    if is_minor:
        profile["guardian_contact_available"] = True
    if dependency_tendency:
        profile["dependency_tendency"] = True
    return profile
