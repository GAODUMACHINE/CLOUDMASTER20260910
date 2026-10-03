"""Profile Store 最小画像（unit，tmp_path，零触网）。"""

from __future__ import annotations

import pytest

from lightcloudmaster.profile_store import ProfileStore, ProfileValidationError


def _store(path):
    return ProfileStore(str(path))


def test_put_get_roundtrip(tmp_path):
    s = _store(tmp_path / "profile.json")
    s.put("u1", {"age": 22, "is_minor": False})
    assert s.get("u1") == {"age": 22, "is_minor": False}


def test_reject_unknown_field(tmp_path):
    s = _store(tmp_path / "profile.json")
    with pytest.raises(ProfileValidationError):
        s.put("u1", {"age": 22, "full_name": "张三"})  # full_name 不在白名单


def test_reject_wrong_type(tmp_path):
    s = _store(tmp_path / "profile.json")
    with pytest.raises(ProfileValidationError):
        s.put("u1", {"age": "not-int"})


def test_delete_and_has(tmp_path):
    s = _store(tmp_path / "profile.json")
    s.put("u1", {"age": 20})
    assert s.has("u1") is True
    assert s.delete("u1") is True
    assert s.has("u1") is False


def test_durability_across_instances(tmp_path):
    f = tmp_path / "profile.json"
    s1 = _store(f)
    s1.put("u1", {"age": 21, "dependency_tendency": True})
    s2 = _store(f)  # 新建实例，验证文件后备持久化
    assert s2.get("u1") == {"age": 21, "dependency_tendency": True}


def test_clear_all(tmp_path):
    s = _store(tmp_path / "profile.json")
    s.put("u1", {"age": 20})
    s.put("u2", {"age": 19})
    s.clear_all()
    assert s.has("u1") is False and s.has("u2") is False
