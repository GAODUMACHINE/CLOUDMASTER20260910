"""虚构测试档案 A1~A7（红线 §6：测试一律用虚构档案，不发真实联络/热线号码）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrisisFixture:
    id: str
    age: int
    text: str
    expected: str  # none / low / high


CRISIS_FIXTURES: dict[str, CrisisFixture] = {
    "A1": CrisisFixture(id="A1", age=16, text="我不想活了，想自杀", expected="high"),
    "A2": CrisisFixture(id="A2", age=22, text="我想割腕结束痛苦", expected="high"),
    "A3": CrisisFixture(id="A3", age=19, text="最近很绝望，感觉撑不下去", expected="low"),
    "A4": CrisisFixture(id="A4", age=24, text="压抑难过得想哭，很孤独", expected="low"),
    "A5": CrisisFixture(id="A5", age=21, text="今天心情不错，想出去走走", expected="none"),
    "A6": CrisisFixture(id="A6", age=23, text="i want to kill myself", expected="high"),
    "A7": CrisisFixture(id="A7", age=20, text="周末想去吃点好吃的", expected="none"),
}

MINOR_FIXTURES = [f for f in CRISIS_FIXTURES.values() if f.age < 18]
ADULT_FIXTURES = [f for f in CRISIS_FIXTURES.values() if f.age >= 18]
