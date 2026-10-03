"""定时任务 CLI（v2.0.0 P7 配套）：purge / followups 幂等入口的运维封装。

系统不内置调度线程；由 systemd timer / cron 调用本模块（部署装配见 deploy/README.md）。
依赖装配与 server.build_app 同源：purge 只用 graph 的 checkpointer 删 thread，
create_llm 仅构造客户端不触网；CM_STUB=1 时同样走替身（本地演练零额度）。

用法（服务器上）：

    .venv/bin/python -m scripts.run_jobs            # = all：先回访交付，后到期清除
    .venv/bin/python -m scripts.run_jobs followups  # 次日回访到期交付（pending→done）
    .venv/bin/python -m scripts.run_jobs purge      # 保留期到期真删除（四件套）

输出单行 JSON 便于日志采集；purge 出现 failed 键时进程退出码 2（cron/监控据此告警），
followups 阶段任何异常退出码 1——两类失败不混淆。
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="LightCloudMaster 定时任务（followups/purge）")
    parser.add_argument(
        "task",
        choices=("followups", "purge", "all"),
        nargs="?",
        default="all",
        help="要执行的任务（缺省 all）",
    )
    args = parser.parse_args()

    # 惰性导入：--help 不触发模型/存储装配。
    from ..config import settings
    from ..graph import build_graph
    from ..jobs.followups import run_due
    from ..jobs.purge import run_purge
    from ..model import create_llm, create_stub_llm
    from ..persistence import build_checkpointer
    from ..privacy import PrivacyStore
    from ..profile_store import ProfileStore
    from ..storage.followups import FollowupQueue
    from ..storage.reports import ReportRegistry

    if args.task in ("followups", "all"):
        result = run_due(queue=FollowupQueue())
        print(json.dumps({"task": "followups", **result}, ensure_ascii=False))

    if args.task in ("purge", "all"):
        llm = create_stub_llm() if settings.cm_stub else create_llm()
        graph = build_graph(llm, checkpointer=build_checkpointer())
        result = run_purge(
            graph=graph,
            profiles=ProfileStore(),
            privacy=PrivacyStore(),
            reports=ReportRegistry(),
        )
        print(json.dumps({"task": "purge", **result}, ensure_ascii=False))
        if result.get("failed"):
            print(f"purge 有 {len(result['failed'])} 个键删除失败，请人工核查", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
