"""共情性抽样（真实模型）——为人工评分准备样本，**不臆造分数**（TC-CHAT-003 / TC-UX-002）。

用法（仓库根目录，`.env` 已配真实 key 且 CM_STUB=0）：

    .venv/Scripts/python.exe -m scripts.empathy_sample --n 20 --out docs/eval/empathy-samples.csv

产出 CSV 的评分列留空，由人工按 `docs/eval/empathy-rubric.md` 的 5 分制填写；
汇总均分 ≥4/5 才算通过。脚本本身不产生、不推断任何评分。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from cloudmaster.config import settings
from cloudmaster.graph import build_graph
from cloudmaster.model import create_llm

# 倾诉类合成话术（非真实用户数据），覆盖学业/人际/家庭/自我评价/睡眠/未来等常见主题。
PROMPTS = [
    "这学期成绩掉得厉害，觉得自己很没用",
    "和最好的朋友吵架了，现在谁都不理我",
    "爸妈总拿我跟别人比，我很累",
    "投了很多简历都没有回音，怀疑自己",
    "晚上总是睡不着，脑子里停不下来",
    "在宿舍觉得特别孤独，融不进去",
    "分手两个月了，还是走不出来",
    "一想到毕业就焦虑得喘不上气",
    "我好像对什么都提不起兴趣",
    "今天被老师当众批评，很难受",
    "总觉得自己在拖累身边的人",
    "家里最近气氛很紧张，我不想回去",
    "实习压力好大，怕自己做不好",
    "不敢跟别人说这些，怕被当成矫情",
    "明明很努力了，还是达不到期望",
    "有时候会突然很想哭，说不出原因",
    "社交场合总是紧张到手心出汗",
    "感觉每天都在重复，没有意义",
    "想找人说说话，但不知道从哪开始",
    "最近很容易烦躁，一点小事就想发火",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="CloudMaster 共情性抽样（人工评分的输入，不评分）")
    parser.add_argument("--n", type=int, default=20, help="样本条数（默认 20）")
    parser.add_argument("--out", default="docs/eval/empathy-samples.csv", help="CSV 输出路径")
    args = parser.parse_args()

    if settings.cm_stub:
        print("CM_STUB=1：当前为本地确定性替身，抽样结果无评分价值。请在 .env 设 CM_STUB=0。")
        return 2
    if not settings.configured():
        print("未配置真实模型：请在 .env 提供 QWEN_API_KEY 与 QWEN_API_HOST。")
        return 2

    llm: Any = create_llm()
    graph = build_graph(llm, checkpointer=InMemorySaver())
    rows: list[dict[str, str]] = []
    for i in range(args.n):
        text = PROMPTS[i % len(PROMPTS)]
        cfg = {"configurable": {"thread_id": f"empathy-{i}"}}
        res = graph.invoke({"messages": [HumanMessage(text)], "user_profile": {"age": 22}}, cfg)
        msgs = res.get("messages") or []
        reply = str(msgs[-1].content) if msgs else ""
        rows.append(
            {
                "id": f"E{i + 1:03d}",
                "user_text": text,
                "reply": reply,
                "risk_level": str(res.get("risk_level")),
                "共情性(1-5)": "",
                "帮助性(1-5)": "",
                "备注": "",
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[已写入] {out}（{len(rows)} 条，评分列留空待人工填写）")
    print("评分口径见 docs/eval/empathy-rubric.md；均分 ≥4/5 才通过 TC-CHAT-003 / TC-UX-002。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
