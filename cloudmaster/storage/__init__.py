"""统一存储层（v2.0.0）：SQLite business.db，唯一碰盘层（checkpoint 库除外）。

DAL 与旧 JSON/JSONL store 公开方法 1:1（调用方零改动切换）：
- profiles.ProfileStore   ← cloudmaster/profile_store.py
- privacy.PrivacyStore    ← cloudmaster/privacy.py（PrivacyStore 部分）
- reviews.ReviewLedger    ← cloudmaster/review_queue.py
- appeals.AppealStore     ← cloudmaster/appeals.py
- resources.ResourceStore ← cloudmaster/resources.py
- inbox.InboxStore        ← cloudmaster/mail_store.py（InboxStore 部分）
- reports.ReportRegistry  ← cloudmaster/mail_store.py（ReportRegistry 部分）

旧模块只读保留至 P3 删除（迁移窗口见 scripts/migrate_json_to_sqlite.py）。
"""
