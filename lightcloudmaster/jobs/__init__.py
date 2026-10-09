"""定时任务执行器：保留期真删除（purge）与回访交付（followups）。

均为幂等纯函数式入口（run_purge / run_due），由运维手动或外部调度触发
（生产经 systemd timer / cron 调 scripts/run_jobs.py）——本系统不引入后台
线程/调度器依赖。每次执行经 DAL 落审计（audit_events append-only），
「到期删除」是可验证的执行事实而非只算时间。
"""
