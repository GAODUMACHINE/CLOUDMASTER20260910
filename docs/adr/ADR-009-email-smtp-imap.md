# ADR-009：邮件收发（SMTP + IMAP）与注册邮箱采集（v1.3.0）

- 状态：评审通过（v1.3.0）
- 日期：2026-09-17
- 关联：ADR-005（注册与邮件 HITL）、ADR-007（匿名身份与申诉）、ADR-008（审核台与隐私保留期）、
  计划书 3.1.3-6/8、3.2.3、3.2.4、3.3.1、P1；`LIGHTCLOUDMASTER20260910-TEST.md` TC-REPORT-001

## 上下文

经逐行核查，邮件在 v1.2.0 之前**只是 HITL 闸门、不是收发实现**：

1. `Mailer.__init__(channel=None)` 的通道注释写「生产可注入 SMTP 通道；缺省为内存桩」，
   而 `server.py` 传的就是 `None` → `_channel is None` → **连发送动作都不会执行**；
   全仓 `smtp|smtplib|EmailMessage|MIMEText` **零命中**。
2. **没有任何收信能力**（`imaplib|imap|pop3` 零命中）。
3. **未采集注册邮箱**：`profile_store.ALLOWED_FIELDS` 无 `email` 字段，
   因此计划书「报告发至注册邮箱」在数据上不可达。
4. **前端零邮件入口**：`/api/email/confirm` 从未被前端调用，是孤立端点。

即：计划书 3.1.3-8「年龄与邮箱」、P1「阶段性报告经确认后发至注册邮箱」、
TC-REPORT-001「发送前出现前端二次确认」均无法执行。

## 决策

1. **发信：标准库 `smtplib` 真实通道**（`lightcloudmaster/mailer.py`）。
   `SmtpChannel` 支持 `ssl`（465，默认）/ `starttls`（587）/ `plain`（仅本地调试）；
   网络或认证失败抛 `MailError`，**绝不静默吞掉**，避免「未送达」被当成成功。
2. **未配置通道绝不假装成功**：`Mailer()` 无通道时 `enabled=False`，`send()` 抛错，
   `send_if_confirmed()` 返回 `sent=False` 并说明「未配置 SMTP_*」。
   这是对原内存桩语义的**收紧**（原实现返回 `sent=True` 却什么都没发）。
3. **收信：标准库 `imaplib`**（`lightcloudmaster/inbox.py`）。
   - `parse_message()` 为**纯函数**（bytes → 结构化来信），可完全离线单测；
   - 只取 `text/plain`、**跳过附件**、正文截断 2000 字后才入库；
   - 分类 `reply` / `bounce` / `auto` / `other`；主题含 `[RP-xxxx]`/`[HR-xxxx]` 即归属报告或工单；
   - 正文含 `STOP`/`退订` → 按发件地址回查匿名标识并置 `report_opt_in=False`。
4. **报告生成与发送分离**（`lightcloudmaster/report.py`）：
   `build_report()` 为纯函数，**只输出聚合信息与建议，绝不含对话原文**
   （`contains_raw_conversation=False`，并有单测锁定）；报告编号 `RP-xxxxxx` 写入主题，
   作为收信侧回信归属依据。
5. **发送是产品级 HITL**：`GET /api/report/{key}` 只生成草稿（不落盘、只存内存），
   返回绑定「匿名标识 + 报告编号」的 `confirm_token`；`POST /api/report/send` 须
   令牌 `compare_digest` 相符 + 未退订 + 通道就绪才发送；同一报告**不可重复投递**（409）。
6. **采集注册邮箱——明确的最小必要例外**：
   - 计划书 3.2.4 要求「不采集姓名/学号/手机号」，而报告必须要有投递地址，
     故 `email` 是白名单中**唯一新增的个人信息字段**，并写入 ADR 备查；
   - 必填且做格式校验（`registration.valid_email`，拒绝空格/无顶级域/连续点等）；
   - 配套「可查看（`/api/privacy/{key}/export`）、可删除（`DELETE /api/profile/{key}`）、
     可退订（`report_opt_in`）」三项控制，满足最小化 + 可删除 + 可审计；
   - **不采集**监护人/紧急联系人的邮箱或电话（仍只保留布尔可用信号）。
7. **收信接口须审核令牌**：`/api/inbox/poll`、`/api/inbox` 复用 ADR-008 的审核台令牌，
   未授权一律 403；IMAP 未配置返回 503，认证/网络失败返回 502（不静默返回空）。
8. **凭据全部经环境变量/.env 注入**（`SMTP_*` / `IMAP_*`），gitignored、零硬编码。

## 后果

- 正向：补齐计划书 3.1.3-8、P1 与 TC-REPORT-001；邮件从「HITL 空壳」变为可用收发链路；
  审核台可直接看到针对工单的邮件回信。
- 约束：
  - `data/private/inbox.jsonl` 含来信正文（已截断），与其它私密数据同等保护、gitignored；
  - SMTP/IMAP 授权码属高敏感凭据，只存本机 `.env`；
  - 发送台账不落正文，只留地址/主题/时间/消息号。
- 待办（明确不在本次范围）：
  - 真实向量检索与知识库版本化（仍为 `StubRetriever`，ADR-004 契约不变）；
  - 定时自动拉取（当前为手动/运维调用 `/api/inbox/poll`）与报告定时推送；
  - 监护人查询使用概况页、长程画像（Store）与主动回访调度。