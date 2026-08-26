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
from app.services import canonical_markdown
from app.services.storage import LocalFileStorage

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
    directory_rule_version: int | None = None


ConfirmationRoute = ValidatedConfirmationContext | IngestConfirmResponse


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"denied_reason": reason, "message": message},
    )


def apply_authoritative_project_subject(
    request: IngestConfirmRequest,
    result: RenderedNaming | None,
) -> IngestConfirmRequest:
    """Apply the server-rendered project subject to every persisted request field."""
    if result is None or request.target_scope != KnowledgeScope.project:
        return request
    subject = result.metadata["subject"]
    naming = request.naming
    if naming is not None:
        naming = naming.model_copy(update={"subject": subject})
    return request.model_copy(update={"title": subject, "naming": naming})


def require_naming_warning_acknowledgement(
    request: IngestConfirmRequest,
    result: RenderedNaming | None,
) -> None:
    """Require an explicit decision for server-recomputed soft warnings."""
    if result is None:
        return
    warning_codes = {notice.code for notice in result.notices}
    acknowledged = set(request.acknowledged_naming_warning_codes)
    missing = sorted(warning_codes - acknowledged)
    if missing:
        raise _denied(
            409,
            "naming_warning_acknowledgement_required",
            "存在命名或重复风险提示，请核对后选择仍然确认入库",
        )


async def validate_and_route_confirmation(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    request: IngestConfirmRequest,
    trace_id: str,
    *,
    storage: LocalFileStorage,
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
            .options(
                selectinload(IngestTask.ai_result),
                selectinload(IngestTask.canonical_markdown),
            )
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
    if not canonical_markdown.task_markdown_is_valid(storage, task.canonical_markdown):
        raise _denied(
            409,
            "canonical_markdown_not_ready",
            "规范文本尚未生成，请等待处理完成或重试",
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
        target_project_id = request.target_project_id
        if target_project_id is None:
            raise _denied(422, "target_project_required", "项目入库必须指定目标项目")
        if target_project_id not in caller.active_project_ids:
            raise _denied(
                403,
                "project_membership_required",
                "需为目标项目的有效成员",
            )
        # Validate the published naming facts before creating a review snapshot.
        # The project code is resolved from server configuration, never the request.
        from app.services import naming_rules

        naming_result = await naming_rules.render(
            session,
            caller,
            task,
            NamingPreviewRequest(
                target_scope=request.target_scope,
                target_project_id=target_project_id,
                confidentiality_level=request.confidentiality_level,
                naming=request.naming,
            ),
        )
        require_naming_warning_acknowledgement(request, naming_result)
        request = apply_authoritative_project_subject(request, naming_result)
        directory_key = (
            naming_result.metadata.get("directory_key")
            if naming_result is not None
            else request.naming.directory_key
            if request.naming is not None
            else request.directory_key
        )
        if not directory_key:
            raise _denied(422, "directory_required", "请选择一个正式项目目录")
        from app.services.directories import validate_directory

        await validate_directory(
            session,
            directory_key=directory_key,
            scope=scope,
            project_id=target_project_id,
        )
        can_self_confirm = (
            caller.active_project_roles.get(target_project_id) == ProjectRole.project_manager.value
        )
        if not can_self_confirm:
            from app.services.review_ingest_commands import create_or_get_project_ingest_review

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

    from app.services.directories import validate_directory

    directory_key = (
        request.naming.directory_key if request.naming is not None else request.directory_key
    )
    directory_rule_version: int | None = None
    if not directory_key and scope == KnowledgeScope.personal.value:
        raise _denied(422, "directory_required", "请选择一个正式个人目录")
    if directory_key:
        directory_rule_version, _directory = await validate_directory(
            session,
            directory_key=directory_key,
            scope=scope,
            project_id=project_id,
        )
        if directory_key == "personal.pending":
            raise _denied(
                422,
                "personal_pending_not_formal",
                "个人待处理目录不能作为正式入库目录",
            )

    return ValidatedConfirmationContext(
        task=task,
        request=request,
        scope=scope,
        owner_id=owner_id,
        project_id=project_id,
        caller=caller,
        trace_id=trace_id,
        session=session,
        directory_rule_version=directory_rule_version,
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
    require_naming_warning_acknowledgement(context.request, result)
    directory_key = (
        result.metadata.get("directory_key")
        if result is not None
        else context.request.naming.directory_key
        if context.request.naming is not None
        else context.request.directory_key
    )
    if not directory_key:
        raise _denied(422, "directory_required", "请选择一个正式入库目录")
    from app.services.directories import validate_directory

    directory_rule_version, _directory = await validate_directory(
        context.session,
        directory_key=directory_key,
        scope=context.scope,
        project_id=context.project_id,
    )
    # Governed project subject is authoritative for the asset title, review
    # snapshot, naming facts, and canonical filename, including direct callers.
    request = apply_authoritative_project_subject(context.request, result)
    return replace(
        context,
        request=request,
        naming_result=result,
        directory_rule_version=directory_rule_version,
    )
