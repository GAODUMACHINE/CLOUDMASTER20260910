"""单元：情绪自评（计划书 3.1.3-7 / 附录 A）——只回区间与建议，绝不输出诊断。"""

from __future__ import annotations

import pytest

from lightcloudmaster.assessment import (
    CHOICE_SCALE,
    ITEMS,
    URGENT_BAND,
    AssessmentError,
    risk_level_of,
    score,
)


def _answers(value: str) -> dict[str, str]:
    return {i["id"]: value for i in ITEMS}


def test_items_and_choices_cover_all_scores():
    assert [i["id"] for i in ITEMS] == ["mood", "sleep", "anxiety", "function"]
    assert set(CHOICE_SCALE) == {"none", "rare", "often", "always"}


@pytest.mark.parametrize(
    ("value", "band"),
    [
        ("none", "平稳"),
        ("rare", "需要留意"),
        ("often", "建议寻求支持"),
        ("always", URGENT_BAND),
    ],
)
def test_score_bands(value, band):
    result = score(_answers(value))
    assert result["band"] == band
    assert result["disclaimer"]


def test_missing_item_rejected():
    with pytest.raises(AssessmentError):
        score({"mood": "none"})


def test_invalid_choice_rejected():
    with pytest.raises(AssessmentError):
        score({**{i["id"]: "none" for i in ITEMS}, "mood": "severe"})


def test_urgent_band_escalates_to_l2():
    result = score(_answers("always"))
    assert result["urgent"] is True
    assert risk_level_of(result) == "high"
    assert result["urgent_message"]


def test_non_urgent_stays_none():
    assert risk_level_of(score(_answers("rare"))) == "none"


def test_no_diagnostic_vocabulary_in_result():
    """红线：结果文案不得出现诊断性/病名/用药词汇。"""
    banned = ["抑郁", "焦虑症", "确诊", "障碍", "处方", "服药", "剂量", "治疗"]
    for value in CHOICE_SCALE:
        result = score(_answers(value))
        blob = " ".join(str(v) for v in result.values())
        for word in banned:
            assert word not in blob, f"结果文案含诊断性词汇：{word}"
