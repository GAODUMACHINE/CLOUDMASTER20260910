# PR：feat(memory): v0.2.0 会话记忆——持久化 Checkpointer + 最小 Profile Store（ADR-002）

> 分支：`feature/v0.2.0-session-memory`　目标：`main`（本会话已授权跳过远端 push，待配置远端后开 PR，squash merge）

## 变更内容
- **ADR-002 先评审后编码**：`docs/adr/ADR-002-session-memory.md`。
- `lightcloudmaster/persistence.py`：文件后备 SqliteSaver（默认 `data/private/lightcloudmaster.sqlite3`，`MEMORY_DB_PATH` 可覆盖），按 thread 跨刷新/跨天接续。
- `lightcloudmaster/profile_store.py`：最小画像 Store（文件后备 JSON），字段白名单（age/is_minor/guardian_contact_available/emergency_contact_available/dependency_tendency），未知字段一律拒绝；get/put/delete/clear_all——可查看、可清除。
- `lightcloudmaster/service.py`：服务层注入 `user_profile`（图内只读），可更新画像并持久化。
- 记忆不混用：Store 只存「这个用户」，心理知识/引用归 knowledge（v0.4.0 接入）。
- ADR-001 State 字段表未增改（仅新增持久化层与注入点）。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | tests/unit/test_profile_store.py | 白名单拒绝/类型校验/get·put·delete·clear_all/跨实例持久化 |
| integration | tests/integration/test_memory.py | turn_count 按 thread 接续、新 thread 重置、同一库文件跨实例接续、service 注入与持久化画像 |

## 自测结果摘要（`make pre` 全绿）
- `ruff check .`：通过；`ruff format --check .`：通过。
- `pytest -q`：**41 passed**（v0.1 30 + v0.2 新增 11）。
- `pytest -m safety -q`：**3/3**（高危召回=1.0，漏检=0）。

## TC 覆盖说明
- 跨天接续（刷新/次日继续）→ 对应会话记忆 milestone TC-*（ADR-002）。
- 画像最小化 + 可清除 → 隐私/可清除合规（§4.3 记忆）。

## 红线核对
- `.env` 未入库；SQLite/画像文件落在 gitignore 的 `data/private/`，测试用 tmp_path 不入仓。
- 全部 fake LLM，零触网；守卫顺序未改动。
- 本地 git 配置（无 --global/--system）。

## 待办
- 待配置远端后 `git push -u origin feature/v0.2.0-session-memory` 并开 PR（squash merge）。