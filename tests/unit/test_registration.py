"""注册年龄门（unit，ADR-005 / ADR-009）：<14 拒绝、未成年需监护人信号、邮箱必填且格式合法。"""

from __future__ import annotations

import pytest

from cloudmaster.registration import RegistrationError, register, valid_email


def test_under_14_rejected() -> None:
    with pytest.raises(RegistrationError):
        register(age=13, email="u@example.com")


def test_minor_requires_guardian_signal() -> None:
    with pytest.raises(RegistrationError):
        register(age=16, email="u@example.com")
    ok = register(age=16, email="u@example.com", guardian_contact_available=True)
    assert ok["is_minor"] is True and ok["guardian_contact_available"] is True
    assert ok["email"] == "u@example.com"


def test_adult_minimal_profile() -> None:
    p = register(age=22, email="u@example.com")
    assert p == {"age": 22, "is_minor": False, "email": "u@example.com", "report_opt_in": True}


def test_dependency_tendency_recorded() -> None:
    p = register(age=22, email="u@example.com", dependency_tendency=True)
    assert p["dependency_tendency"] is True


# ---- 邮箱：计划书 3.1.3-8 注册邮箱（ADR-009 最小必要的例外） ----


def test_email_is_required() -> None:
    with pytest.raises(RegistrationError):
        register(age=22)
    with pytest.raises(RegistrationError):
        register(age=22, email="   ")


def test_email_is_normalized() -> None:
    assert register(age=22, email="  u@example.com  ")["email"] == "u@example.com"


@pytest.mark.parametrize(
    "bad",
    [
        "not-an-email",
        "a@b",  # 无顶级域
        "a@@example.com",
        "a b@example.com",
        "a..b@example.com",
        "@example.com",
        "a@.com",
        "a@example.",
        "a@exa mple.com",
    ],
)
def test_invalid_email_rejected(bad: str) -> None:
    with pytest.raises(RegistrationError):
        valid_email(bad)


@pytest.mark.parametrize(
    "good",
    [
        "u@example.com",
        "first.last@example.com",
        "user+tag@example.co.uk",
        "u_1-x@sub.example-school.edu.cn",
        "gaodumachine@outlook.com",
    ],
)
def test_valid_email_accepted(good: str) -> None:
    assert valid_email(good) == good


def test_overlong_email_rejected() -> None:
    with pytest.raises(RegistrationError):
        valid_email("a" * 250 + "@example.com")
