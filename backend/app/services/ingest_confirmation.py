"""Server-authoritative validation and routing for ingest confirmation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingest import IngestTask
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    IngestStatus,
    KnowledgeScope,
    ProjectRole,
)
from app.schemas.ingest import IngestConfirmRequest, IngestConfirmResponse
from app.schemas.naming import NamingPreviewRequest
from app.schemas.permission import CallerContext
from app.services import audit as audit_service

if TYPE_CHECKING:
    from app.services.naming_rules import RenderedNaming


@dataclass(frozen=True, slots=True)
class ValidatedConfirmationContext:
    """Confirmation input after all target and caller checks have succeeded."""

    task: IngestTask
    request: IngestConfirmRequest
    scope: str
    owner_id: uuid.UUID
    project_id: uuid.UUID | None
    caller: CallerContext
    trace_id: str
    session: AsyncSession
    naming_result: RenderedNaming | None = None


ConfirmationRoute = ValidatedConfirmationContext | IngestConfirmResponse


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"denied_reason": reason, "message": message},
    )


async def validate_and_route_confirmation(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    request: IngestConfirmRequest,
    trace_id: str,
) -> ConfirmationRoute:
    """Validate source locks and destination authority, then route review if needed."""
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "ingest.confirm",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可确认入库")

    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == task_id)
            .options(selectinload(IngestTask.ai_result))
        )
    ).scalar_one_or_none()
    if task is None:
        raise _denied(404, "ingest_task_not_found", "入库任务不存在")

    if not (task.created_by == caller.user_id or caller.can_discover_l5):
        raise _denied(
            403,
            "ingest_confirm_forbidden",
            "只有任务创建人或业务治理角色可确认入库",
        )
    if task.result_asset_id is not None or task.status == IngestStatus.completed.value:
        raise _denied(
            409,
            "ingest_already_confirmed",
            "该入库任务已确认，不可重复确认",
        )
    if task.status == IngestStatus.processing.value:
        raise _denied(
            409,
            "ingest_processing_not_ready",
            "后台仍在处理该上传，请稍后再确认",
        )
    if not (request.title or "").strip():
        raise _denied(422, "ingest_title_required", "标题不能为空")
    if not (request.summary or "").strip() and not (request.one_liner or "").strip():
        raise _denied(
            422,
            "ingest_summary_required",
            "至少需填写详细摘要或一句话摘要",
        )

    scope = request.target_scope.value
    if task.target_scope is not None and task.target_scope != scope:
        raise _denied(
            409,
            "ingest_target_locked",
            "入库目标已由来源规则锁定，不能更改",
        )
    if (
        task.target_scope == KnowledgeScope.project.value
        and task.target_project_id != request.target_project_id
    ):
        raise _denied(
            409,
            "ingest_target_project_locked",
            "目标项目已由来源规则锁定，不能更改",
        )

    if scope == KnowledgeScope.personal.value:
        owner_id = caller.user_id
        project_id = None
    elif scope == KnowledgeScope.project.value:
        if request.target_project_id is None:
            raise _denied(422, "target_project_required", "项目入库必须指定目标项目")
        if request.target_project_id not in caller.active_project_ids:
            raise _denied(
                403,
                "project_membership_required",
                "需为目标项目的有效成员",
            )
        # Validate the published naming facts before creating a review snapshot.
        # The project code is resolved from server configuration, never the request.
        from app.services import naming_rules

        await naming_rules.render(
            session,
            caller,
            task,
            NamingPreviewRequest(
                target_scope=request.target_scope,
                target_project_id=request.target_project_id,
                confidentiality_level=request.confidentiality_level,
                naming=request.naming,
            ),
        )
        can_self_confirm = (
            caller.active_project_roles.get(request.target_project_id)
            == ProjectRole.project_manager.value
        )
        if not can_self_confirm:
            from app.services.review import create_or_get_project_ingest_review

            review = await create_or_get_project_ingest_review(
                session,
                caller,
                task,
                request,
                trace_id,
            )
            return IngestConfirmResponse(
                task_id=task.id,
                status=IngestStatus.waiting_review.value,
                result_asset_id=None,
                review_id=review.id,
                index_status=None,
            )
        owner_id = caller.user_id
        project_id = request.target_project_id
    elif scope == KnowledgeScope.company.value:
        if not caller.can_discover_l5:
            raise _denied(
                403,
                "company_confirmation_requires_governance",
                "公司知识需总经理或咨询总监确认",
            )
        from app.services.company_kb import require_company_kb_ready

        await require_company_kb_ready(session)
        owner_id = caller.user_id
        project_id = None
    else:
        raise _denied(422, "invalid_target_scope", "非法的 target_scope")

    return ValidatedConfirmationContext(
        task=task,
        request=request,
        scope=scope,
        owner_id=owner_id,
        project_id=project_id,
        caller=caller,
        trace_id=trace_id,
        session=session,
    )


async def apply_confirmation_extensions(
    context: ValidatedConfirmationContext,
) -> ValidatedConfirmationContext:
    """Render canonical naming from the published server policy after authorization."""
    from app.services import naming_rules

    result = await naming_rules.render(
        context.session,
        context.caller,
        context.task,
        NamingPreviewRequest(
            target_scope=context.request.target_scope,
            target_project_id=context.request.target_project_id,
            confidentiality_level=context.request.confidentiality_level,
            naming=context.request.naming,
        ),
    )
    return replace(context, naming_result=result)
