"""Celery 异步治理作业层（R5）。

把入库处理、WeKnora 解析对账、生命周期归档扫描、跨项目复用/升格推荐从请求路径或
同步占位迁到真实 Celery 作业。仅依赖 Redis/Celery，不引入其它外部系统。

业务逻辑实现在 `app/services/jobs/*`（async、可直接调用、幂等、可测）；本包只放 Celery
应用、任务薄包装与入队工具。
"""
