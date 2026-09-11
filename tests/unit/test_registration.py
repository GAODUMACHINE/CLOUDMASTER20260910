"""注册年龄门（unit，ADR-005）：<14 拒绝、未成年需监护人信号、成人最小画像。"""

from __future__ import annotations

import pytest

from cloudmaster.registration import RegistrationError, register


def test_under_14_rejected() -> None:
    with pytest.raises(RegistrationError):
        register(age=13)


def test_minor_requires_guardian_signal() -> None:
    with pytest.raises(RegistrationError):
        register(age=16)
    ok = register(age=16, guardian_contact_available=True)
    assert ok["is_minor"] is True and ok["guardian_contact_available"] is True


def test_adult_minimal_profile() -> None:
    p = register(age=22)
    assert p == {"age": 22, "is_minor": False}
