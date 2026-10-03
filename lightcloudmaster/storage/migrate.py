"""一次性迁移：data/private 旧 JSON/JSONL 存储 → storage/ SQLite business.db。

旧六类文件 → 统一业务库（DDL 见 storage/db.py）：
profile.json → profiles；privacy.json → privacy_settings；reviews.jsonl →
review_cases + review_decisions（两遍配对）；appeals.jsonl → appeals；
resources.jsonl → resources；inbox.jsonl → inbox_mails。

设计要点（重写计划 §15b.3）：
- INSERT OR IGNORE 幂等：重跑只补漏不重复；resources 无自然主键，按
  (title, approved_at) 预查去重后再插。
- reviews.jsonl 两遍扫描：第一遍按 ticket_id 收集开案行（status=pending）与结论行
  （status=resolved），源内重复 ticket 计入 skipped；第二遍配对——成对 → resolved
  案 + 结论行（**保留原工单号与原始时间戳**），开案无结论 → 保持 pending（如实呈现
  未闭环状态），结论无开案 → orphans。坏行（非法 JSON/缺关键字段）一律计入
  orphans 并附行号，绝不静默丢弃。
- 画像逐条过白名单校验（复用 ProfileStore._validate）：违规条目 skipped，不中断整体。
- privacy 逐条校验 retention_days ∈ (7, 30, 90)（表级 CHECK 的前置过滤）。
- dry_run 严格只读：不建库、不写行、不归档，用 mode=ro 连接对账既有行数，
  输出与实跑同构的清单。
- 实跑单事务：全部来源插完一次 commit（all-or-nothing），成功后原文件改名
  <name>.bak（已存在则 .bak.1/.bak.2 递增）只读归档不删除，并向 audit_events
  追加 storage_migrated 审计。
- 内存态（旧 ReportRegistry / Mailer 发送台账）无文件可迁，明示接受丢失。
- 执行时点：P3 切换窗口才对生产数据执行（单一维护动作，计划 §21）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import db
from .privacy import RETENTION_CHOICES
from .profiles import ProfileStore, ProfileValidationError
from .reviews import CONTACT_KINDS, REVIEW_DECISIONS

# 来源名（汇总报告键）→ 旧文件名；处理顺序即此表顺序。
SOURCE_FILES = {
    "profiles": "profile.json",
    "privacy": "privacy.json",
    "reviews": "reviews.jsonl",
    "appeals": "appeals.jsonl",
    "resources": "resources.jsonl",
    "inbox": "inbox.jsonl",
}

# 来源名 → 目标表（existing_before 计数用）。
TARGET_TABLES = {
    "profiles": "profiles",
    "privacy": "privacy_settings",
    "reviews": "review_cases",
    "appeals": "appeals",
    "resources": "resources",
    "inbox": "inbox_mails",
}


def run(data_dir: str | Path, db_path: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """执行迁移。返回对账清单（dry_run 与实跑同构，inserted/archived 在 dry_run 恒空）。"""
    data_dir, db_path = Path(data_dir), Path(db_path)
    summary: dict[str, Any] = {
        "data_dir": str(data_dir),
        "db_path": str(db_path),
        "dry_run": dry_run,
        "sources": {name: _blank_stat((data_dir / fn).exists()) for name, fn in SOURCE_FILES.items()},
        "archived": [],
    }
    rows = _collect(data_dir, summary)
    for name, stat in summary["sources"].items():
        stat["valid"] = sum(len(v) for k, v in rows.items() if k[0] == name)
    if dry_run:
        for name, table in TARGET_TABLES.items():
            summary["sources"][name]["existing_before"] = _count_ro(db_path, table)
        return summary

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn, lock = db.connect(db_path)
    with lock:
        for name, table in TARGET_TABLES.items():
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 -- 表名取自常量表
            summary["sources"][name]["existing_before"] = int(row[0])
        _insert_all(conn, rows, summary)
        conn.commit()
    for _name, fn in SOURCE_FILES.items():
        src = data_dir / fn
        if src.exists():
            summary["archived"].append(_archive(src))
    db.record_audit(conn, lock, "storage_migrated", "", _audit_detail(summary))
    return summary


def _blank_stat(present: bool) -> dict[str, Any]:
    return {
        "present": present,
        "read": 0,  # 读到的记录数（JSONL 非空行 / JSON 顶层条目）
        "valid": 0,  # 通过校验/配对、待入库的行数（reviews 含 review_decisions）
        "inserted": 0,  # 实际 INSERT 成功行数（OR IGNORE 忽略的不计）
        "existing_before": 0,
        "skipped": 0,
        "skipped_detail": [],
        "orphans": 0,
        "orphans_detail": [],
    }


# ---------- 读取与校验（纯读，无库交互） ----------


def _read_json_dict(path: Path, stat: dict[str, Any]) -> dict[str, Any]:
    """读 {key: {...}} 形态 JSON 文件；坏文件整体计入 orphans 并返回 {}。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        stat["orphans"] += 1
        stat["orphans_detail"].append(f"文件无法读取或不是合法 JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        stat["orphans"] += 1
        stat["orphans_detail"].append(f"顶层应为对象，实为 {type(data).__name__}")
        return {}
    return data


def _read_jsonl(path: Path, stat: dict[str, Any]) -> list[tuple[int, dict[str, Any] | None]]:
    """逐行读 JSONL，产出 (行号, 记录)；坏行计 orphans 并以 None 占位。"""
    out: list[tuple[int, dict[str, Any] | None]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        stat["orphans"] += 1
        stat["orphans_detail"].append(f"文件无法读取: {exc}")
        return out
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        stat["read"] += 1
        try:
            rec: Any = json.loads(line)
        except json.JSONDecodeError:
            stat["orphans"] += 1
            stat["orphans_detail"].append(f"第 {lineno} 行不是合法 JSON")
            out.append((lineno, None))
            continue
        if not isinstance(rec, dict):
            stat["orphans"] += 1
            stat["orphans_detail"].append(f"第 {lineno} 行不是 JSON 对象")
            out.append((lineno, None))
        else:
            out.append((lineno, rec))
    return out


def _collect(data_dir: Path, summary: dict[str, Any]) -> dict[tuple[str, str], list[tuple]]:
    """读全部来源 → 校验/配对 → {(来源名, 目标表): 行元组列表}。"""
    rows: dict[tuple[str, str], list[tuple]] = {}
    for name, fn in SOURCE_FILES.items():
        stat = summary["sources"][name]
        path = data_dir / fn
        if not stat["present"]:
            rows[(name, TARGET_TABLES[name])] = []
            if name == "reviews":
                rows[(name, "review_decisions")] = []
            continue
        if name == "profiles":
            rows[(name, "profiles")] = _collect_profiles(_read_json_dict(path, stat), stat)
        elif name == "privacy":
            rows[(name, "privacy_settings")] = _collect_privacy(_read_json_dict(path, stat), stat)
        elif name == "reviews":
            cases, decisions = _collect_reviews(_read_jsonl(path, stat), stat)
            rows[(name, "review_cases")] = cases
            rows[(name, "review_decisions")] = decisions
        elif name == "appeals":
            rows[(name, "appeals")] = _collect_appeals(_read_jsonl(path, stat), stat)
        elif name == "resources":
            rows[(name, "resources")] = _collect_resources(_read_jsonl(path, stat), stat)
        else:
            rows[(name, "inbox_mails")] = _collect_inbox(_read_jsonl(path, stat), stat)
    return rows


def _collect_profiles(data: dict[str, Any], stat: dict[str, Any]) -> list[tuple]:
    out: list[tuple] = []
    for key, entry in data.items():
        stat["read"] += 1
        if not isinstance(entry, dict):
            stat["skipped"] += 1
            stat["skipped_detail"].append(f"{key}: 条目不是对象，跳过")
            continue
        try:
            cleaned = ProfileStore._validate(entry)
        except ProfileValidationError as exc:
            stat["skipped"] += 1
            stat["skipped_detail"].append(f"{key}: {exc}")
            continue
        out.append(
            (
                key,
                cleaned.get("age"),
                _int_or_none(cleaned, "is_minor"),
                _int_or_none(cleaned, "guardian_contact_available"),
                _int_or_none(cleaned, "emergency_contact_available"),
                _int_or_none(cleaned, "dependency_tendency"),
                cleaned.get("email"),
                _int_or_none(cleaned, "report_opt_in"),
                json.dumps(cleaned, ensure_ascii=False),
                # 旧 profile.json 未记录创建时间，无法考古——首次迁移统一取当前时刻，
                # 如实记录而非伪造；重跑时 OR IGNORE 不改既有行的 created_at。
                db.now_iso(),
                db.now_iso(),
            )
        )
    return out


def _collect_privacy(data: dict[str, Any], stat: dict[str, Any]) -> list[tuple]:
    out: list[tuple] = []
    for key, entry in data.items():
        stat["read"] += 1
        if not isinstance(entry, dict) or entry.get("retention_days") not in RETENTION_CHOICES:
            stat["skipped"] += 1
            stat["skipped_detail"].append(f"{key}: 保留期须为 {list(RETENTION_CHOICES)} 天之一，跳过")
            continue
        out.append(
            (
                key,
                entry["retention_days"],
                entry.get("created_at") or db.now_iso(),
                entry.get("updated_at") or db.now_iso(),
            )
        )
    return out


def _collect_reviews(
    lines: list[tuple[int, dict[str, Any] | None]], stat: dict[str, Any]
) -> tuple[list[tuple], list[tuple]]:
    """两遍配对：第一遍按 ticket_id 收集开案/结论行（剔除源内重复），第二遍成对落位。"""
    opens: dict[str, dict[str, Any]] = {}
    closes: dict[str, tuple[int, dict[str, Any]]] = {}
    for lineno, rec in lines:
        if rec is None:
            continue  # 坏行已在 _read_jsonl 计 orphans
        tid = str(rec.get("ticket_id") or "")
        if not tid or not rec.get("thread_id"):
            stat["orphans"] += 1
            stat["orphans_detail"].append(f"第 {lineno} 行缺少 ticket_id/thread_id")
            continue
        status = rec.get("status")
        if status == "pending":
            if tid in opens:
                stat["skipped"] += 1
                stat["skipped_detail"].append(f"重复开案行 ticket_id={tid}（第 {lineno} 行），取首行")
            else:
                opens[tid] = rec
        elif status == "resolved":
            if rec.get("decision") not in REVIEW_DECISIONS or rec.get("contact_kind") not in CONTACT_KINDS:
                stat["orphans"] += 1
                stat["orphans_detail"].append(f"第 {lineno} 行结论词表不合法（decision/contact_kind）")
            elif tid in closes:
                stat["skipped"] += 1
                stat["skipped_detail"].append(f"重复结论行 ticket_id={tid}（第 {lineno} 行），取首行")
            else:
                closes[tid] = (lineno, rec)
        else:
            stat["orphans"] += 1
            stat["orphans_detail"].append(f"第 {lineno} 行 status 异常: {status!r}")

    cases: list[tuple] = []
    decisions: list[tuple] = []
    for tid, rec in opens.items():
        paired_close = closes.pop(tid, None)
        cases.append(
            (
                tid,
                str(rec.get("thread_id") or ""),
                str(rec.get("profile_key") or ""),
                str(rec.get("opened_at") or ""),
                str(rec.get("risk_level") or ""),
                str(rec.get("basis_level") or ""),
                str(rec.get("basis_reason") or ""),
                str(rec.get("context_summary") or ""),
                "resolved" if paired_close is not None else "pending",
            )
        )
        if paired_close is not None:
            _lineno, closed = paired_close
            decisions.append(
                (
                    tid,
                    str(closed.get("thread_id") or rec.get("thread_id") or ""),
                    str(closed.get("decision") or ""),
                    str(closed.get("decision_label") or REVIEW_DECISIONS[closed["decision"]]),
                    str(closed.get("contact_kind") or ""),
                    str(closed.get("contact_label") or CONTACT_KINDS[closed["contact_kind"]]),
                    str(closed.get("reviewer") or "unassigned"),
                    str(closed.get("resolved_at") or ""),
                )
            )
    for tid, (lineno, _rec) in closes.items():
        stat["orphans"] += 1
        stat["orphans_detail"].append(f"第 {lineno} 行结论无对应开案 ticket_id={tid}")
    return cases, decisions


def _collect_appeals(lines: list[tuple[int, dict[str, Any] | None]], stat: dict[str, Any]) -> list[tuple]:
    out: list[tuple] = []
    for lineno, rec in lines:
        if rec is None:
            continue
        tid = str(rec.get("ticket_id") or "")
        if not tid:
            stat["orphans"] += 1
            stat["orphans_detail"].append(f"第 {lineno} 行缺少 ticket_id")
            continue
        out.append(
            (
                tid,
                str(rec.get("submitted_at") or ""),
                str(rec.get("kind") or "other"),
                str(rec.get("kind_label") or ""),
                str(rec.get("text") or ""),
                str(rec.get("profile_key") or ""),
                str(rec.get("status") or "received"),
            )
        )
    return out


def _collect_resources(lines: list[tuple[int, dict[str, Any] | None]], stat: dict[str, Any]) -> list[tuple]:
    out: list[tuple] = []
    for lineno, rec in lines:
        if rec is None:
            continue
        if not (rec.get("title") and rec.get("reviewer")):
            stat["skipped"] += 1
            stat["skipped_detail"].append(f"第 {lineno} 行缺 title/reviewer（未审核资源不下发），跳过")
            continue
        out.append(
            (
                str(rec["title"]),
                str(rec.get("detail") or ""),
                str(rec.get("kind") or "school"),
                str(rec.get("kind_label") or ""),
                str(rec.get("tel") or ""),
                str(rec["reviewer"]),
                str(rec.get("approved_at") or ""),
            )
        )
    return out


def _collect_inbox(lines: list[tuple[int, dict[str, Any] | None]], stat: dict[str, Any]) -> list[tuple]:
    out: list[tuple] = []
    for lineno, rec in lines:
        if rec is None:
            continue
        uid = str(rec.get("uid") or "")
        if not uid:
            stat["orphans"] += 1
            stat["orphans_detail"].append(f"第 {lineno} 行缺少 uid")
            continue
        out.append(
            (
                uid,
                str(rec.get("kind") or "other"),
                str(rec.get("from_addr") or ""),
                str(rec.get("subject") or ""),
                str(rec.get("date") or ""),
                str(rec.get("ticket") or ""),
                str(rec.get("body") or ""),
                int(bool(rec.get("stop_requested"))),
                str(rec.get("fetched_at") or ""),
            )
        )
    return out


def _int_or_none(cleaned: dict[str, Any], key: str) -> int | None:
    v = cleaned.get(key)
    return None if v is None else int(v)


# ---------- 落库（单事务） ----------


def _insert_all(
    conn: sqlite3.Connection, rows: dict[tuple[str, str], list[tuple]], summary: dict[str, Any]
) -> None:
    # 有主键/唯一约束的表：executemany OR IGNORE，rowcount 即实际插入数。
    _executemany(
        conn,
        "INSERT OR IGNORE INTO profiles (anon_key, age, is_minor,"
        " guardian_contact_available, emergency_contact_available, dependency_tendency,"
        " email, report_opt_in, data_json, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows[("profiles", "profiles")],
        summary["sources"]["profiles"],
    )
    _executemany(
        conn,
        "INSERT OR IGNORE INTO privacy_settings (anon_key, retention_days, created_at, updated_at)"
        " VALUES (?, ?, ?, ?)",
        rows[("privacy", "privacy_settings")],
        summary["sources"]["privacy"],
    )
    _executemany(
        conn,
        "INSERT OR IGNORE INTO appeals (ticket_id, submitted_at, kind, kind_label, text,"
        " profile_key, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows[("appeals", "appeals")],
        summary["sources"]["appeals"],
    )
    _executemany(
        conn,
        "INSERT OR IGNORE INTO inbox_mails (uid, kind, from_addr, subject, date, ticket,"
        " body, stop_requested, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows[("inbox", "inbox_mails")],
        summary["sources"]["inbox"],
    )
    # review_cases 无 OR IGNORE 兜底的唯一索引（同 thread 仅一 pending）：逐行插、
    # 撞 uq_review_pending_thread 时如实计入 skipped。
    cases_stat = summary["sources"]["reviews"]
    for row in rows[("reviews", "review_cases")]:
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO review_cases (ticket_id, thread_id, profile_key,"
                " opened_at, risk_level, basis_level, basis_reason, context_summary, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            cases_stat["inserted"] += cur.rowcount
        except sqlite3.IntegrityError:
            cases_stat["skipped"] += 1
            cases_stat["skipped_detail"].append(
                f"ticket_id={row[0]} 与既有未闭环案同 thread（uq_review_pending_thread 拦截）"
            )
    for row in rows[("reviews", "review_decisions")]:
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO review_decisions (ticket_id, thread_id, decision,"
                " decision_label, contact_kind, contact_label, reviewer, resolved_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            cases_stat["inserted"] += cur.rowcount
        except sqlite3.IntegrityError:
            cases_stat["skipped"] += 1
            cases_stat["skipped_detail"].append(f"ticket_id={row[0]} 结论行外键不满足（对应开案未入库）")
    # resources 无自然主键：按 (title, approved_at) 预查去重，保证重跑不重复下发清单。
    res_stat = summary["sources"]["resources"]
    existing = {
        (r["title"], r["approved_at"])
        for r in conn.execute("SELECT title, approved_at FROM resources").fetchall()
    }
    fresh = []
    for row in rows[("resources", "resources")]:
        key = (row[0], row[6])
        if key in existing:  # 库内已有或本批已收（源内同键重复同样跳过）
            res_stat["skipped"] += 1
            res_stat["skipped_detail"].append(f"{row[0]}（{row[6]}）已存在，跳过")
            continue
        existing.add(key)
        fresh.append(row)
    _executemany(
        conn,
        "INSERT INTO resources (title, detail, kind, kind_label, tel, reviewer, approved_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        fresh,
        res_stat,
    )


def _executemany(conn: sqlite3.Connection, sql: str, seq: list[tuple], stat: dict[str, Any]) -> None:
    if not seq:
        return
    cur = conn.executemany(sql, seq)
    stat["inserted"] += cur.rowcount


def _count_ro(db_path: Path, table: str) -> int:
    """dry_run 专用：只读连接数既有行数；库或表不存在返回 0（首次迁移）。"""
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 -- 表名取自常量表
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _audit_detail(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "dry_run": summary["dry_run"],
        "sources": {
            name: {k: v for k, v in stat.items() if k in ("read", "inserted", "skipped", "orphans")}
            for name, stat in summary["sources"].items()
        },
        "archived": list(summary["archived"]),
    }


def _archive(path: Path) -> str:
    """原文件改名为 <name>.bak（已存在则 .bak.1/.bak.2 递增），只读归档不删除。"""
    target = path.with_name(path.name + ".bak")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.bak.{n}")
        n += 1
    path.replace(target)
    return target.name
