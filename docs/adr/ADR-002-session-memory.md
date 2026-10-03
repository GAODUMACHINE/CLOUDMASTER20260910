# ADR-002：会话记忆（v0.2.0）——Checkpointer 持久化 + Profile Store 最小画像

- 状态：评审通过（v0.2.0-session-memory）
- 日期：2026-09-10
- 里程碑：v0.2.0（会话记忆）
- 关联：指令 §4.3「记忆」；§8（v0.2.0）

## 上下文
v0.1.0 已在内存 Checkpointer（InMemorySaver）上验证守卫顺序与 L2 中断恢复。v0.2.0 引入
**跨刷新/跨天接续**：Checkpointer 落盘为 SQLite；Profile Store 持久化「这个用户」的最小画像
并默认最小化、可查看可清除。知识库（v0.4.0）答「心理知识」，与用户记忆**不混用**。

## 决策

### 1. 持久化 Checkpointer
- 默认 `data/private/cloudmaster.sqlite3`（相对路径，已 gitignore），可用 `MEMORY_DB_PATH` 环境变量覆盖；
  禁止绝对路径/密钥硬编码。
- 按 thread 持久化：同一 thread 刷新/次日继续，`messages`、`turn_count`、`risk_level` 等随 Checkpoint
  接续（守卫状态如 `usage_meta` 亦随之，保证"当日已收尾不重复、次日恢复"跨会话成立）。
- 测试一律用 pytest `tmp_path` 建临时库文件，不入仓、不触网。

### 2. Profile Store（最小画像，可查看可清除）
- 文件后备 `data/private/profile.json`（同名环境变量 `PROFILE_DB_PATH` 可覆盖）。
- 字段白名单（隐私最小化，未知字段一律拒绝写入）：`age`、`is_minor`、`guardian_contact_available`、
  `emergency_contact_available`、`dependency_tendency`。
- 接口：`get(key)`、`put(key, profile)`（白名单校验）、`delete(key)`（清除）、`has(key)`。
- 服务层读取后注入 `state.user_profile`，**图内只读**（ADR-001 不变）。

### 3. 记忆不混用
- Profile Store 只存「这个用户」；心理知识/引用归 knowledge（citations 唯一写者不变）。
- 不因本次里程碑增改 ADR-001 的 State 字段表（仅新增持久化层与注入点）。

## 后果
- 正向：跨刷新/跨天接续可验证；画像最小化符合隐私与「可清除」要求。
- 约束：任何对记忆字段或数据库 schema 的增改须先 ADR；测试触网/真实模型仍禁止。
- 风险：SQLite 并发写需串行（单连接 + 锁）；v0.2.0 不引入 RAG，向量库留待 v0.4.0。