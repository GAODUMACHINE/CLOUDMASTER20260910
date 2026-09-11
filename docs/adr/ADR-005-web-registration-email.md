# ADR-005：Web/注册/未成年人/流式/邮件（v0.5.0）

- 状态：评审通过（v0.5.0-web）
- 日期：2026-09-10
- 里程碑：v0.5.0
- 关联：§1 红线（<14岁数据处理禁止）、§4.3 数据（随机ID/年龄/邮箱，未成年另加监护人/紧急联系人）、
  产品 HITL（邮件须前端二次确认，拒绝则不发送）

## 决策
### 1. Web 服务（FastAPI）
- `cloudmaster/web_app.py`：FastAPI 应用，托管：`POST /api/chat`（单轮）、`POST /api/chat/stream`（SSE 流式）、
  `POST /api/register`（注册年龄门）、`POST /api/email/confirm`（邮件 HITL 确认/拒绝）。
- 后端经 `service` 驱动持久化图；一律注入 fake LLM 供测试，禁止触网。

### 2. 注册年龄门（§1 红线：<14 岁数据处理禁止）
- `/api/register` 拒绝 age<14（400 语义错误），不创建档案、不落库任何该用户数据。
- 通过者仅采集最小画像（随机匿名ID/年龄/邮箱白名单字段，ADR-002）；未成年(age<18)额外要求
  guardian_contact_available 表示监护人可用信号（不采集真实联络，测试用档案 A1~A7）。

### 3. 未成年人分支
- profile.is_minor=True 时：时间守卫走 50/60 分钟阈值（time_guard 已有）；仅提供审核台核发的
  求助资源转发，不含任何未审核热线号码。

### 4. 流式 SSE
- `/api/chat/stream`：用 graph.stream 逐 token/消息以 text/event-stream 输出；fake LLM 下确定性。

### 5. 邮件 HITL（产品级二次确认）
- `cloudmaster/mailer.py`：Mailer 只有在提供已确认决策(approve+confirm_token)时才会 send；reject → 不 send、
  无调用记录（不写审计）。测试一律 fake 通道（记于内存，不真发）。

## 后果
- 正向：<14 强拒、未成年单独兜底、邮件 HITL；红线/数据最小化落实。
- 约束：任何真实邮件中继/SMS/热线号码禁止；测试全 fake；新增模块不留 State 字段（无需改 ADR-001）。