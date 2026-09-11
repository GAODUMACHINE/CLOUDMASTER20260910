# PR: feat(web): 前端两种视觉风格（soft-pastel / cloud-glass）+ 静态托管

> 分支：`feature/frontend-web`　目标：`main`（建议先合并 v0.1→v1.0 各 feature PR 后再以此为基础）。本会话授权跳过远端 push。

## 变更内容
- `docs/design/visual-styles.md`：15 种心理辅导视觉风格设计文档。
- `frontend/common/api.js`：共享逻辑——注册年龄门(<14 强拒/未成年需监护人信号)、/api/chat 调用、
  打字机流式观感(支持 prefers-reduced-motion)、危机(L2)→人工审核横幅(不放真实热线)、AI 标识+匿名隐私。
- `frontend/soft-pastel/`：风格一「柔雾奶油」index.html + style.css（雾米/薄荷/暖杏、大圆角、极慢淡入）。
- `frontend/cloud-glass/`：风格二「云朵玻璃」index.html + style.css（毛玻璃、天蓝灰底、轻盈年轻）。
- `cloudmaster/web_app.py`：挂载 `/web` 静态目录(html=True)托管上述页面。
- 新增集成测试：`GET /web/soft-pastel/`、`GET /web/cloud-glass/` 返回 200 并含品牌文案。

## 测试计划
| 层 | 覆盖 |
|---|---|
| integration | static 托管两个风格页返回 200；既有 /api/register、/api/chat、/api/email/confirm 回归不变 |

## 自测摘要（make pre 全绿）
ruff ✓　format ✓　pytest：67 passed（原 65 + 静态页 2）　pytest -m safety：4/4

## 红线核对
前端不放真实热线/不索要真实姓名照片；<14 强拒；未成年监护人信号；AI 生成标识必现；
动效全部支持 reduce-motion；密钥/数据库不入库。本地打开页面时设置 `window.CM_API_BASE` 指向后端即可，
由后端托管时同源(`/api/*`)无需配置。