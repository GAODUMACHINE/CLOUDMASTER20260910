# PR: feat(mail): v1.3.0 邮件收发（SMTP + IMAP）+ 注册邮箱 + 报告二次确认（ADR-009）

> 分支：`feature/v1.1.0-online-model`（本地，**未推送**）　目标：`main`
> 约束：沿用云朵玻璃 v1.3 视觉体系与 Qwen 接入方式；不回退 ADR-001 State 契约。

## 背景

v1.2.0 之前**邮件只有 HITL 闸门、没有收发实现**（核查结论）：

| 项 | 核查结果 |
| --- | --- |
| 发信 | `server.py` 传 `Mailer()` → `_channel is None` → **连发送动作都不执行**；全仓 `smtplib/EmailMessage` 零命中 |
| 收信 | 全仓 `imaplib/imap/pop3` 零命中，**完全不存在** |
| 注册邮箱 | `ALLOWED_FIELDS` 无 `email`，报告「发至注册邮箱」在数据上不可达 |
| 前端 | `/api/email/confirm` 从未被调用，是孤立端点 |

即计划书 3.1.3-8「年龄与邮箱」、P1「报告经确认后发至注册邮箱」、TC-REPORT-001 均无法执行。

## 变更内容

### 1. 发信：真实 SMTP（`lightcloudmaster/mailer.py`）
- `SmtpChannel`（标准库 `smtplib`）：`ssl`(465，默认) / `starttls`(587) / `plain`(仅本地调试)；
  支持 `formataddr` 显示名、`Message-ID`、UTF-8 正文。
- 网络/认证失败抛 `MailError`，**绝不静默**；
- **语义收紧（重要）**：`Mailer()` 无通道时 `enabled=False`，`send()` 抛错、
  `send_if_confirmed()` 返回 `sent=False` 并说明「未配置 SMTP_*」。
  原实现无通道仍返回 `sent=True`（假装成功）——这是本轮修掉的一个真实隐患。
- 发送台账只留 `to/subject/sent_at/message_id`，**不落正文**（单测锁定）。

### 2. 收信：真实 IMAP（`lightcloudmaster/inbox.py`）
- `parse_message()` **纯函数**：bytes → 结构化来信，完全离线可测；
- 分类：`reply`（主题含 `[RP-xxxx]`/`[HR-xxxx]` → 归属报告/工单）、`bounce`（退信）、`auto`（自动回复）、`other`；
- **只取 `text/plain`、跳过附件**，正文截断 2000 字后才入库；
- `STOP`/`退订` 等 → 按发件地址回查匿名标识并置 `report_opt_in=False`；
- `ImapInbox` 只拉 `UNSEEN` 并标记已读；连接/认证失败抛 `InboxError`（接口 → 502）。

### 3. 报告生成（`lightcloudmaster/report.py`）
- `build_report()` 纯函数：会话轮次、风险分级、时长守护、**引用来源标题**、建议动作、免责声明；
- **绝不含对话原文**（`contains_raw_conversation=False` + 单测锁定原话不出现）；
- 编号 `RP-xxxxxx` 写入主题，供收信侧归属回信。

### 4. 接口（`lightcloudmaster/web_app.py`）
| 接口 | 说明 |
| --- | --- |
| `GET /api/report/{key}` | 生成**草稿**（内存，不发送），返回绑定「匿名标识+报告编号」的 `confirm_token` |
| `POST /api/report/send` | 二次确认后发送；令牌 `compare_digest` + 未退订 + 通道就绪；重复投递 → 409 |
| `GET /api/report/status/{key}` | 投递邮箱、通道就绪、已发送记录 |
| `POST /api/report/unsubscribe|resubscribe/{key}` | 退订 / 重新开启 |
| `POST /api/inbox/poll?token=` | 拉取来信入库 + 处理退订（须审核台令牌） |
| `GET /api/inbox?token=` | 来信台账 |
| `GET /api/review/{ticket}` | 审核台新增 `replies`：该工单的邮件回信 |

### 5. 注册邮箱（`registration.py` / `profile_store.py`）
- 白名单**唯一新增个人信息字段** `email`（属最小必要的例外，ADR-009 备查）+ `report_opt_in`；
- 必填 + 格式校验（拒绝无顶级域/空格/连续点等）；配套**可查看/可删除/可退订**。

### 6. 前端（沿用既有视觉体系）
- 注册页新增邮箱输入 + 实时格式校验（格式错即禁用提交）；
- 设置面板新增「疏导报告」区：**生成预览 → 阅读 → 点确认发送**（真实二次确认，
  发送前 `confirm` 明确告知投递邮箱）；通道未配置时如实提示；
- `fieldName()` 补充 email/监护人信号的中文错误名。

### 7. 配置与测试
- `.env.example` / `docs/run-local.md`：`SMTP_*` / `IMAP_*` 完整说明（含 QQ/Outlook 示例与授权码提醒）；
- `server.py`：`build_mailer()` / `build_inbox()` 按配置组装，未配置即关闭通道。
- 新增测试：`test_mailer.py`(9) / `test_inbox.py`(9) / `test_report.py`(9) /
  `test_mail_store.py`(6) / `test_mail_flow.py`(23 集成) / `test_registration.py` 扩充邮箱用例 /
  `test_compliance.py` TC-COMP-009（邮箱最小必要与退订）。

## 验证结果（全部 exit 0）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Lint | `ruff check .` / `ruff format --check .` | All checks passed / 96 files already formatted |
| 单测+集成 | `pytest` | **239 passed**, 2 deselected |
| 安全回归（含合规） | `pytest -m safety` | **34 passed** |
| 评估集 | `pytest -m eval` | 2 passed |
| 前端语法 | `node --check frontend/common/api.js` | exit 0 |
| 端到端（`CM_STUB=1`，不触网） | TestClient 真实 app | 见下 |

端到端实测（真实 app）：静态页 200 且邮箱/报告容器就位；注册缺邮箱 → 400、格式错 → 400；
报告草稿含 `recipient` 且 `contains_raw_conversation=False`；未配置 SMTP 时确认发送
**如实返回 `sent=False` 并说明未配置**；错误令牌 → 403；退订后 `opt_in=False`；
未配置 IMAP 时 `/api/inbox/poll` 在令牌校验后返回 503。

## 启用方式（需你填入凭据）

`.env` 中填 `SMTP_HOST/PORT/USER/PASSWORD`（QQ 用 `smtp.qq.com:465` + 授权码；
Outlook 用 `smtp-mail.outlook.com:587` + `SMTP_SECURITY=starttls`），
收信再填 `IMAP_*`。**未填则通道关闭且如实报错，不会假装发送。**

## 明确不在本次范围（ADR-009 待办）

- 定时自动拉取（当前为手动调用 `/api/inbox/poll`）与报告定时推送；
- 真实向量检索与知识库版本化、长程画像与主动回访、监护人查询页；
- 监护人/紧急联系人**联系方式**采集（仍只保留布尔可用信号，不采集邮箱或电话）。