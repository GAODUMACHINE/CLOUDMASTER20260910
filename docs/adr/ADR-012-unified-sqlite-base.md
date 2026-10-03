# ADR-012：统一 SQLite 底座（v2.0.0 存储层，P1 追记）

- 状态：评审通过（v2.0.0-rewrite P1，落地 commit b89cdda；本 ADR 为 P8 补记）
- 日期：2026-10-02
- 关联：ADR-008（审核台账）、ADR-009（邮件链路）、ADR-011（重写总纲）
- 对应用例：TC-PRIV-002（删除不可恢复）、TC-SEC-001/002、TC-REG-007（协议签署可审计）

## 上下文

v1.x 各业务各持一种持久化：JSON / JSONL / 内存 dict，散落 `data/private/` 多个文件；
写入无事务、无并发控制（单测里靠 tmp_path 隔离，生产并发写同一 JSONL 会互相截断）；
「台账 append-only」「审计不可篡改」只靠约定；进程重启丢内存态（报告发送台账曾为此丢过记录）。
重写 P1 决定全部业务存储收敛到单一 SQLite 底座。

## 决策

### 1. 单库 14 表 + 按文件分连接
`cloudmaster/storage/db.py` 持全部 DDL：`profiles / privacy_settings / agreements / review_cases
（source 列 P1 即预置）/ review_decisions / appeals / appeal_events / inbox_mails /
report_drafts / report_sents / mail_sent_ledger / audit_events / followups / resources`。
每个 DB 文件一个连接 + 一个 `threading.RLock`（同库串行、跨库并行），WAL 模式；
SQL 一律 `?` 参数化，写方法统一 `with lock + commit`。

### 2. 路径解析收口
`resolve_db_path(path, env)`：显式 path → 专属环境变量（如 `INBOX_DB_PATH`）→
`BUSINESS_DB_PATH` → `data/private/business.db`。测试经 conftest 重定向到 tmp，
生产默认单文件；分库部署只需设环境变量，不改代码。

### 3. append-only 用触发器兜底
`audit_events` 上 `BEFORE UPDATE / BEFORE DELETE` 触发器直接 `RAISE(ABORT)`——
「审计不可篡改」从代码约定升级为数据库层约束。`db.record_audit(conn, lock, kind, anon_key, detail)`
是唯一写入口。

### 4. 8 组 DAL 与旧模块薄壳
`profiles / privacy / reviews / appeals / inbox / reports / resources / (+P4 agreements、
P7 followups)` 各自封装 SQL；API 与旧模块逐一对应（如 `ReviewLedger.decide` 保持
「校验 + 决策落库」同事务原子）。旧模块在 P3 起改为再导出薄壳（ADR-011 §1），
既有 246 例用例即为 DAL 回归——不新增测试样例（用户指令，见功能对照表验证记录）。

### 5. 迁移脚本与追溯一致性
`storage/migrate.py` 从旧 JSON/JSONL 一次性入库（dry-run 对账 + 实跑 + 幂等重跑 +
`.bak` 归档 + 坏例如实计入 orphans/skipped），已手动冒烟验证（功能对照表 2026-10-01 记录）。

## 备选与否决
- **保持 JSONL**：零迁移成本，但并发截断/无事务/无约束三条硬伤无法补救；
- **上 PostgreSQL**：并发与约束最强，但引入服务进程与运维面，毕设单人部署场景过重；
- **SQLite（选定）**：标准库自带（零新增依赖）、单文件备份、WAL 下读写不互斥，
  单写者串行对本系统流量量级绰绰有余。

## 后果
- 正向：台账持久化（重启不丢）、审计数据库级不可篡改、保留期真删除有了可靠的执行底座（ADR-011 §6）。
- 约束：单写者串行意味着同库高频写会排队（当前量级无感）；跨库无分布式事务
  （注册三步写经三个 DAL，靠「任一步失败不产生半开账户」的顺序设计，见 services/registration docstring）。
- 待办：量级上来后若需多进程部署，须引入外部队列或改 PostgreSQL（本 ADR 不预设）。
