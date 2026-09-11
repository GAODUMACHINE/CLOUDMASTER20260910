# CLOUDMASTER

面向 18-25 岁青年的 AI 心理陪伴与疏导助手——只做支持性陪伴、心理科普、资源转介与情绪疏导，**永远不做诊断、治疗与用药建议**。

## 快速自测

```bash
make pre        # ruff check . && ruff format --check . && pytest -q
pytest -m safety -q   # 危机场景回归（改过词表/prompt/危机逻辑时必跑）
```

## 开发约定

### 分支
- 开发一律在 `feature/<类型>/<issue编号>-<短名>` 分支上进行，禁止直推 `main`。
- 仓库初始化后的首个基线提交是唯一允许的一次 `git push -u origin main`。

### 提交（Commit）
- 一行式：`<type>(<scope>): <做了什么>`
- type = `feat|fix|docs|test|refactor|chore`
- scope = `agent|tools|prompts|rag|api|ci|docs`
- 一个 commit 一件事；禁止使用 `update` / `fix bug` 这类含糊信息。

### 合并
- 仅接受 PR squash merge，合并后删远端分支。

## 目录结构

```
cloudmaster/          # 主包
tests/unit/           # 单测（零外部依赖）
tests/integration/    # 集成（fake LLM 走完整图）
tests/safety/         # 危机场景回归（失败禁止合并）
tests/eval/           # 慢速评估（日常不跑）
docs/eval/            # 评估报告归档
```

## 身份
`user.name` / `user.email` 于仓库本地配置，可自行修改。