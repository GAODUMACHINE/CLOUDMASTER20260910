"""定时任务 CLI：purge / followups 幂等入口的运维封装。

系统不内置调度线程；由 systemd timer / cron 调用本模块（部署装配见 deploy/README.md）。

用法（服务器上）：

    .venv/bin/python -m scripts.run_jobs            # = all：先回访交付，后到期清除
    .venv/bin/python -m scripts.run_jobs followups  # 次日回访到期交付（pending→done）
    .venv/bin/python -m scripts.run_jobs purge      # 保留期到期真删除

输出单行 JSON 便于日志采集；purge 出现 failed 键时退出码 2，followups 阶段异常退出码 1。
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
    from lightcloudmaster.config import settings
    from lightcloudmaster.graph import build_graph
    from lightcloudmaster.jobs.followups import run_due
    from lightcloudmaster.jobs.purge import run_purge
    from lightcloudmaster.model import create_llm, create_stub_llm
    from lightcloudmaster.persistence import build_checkpointer
    from lightcloudmaster.storage.followups import FollowupQueue
    from lightcloudmaster.storage.privacy import PrivacyStore
    from lightcloudmaster.storage.profiles import ProfileStore
    from lightcloudmaster.storage.reports import ReportRegistry

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
