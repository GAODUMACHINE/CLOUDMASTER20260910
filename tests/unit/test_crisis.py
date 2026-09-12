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


def test_llm_confirm_danger_upgrades_l1_to_l2(fake_llm_crisis_danger):
    """复核为 DANGER 时应升级到 L2（L1 规则命中不足以挡住人工审核）。"""
    basis = classify("最近很压抑很绝望", fake_llm_crisis_danger)
    assert basis["rule_level"] == "L1"
    assert basis["final_level"] == "L2"
    assert risk_level_of(basis) == "high"


def test_llm_screen_catches_implicit_l2(fake_llm_screen_danger):
    """规则未命中时的语义风险（计划安排/告别暗示/绝望自贬/隐喻）必须被语义筛查捕获——防漏检关键类。"""
    corpus = [
        "我已经开始做最后的安排了",
        "谢谢你一直陪我，这是最后一次聊了",
        "帮我照顾好我的家人",
        "我就是个彻底的累赘，我消失了大家都会轻松",
        "想去很远很远的地方",
        "我不想huo了",
    ]
    for text in corpus:
        basis = classify(text, fake_llm_screen_danger)
        assert basis["rule_level"] == "L0", text
        assert basis["llm_mode"] == "screen", text
        assert risk_level_of(basis) == "high", text


def test_llm_screen_watch_maps_to_low(fake_llm_screen_watch):
    basis = classify("最近有点说不上来的不对劲", fake_llm_screen_watch)
    assert basis["final_level"] == "L1"
    assert risk_level_of(basis) == "low"
    assert basis["llm_mode"] == "screen"


def test_llm_screen_safe_stays_none(fake_llm_empathic):
    basis = classify("今天天气不错，想出去走走放松一下", fake_llm_empathic)
    assert basis["final_level"] == "L0"
    assert risk_level_of(basis) == "none"
    assert basis["llm_mode"] == "screen"


def test_empty_text_skips_llm_layer(fake_llm_screen_danger):
    basis = classify("   ", fake_llm_screen_danger)
    assert basis["confirmed_by_llm"] is False
    assert basis["final_level"] == "L0"


def test_persistent_low_mood_maps_to_low():
    """TC-CRI-002：持续低落/自我否定表述应判 low。"""
    basis = classify("已经连续两周每天都很低落，觉得自己一无是处")
    assert basis["rule_level"] == "L1"
    assert risk_level_of(basis) == "low"


def test_low_mood_prefilter_does_not_escalate_to_high():
    """TC-CRI-001/附录A 类别7：一般情绪与低危对照不得判 L2（误报控制）。"""
    for text in ["这周考试考砸了，挺郁闷的", "最近压力好大，晚上总想哭"]:
        assert risk_level_of(classify(text)) != "high", text


def test_ordinary_venting_stays_none_with_semantic_layer(fake_llm_empathic):
    """TC-CRI-001：一般情绪消息（考试考砸了）在语义层常开时仍须判 none。"""
    basis = classify("这周考试考砸了，挺郁闷的", fake_llm_empathic)
    assert risk_level_of(basis) == "none"
    assert basis["llm_mode"] == "screen"


def test_broad_mood_word_not_in_l1():
    """「低落」等过宽词不得进 L1：影视观感/一时吐槽会被误升为 low（附录 A 类别 8）。"""
    assert "低落" not in L1_WORDS
    assert risk_level_of(classify("昨天看的电影结局好虐，心情有点低落")) == "none"


def test_basis_totally_auditable():
    """两级判定依据均落痕：rule_level / matched_words / llm_level / final_level / reason。"""
    basis = classify("我觉得活着没意思，不想活了")
    for key in ("rule_level", "matched_words", "llm_level", "final_level", "reason"):
        assert key in basis


def test_words_tables_nonempty():
    assert L2_WORDS and L1_WORDS
