"""JSON/JSONL 旧存储 → SQLite business.db 一次性迁移 CLI（重写计划 §15b.3 / §17-P3）。

用法（仓库根目录）：

    .venv/Scripts/python.exe -m scripts.migrate_json_to_sqlite --dry-run   # 只读对账
    .venv/Scripts/python.exe -m scripts.migrate_json_to_sqlite             # 执行迁移

实跑语义：单事务 all-or-nothing；成功后旧文件改名 <name>.bak（递增 .bak.1/...）只读
归档不删除，并向 audit_events 追加 storage_migrated 审计。INSERT OR IGNORE 幂等，
中断重跑只补漏。dry-run 严格只读（不建库、不写行、不归档）。

**执行时点：P3 切换窗口才对生产数据执行**（单一维护动作，消除新旧 store 并存分叉）。
明细与行号见 summary JSON 的 skipped_detail / orphans_detail——绝不静默丢弃任何记录。
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from lightcloudmaster.storage import migrate
from lightcloudmaster.storage.db import DEFAULT_BUSINESS_DB


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="旧 JSON/JSONL 存储（data/private）→ SQLite business.db 一次性迁移"
    )
    parser.add_argument(
        "--data-dir",
        default="data/private",
        help="旧存储目录（默认：%(default)s）",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_BUSINESS_DB,
        help="目标业务库路径（默认：%(default)s）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读对账：不建库、不写行、不归档",
    )
    args = parser.parse_args(argv)
    summary = migrate.run(args.data_dir, args.db, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _warn_pending_review(summary)
    return 0


def _warn_pending_review(summary: dict[str, Any]) -> None:
    """orphans/skipped 非零时输出醒目提示（迁移本身成功，但需人工核对清单）。"""
    for name, stat in summary["sources"].items():
        if stat.get("orphans") or stat.get("skipped"):
            print(
                f"[需人工复核] 来源 {name}：orphans={stat['orphans']} skipped={stat['skipped']}，"
                "明细见上方 skipped_detail / orphans_detail（对应原始记录保留在归档 .bak 内）。"
            )


if __name__ == "__main__":
    raise SystemExit(main())
