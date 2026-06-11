"""Celery 任务薄包装。每个任务自建 async 会话与客户端，asyncio.run 调用
`app/services/jobs/*` 的 async 实现。**绝不**复用 FastAPI 请求会话。"""
