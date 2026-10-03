# PR: feat(web): v0.5.0 Web+注册年龄门+未成年人+流式SSE+邮件HITL（ADR-005）

> 分支：`feature/v0.5.0-web`　目标：`main`（本会话授权跳过远端 push）

## 变更内容
- ADR-005（先评审）：Web/注册/未成年人/流式/邮件契约。
- `lightcloudmaster/registration.py`：注册年龄门——<14 岁强拒（红线不处理该数据），仅采最小画像白名单；未成年须声明监护人可用信号。
- `lightcloudmaster/mailer.py`：邮件 HITL 二次确认——未确认/令牌不符绝不发送，拒绝→不发送且无调用记录。
- `lightcloudmaster/web_app.py`：FastAPI——POST /api/register、/api/chat、/api/chat/stream(SSE)、/api/email/confirm。
- 未成年人走 time_guard 50/60 阈值；无任何真实热线号码/真实 SMTP（测试全 fake）。

## 测试计划
| 层 | 文件 | 覆盖 |
|---|---|---|
| unit | test_registration.py | <14 拒绝、未成年需监护人、成人最小画像 |
| unit | test_mailer.py | approve+令牌发送 / reject 不发送无记录 / 令牌不符不发送 |
| integration | test_web_api.py | register 年龄门、chat、SSE 流式、email HITL approve/reject |

## 自测摘要（make pre 全绿）
ruff ✓　format ✓　pytest：65 passed　pytest -m safety：4/4（漏检=0）

## 红线核对
<14 强拒；无真实热线/SMS/邮箱外部调用（全 fake）；守卫顺序未改；最小画像仅白名单；密钥/库文件未入库。

## 待办
远端配置后 `git push -u origin feature/v0.5.0-web` 并开 PR（squash merge）。