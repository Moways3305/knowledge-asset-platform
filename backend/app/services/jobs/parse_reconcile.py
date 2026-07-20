"""WeKnora 解析状态对账作业。

扫描 active 版本中 weknora_parse_status 仍处于 pending/processing 的文档，调
`WeKnoraClient.get_knowledge` 回写**安全业务解析状态**。

要求：
- 只更新安全业务字段 `weknora_parse_status`；**绝不**暴露/审计 weknora kb/doc id。
- 单条失败不影响整批（逐条 try/except，continue）。
- 幂等、可重跑：只动 pending/processing 的版本，终态（completed/failed/duplicate）不再碰。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAssetVersion
from app.schemas.enums import VersionStatus
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraError,
    weknora_enabled,
)

# 仍需对账的解析状态（未达终态）。
_PENDING_STATUSES = {"pending", "processing"}
_TERMINAL = {"completed", "failed", "duplicate"}


async def reconcile_parse_statuses(
    session: AsyncSession,
    weknora: WeKnoraClient | NullWeKnoraClient,
    *,
    trace_id: str | None = None,
    limit: int = 200,
) -> dict:
    """对账一批 pending/processing 版本的解析状态。返回安全计数（无 kb/doc id）。"""
    if not weknora_enabled():
        # 未配置底座：无可对账项，安全空跑。
        return {"processed": 0, "updated": 0, "failed": 0, "skipped": "weknora_not_configured"}

    rows = list(
        (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.version_status == VersionStatus.active.value)
                .where(KnowledgeAssetVersion.weknora_doc_id.is_not(None))
                .where(KnowledgeAssetVersion.weknora_parse_status.in_(_PENDING_STATUSES))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    processed = updated = failed = 0
    for v in rows:
        # 查询已过滤 weknora_doc_id IS NOT NULL（见上方 where），此处必非 None。
        if v.weknora_doc_id is None:
            continue
        try:
            data = await weknora.get_knowledge(v.weknora_doc_id, trace_id=trace_id)
        except WeKnoraError:
            # 单条失败不中断整批。
            failed += 1
            continue
        processed += 1
        new_status = str(data.get("parse_status") or v.weknora_parse_status)
        if new_status != v.weknora_parse_status and new_status in (_TERMINAL | _PENDING_STATUSES):
            v.weknora_parse_status = new_status
            updated += 1
    await session.commit()
    return {"processed": processed, "updated": updated, "failed": failed}
