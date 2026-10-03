"""单元：已审核转介资源（TC-RES-001）——默认不下发任何号码，须审核人署名。"""

from __future__ import annotations

import pytest

from lightcloudmaster.resources import ResourceError, ResourceStore


@pytest.fixture
def store(tmp_path):
    return ResourceStore(str(tmp_path / "resources.jsonl"))


def test_nothing_approved_by_default(store):
    """红线：未录入任何经审核号码时，必须不下发任何号码。"""
    assert store.approved() == []


def test_add_requires_reviewer(store):
    with pytest.raises(ResourceError):
        store.add(title="某热线", reviewer="")
    assert store.approved() == []


def test_add_requires_title(store):
    with pytest.raises(ResourceError):
        store.add(title="  ", reviewer="A1")


def test_invalid_tel_rejected(store):
    for bad in ("abc", "tel:110", "<script>", "110-ext", "+86 10 1234", "#110"):
        with pytest.raises(ResourceError):
            store.add(title="某热线", reviewer="A1", tel=bad)


def test_short_service_numbers_allowed(store):
    """5 位政务/服务号码（如 12345）是合法号码，不应被误拒。"""
    record = store.add(title="某市政务服务热线", reviewer="A1", tel="12345", kind="hotline")
    assert record["tel"] == "12345"


def test_invalid_kind_rejected(store):
    with pytest.raises(ResourceError):
        store.add(title="某热线", reviewer="A1", kind="unknown")


def test_approved_hotline_is_returned_after_review(store):
    store.add(title="某市心理援助热线", reviewer="A1", tel="010-12345678", kind="hotline")
    approved = store.approved()
    assert len(approved) == 1
    assert approved[0]["reviewer"] == "A1"
    assert approved[0]["kind_label"]


def test_text_only_resource_allowed_without_tel(store):
    record = store.add(title="学校心理中心", reviewer="A1", kind="school")
    assert record["tel"] == ""
    assert len(store.approved()) == 1
