"""统一存储层（v2.0.0）：SQLite business.db，唯一碰盘层（checkpoint 库除外）。

DAL 与旧 JSON/JSONL store 公开方法 1:1（调用方零改动切换）：
- profiles.ProfileStore   ← cloudmaster/profile_store.py
- privacy.PrivacyStore    ← cloudmaster/privacy.py（PrivacyStore 部分）
- reviews.ReviewLedger    ← cloudmaster/review_queue.py
- appeals.AppealStore     ← cloudmaster/appeals.py
- resources.ResourceStore ← cloudmaster/resources.py
- inbox.InboxStore        ← cloudmaster/mail_store.py（InboxStore 部分）
- reports.ReportRegistry  ← cloudmaster/mail_store.py（ReportRegistry 部分）

v2.0.0 新增能力（无旧模块对应）：
- agreements.AgreementStore  注册协议签署留痕（P4，《办法》第 12 条）
- followups.FollowupQueue    次日温和回访队列（P7，ADR-011 §5）

旧模块自 v2.0.0 P3 起改为薄壳再导出（唯一实现归本包，既有 import 与 246 例测试不破；
迁移窗口见 scripts/migrate_json_to_sqlite.py）。
"""
