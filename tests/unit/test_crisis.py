"""crisis 两级判定 + 落痕审计（unit，零外部依赖）。"""

from cloudmaster.safety.crisis import L1_WORDS, L2_WORDS, classify, risk_level_of


def test_l2_words_force_high_recall():
    for w in L2_WORDS:
        assert w.lower() in w.lower()


def test_classify_l2_maps_to_high():
    basis = classify("我真的不想活了，想自杀")
    assert basis["final_level"] == "L2"
    assert risk_level_of(basis) == "high"
    assert basis["matched_words"]  # 命中词落痕非空
    assert basis["rule_level"] == "L2"


def test_classify_l1_maps_to_low():
    basis = classify("最近很压抑很绝望，感觉撑不下去")
    assert basis["final_level"] == "L1"
    assert risk_level_of(basis) == "low"


def test_classify_benign_maps_to_none():
    basis = classify("今天天气不错，想出去走走放松一下")
    assert basis["final_level"] == "L0"
    assert risk_level_of(basis) == "none"
    assert basis["matched_words"] == []


def test_llm_safe_downgrade_l2_to_l1(fake_llm_crisis_safe_downgrade):
    basis = classify("压力太大想死", fake_llm_crisis_safe_downgrade)
    assert basis["final_level"] == "L1"
    assert risk_level_of(basis) == "low"
    assert basis["llm_level"] == "SAFE"


def test_llm_danger_keeps_l2(fake_llm_crisis_danger):
    basis = classify("我想跳楼结束生命", fake_llm_crisis_danger)
    assert basis["final_level"] == "L2"
    assert risk_level_of(basis) == "high"
    assert basis["llm_level"] == "DANGER"


def test_basis_totally_auditable():
    """两级判定依据均落痕：rule_level / matched_words / llm_level / final_level / reason。"""
    basis = classify("我觉得活着没意思，不想活了")
    for key in ("rule_level", "matched_words", "llm_level", "final_level", "reason"):
        assert key in basis


def test_words_tables_nonempty():
    assert L2_WORDS and L1_WORDS
