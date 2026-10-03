"""定时任务执行器（v2.0.0 P7，ADR-011 §6）：保留期真删除与回访交付。

边界（取舍）：
- 均为幂等纯函数式入口（run_purge / run_due），由运维手动或外部调度触发——本系统
  **不引入后台线程/调度器依赖**（零新增依赖红线；uvicorn 单进程内起线程会制造
  测试不可控的副作用）。示例：Windows 计划任务每日跑
  `python -c "from lightcloudmaster.jobs.purge import run_purge; ..."`。
- 每次执行经 DAL 落审计（purge_executed / data_deleted 等，audit_events append-only），
  「到期删除」从只算时间（旧版 purge_schedule）变为可验证的执行事实。
"""
