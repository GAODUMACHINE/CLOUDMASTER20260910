"""单元：隐私保留期与一键导出（计划书 3.2.4 / 3.1.3-6）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from cloudmaster.privacy import (
    DEFAULT_RETENTION_DAYS,
    RETENTION_CHOICES,
    PrivacyError,
    PrivacyStore,
    export_bundle,
)


@pytest.fixture
def store(tmp_path):
    return PrivacyStore(str(tmp_path / "privacy.json"))


def test_default_retention_is_30_days(store):
    assert store.get_retention("k")["retention_days"] == DEFAULT_RETENTION_DAYS
    assert RETENTION_CHOICES == (7, 30, 90)


@pytest.mark.parametrize("days", [7, 30, 90])
def test_allowed_retention_choices(store, days):
    record = store.set_retention("k", days)
    assert record["retention_days"] == days
    assert record["created_at"]


def test_retention_outside_choices_rejected(store):
    for days in (0, 45, 365):
        with pytest.raises(PrivacyError):
            store.set_retention("k", days)


def test_purge_schedule_marks_expired(store):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    store.set_retention("k", 7, now=base)
    fresh = store.purge_schedule("k", now=datetime(2026, 1, 5, tzinfo=UTC))
    expired = store.purge_schedule("k", now=datetime(2026, 2, 1, tzinfo=UTC))
    assert fresh["expired"] is False and expired["expired"] is True
    assert expired["delete_after"].startswith("2026-01-08")


def test_forget_clears_preference(store):
    store.set_retention("k", 90)
    assert store.forget("k") is True
    assert store.get_retention("k")["retention_days"] == DEFAULT_RETENTION_DAYS


def test_export_bundle_shapes_roles():
    bundle = export_bundle(
        profile_key="anon-1",
        profile={"age": 20, "is_minor": False},
        messages=[HumanMessage("你好"), AIMessage("我在")],
        retention={"retention_days": 30},
    )
    assert bundle["message_count"] == 2
    assert [m["role"] for m in bundle["messages"]] == ["user", "ai"]
    assert bundle["profile_key"] == "anon-1"


def test_export_handles_missing_profile_and_messages():
    bundle = export_bundle(profile_key="anon-1", profile=None, messages=None)
    assert bundle["messages"] == [] and bundle["profile"] == {}
