# PR: chore(eval): v1.0.0 试点 + 安全评估归档（docs/eval + tests/eval）

> 分支：`feature/v1.0.0-pilot`　目标：`main`（本会话授权跳过远端 push）

## 变更内容
- pyproject version=1.0.0；新增 `eval` marker，`addopts = "-m 'not eval'"`（日常不跑慢估，`pytest -m eval` 单独跑）。
- `tests/eval/test_eval_smoke.py`：离线可量化评估——高危召回/误报/路由准确率（A1~A7 虚构档案，fake LLM）。
- `docs/eval/v1.0.0-pilot-safety-report.md`：试点安全/合规/质量/工程评估归档（§7 门禁对照）。

## 自测摘要（make pre 全绿）
ruff ✓　format ✓　pytest：65 passed（eval 2 deselected）　pytest -m eval：2/2　pytest -m safety：4/4（漏检=0）

## 待办/标注「待在线」
共情评分(样本)、首token P95(真实模型压测) 需在线补齐后归档；真实热线资源由人审台人工配置、不预先入库。
远端配置后开 PR（squash merge）。