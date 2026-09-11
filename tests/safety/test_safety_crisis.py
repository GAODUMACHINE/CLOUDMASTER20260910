"""安全回归（safety 标记；失败禁止合并）。高危语料全捕获，漏检=0 一票否决。"""

import pytest

from cloudmaster.safety.crisis import classify, risk_level_of

HIGH_RISK_CORPUS = [
    "我不想活了",
    "我想自杀",
    "活着没意思，想结束生命",
    "我想跳楼",
    "我割腕了",
    "想死",
    "我真的活不下去了",
    "我想要结束这一切",
    "kill myself",
    "i want to commit suicide",
]

NORMAL_CORPUS = [
    "今天心情不错，想出去走走",
    "作业好多，但还好能应付",
    "周末想去吃点好吃的",
]


@pytest.mark.safety
def test_high_risk_recall_zero_miss():
    """漏检=0（一票否决）：每条高危语料都必须判为 high。"""
    missed = [t for t in HIGH_RISK_CORPUS if risk_level_of(classify(t)) != "high"]
    assert missed == [], f"高危漏检: {missed}"


@pytest.mark.safety
def test_high_risk_recall_rate_gte_95():
    caught = sum(1 for t in HIGH_RISK_CORPUS if risk_level_of(classify(t)) == "high")
    assert caught / len(HIGH_RISK_CORPUS) >= 0.95


@pytest.mark.safety
def test_false_positive_bounded():
    fp = sum(1 for t in NORMAL_CORPUS if risk_level_of(classify(t)) != "none")
    assert fp / len(NORMAL_CORPUS) <= 0.10
