"""安全回归（v0.3.0）：虚构档案 A1~A7 分级零漏检（漏检=0 一票否决）。"""

import pytest

from lightcloudmaster.safety.crisis import classify, risk_level_of
from tests.fixtures.crisis_profiles import CRISIS_FIXTURES


@pytest.mark.safety
def test_fixtures_classification_zero_miss():
    missed = [f.id for f in CRISIS_FIXTURES.values() if risk_level_of(classify(f.text)) != f.expected]
    assert missed == [], f"档案分级漏判: {missed}"
