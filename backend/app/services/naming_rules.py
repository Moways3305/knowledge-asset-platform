"""Published naming policy governance, rendering and safe duplicate notices."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.naming import NamingRuleRevision
from app.schemas.enums import AuditAction, AuditLogType, IngestStatus, KnowledgeScope
from app.schemas.naming import (
    NamingDraftUpdateRequest,
    NamingDuplicateNotice,
    NamingOptionItem,
    NamingOptionsResponse,
    NamingPreviewRequest,
    NamingPreviewResponse,
    NamingPublishRequest,
    NamingRuleCenterOut,
    NamingRuleConfig,
    NamingRuleRevisionOut,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service


@dataclass(frozen=True, slots=True)
class RenderedNaming:
    canonical_name: str
    rule_version: int
    metadata: dict
    notices: list[NamingDuplicateNotice]


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"denied_reason": reason, "message": message})


def _require_governance(caller: CallerContext) -> None:
    if not caller.can_discover_l5:
        raise _denied(403, "naming_rule_governance_required", "仅业务治理角色可管理命名规则")


async def _revision(
    session: AsyncSession, status: str, *, lock: bool = False
) -> NamingRuleRevision:
    stmt = (
        select(NamingRuleRevision)
        .where(NamingRuleRevision.status == status)
        .order_by(NamingRuleRevision.version.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    value = (await session.execute(stmt)).scalar_one_or_none()
    if value is None:
        raise _denied(503, "naming_rule_unavailable", "命名规则暂时不可用")
    return value


async def _ensure_initial_revisions(session: AsyncSession) -> None:
    existing = await session.scalar(select(func.count()).select_from(NamingRuleRevision))
    if existing:
        return
    initial = NamingRuleConfig(enforced=False).model_dump(mode="json")
    session.add_all(
        [
            NamingRuleRevision(
                version=1,
                status="published",
                base_published_version=0,
                config=initial,
            ),
            NamingRuleRevision(
                version=2,
                status="draft",
                base_published_version=1,
                config=initial,
            ),
        ]
    )
    await session.commit()


def _config(revision: NamingRuleRevision) -> NamingRuleConfig:
    try:
        return NamingRuleConfig.model_validate(revision.config)
    except Exception:
        raise _denied(503, "naming_rule_unavailable", "命名规则暂时不可用") from None


def _out(revision: NamingRuleRevision) -> NamingRuleRevisionOut:
    return NamingRuleRevisionOut(
        version=revision.version,
        status=revision.status,
        base_published_version=revision.base_published_version,
        config=_config(revision),
        updated_at=revision.updated_at,
        published_at=revision.published_at,
    )


async def get_rule_center(session: AsyncSession, caller: CallerContext) -> NamingRuleCenterOut:
    _require_governance(caller)
    await _ensure_initial_revisions(session)
    published = await _revision(session, "published")
    draft = await _revision(session, "draft")
    projects = (
        (await session.execute(select(Project).order_by(Project.name, Project.id))).scalars().all()
    )
    return NamingRuleCenterOut(
        published=_out(published),
        draft=_out(draft),
        projects=[
            {
                "id": str(project.id),
                "name": project.name,
                "status": project.status,
                "project_code": project.project_code,
                "project_code_active": project.project_code_active,
                "default_confidentiality": project.naming_default_confidentiality,
            }
            for project in projects
        ],
    )


async def save_draft(
    session: AsyncSession,
    caller: CallerContext,
    request: NamingDraftUpdateRequest,
    trace_id: str,
) -> NamingRuleRevisionOut:
    _require_governance(caller)
    await _ensure_initial_revisions(session)
    published = await _revision(session, "published", lock=True)
    draft = await _revision(session, "draft", lock=True)
    if (
        request.expected_base_version != published.version
        or draft.base_published_version != published.version
    ):
        raise _denied(409, "naming_rule_publish_conflict", "规则已被其他治理者更新，请刷新")
    project_ids = {item.project_id for item in request.config.project_codes}
    existing = set(
        (await session.execute(select(Project.id).where(Project.id.in_(project_ids)))).scalars()
        if project_ids
        else []
    )
    if existing != project_ids:
        raise _denied(422, "naming_rule_project_invalid", "项目代码配置包含不可用项目")
    draft.config = request.config.model_dump(mode="json")
    draft.updated_by = caller.user_id
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.naming_rule_draft_saved.value,
        trace_id=trace_id,
        target_type="naming_rule_revision",
        target_id=draft.id,
        after={
            "version": draft.version,
            "project_code_count": len(request.config.project_codes),
            "category_count": len(request.config.categories),
            "enforced": request.config.enforced,
        },
    )
    await session.commit()
    await session.refresh(draft)
    return _out(draft)


async def publish_draft(
    session: AsyncSession,
    caller: CallerContext,
    request: NamingPublishRequest,
    trace_id: str,
) -> NamingRuleCenterOut:
    _require_governance(caller)
    await _ensure_initial_revisions(session)
    published = await _revision(session, "published", lock=True)
    draft = await _revision(session, "draft", lock=True)
    if (
        request.expected_base_version != published.version
        or draft.base_published_version != published.version
    ):
        raise _denied(409, "naming_rule_publish_conflict", "规则已被其他治理者发布，请刷新")
    config = _config(draft)
    configured_ids = {item.project_id for item in config.project_codes}
    projects = (
        (
            await session.execute(
                select(Project).where(Project.id.in_(configured_ids)).with_for_update()
            )
        )
        .scalars()
        .all()
        if configured_ids
        else []
    )
    if {project.id for project in projects} != configured_ids:
        raise _denied(422, "naming_rule_project_invalid", "项目代码配置包含不可用项目")
    by_id = {project.id: project for project in projects}
    if any(
        item.enabled and by_id[item.project_id].status != "active" for item in config.project_codes
    ):
        raise _denied(422, "naming_rule_project_inactive", "停用项目不能启用项目代码")

    # Clear projections first so two projects can safely exchange unique codes.
    all_projects = (await session.execute(select(Project).with_for_update())).scalars().all()
    for project in all_projects:
        project.project_code = None
        project.project_code_active = False
    await session.flush()
    for item in config.project_codes:
        project = by_id[item.project_id]
        project.project_code = item.code
        project.project_code_active = item.enabled
        project.naming_default_confidentiality = item.default_confidentiality.value

    now = datetime.now(timezone.utc)
    draft.status = "published"
    draft.published_by = caller.user_id
    draft.published_at = now
    await session.flush()
    next_draft = NamingRuleRevision(
        version=draft.version + 1,
        status="draft",
        base_published_version=draft.version,
        config=config.model_dump(mode="json"),
        created_by=caller.user_id,
        updated_by=caller.user_id,
    )
    session.add(next_draft)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.naming_rule_published.value,
        trace_id=trace_id,
        target_type="naming_rule_revision",
        target_id=draft.id,
        after={
            "version": draft.version,
            "project_code_count": len(config.project_codes),
            "category_count": len(config.categories),
            "enforced": config.enforced,
        },
    )
    await session.commit()
    return await get_rule_center(session, caller)


def _extension(file_name: str) -> str:
    suffix = PurePath(file_name).suffix.lower()
    if suffix and len(suffix) <= 11 and suffix[1:].isalnum():
        return suffix
    return ""


async def _duplicate_notices(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    scope: str,
    project_id: uuid.UUID | None,
    metadata: dict,
) -> list[NamingDuplicateNotice]:
    notices: list[NamingDuplicateNotice] = []
    if task.source_file_hash:
        pending_conditions = [
            IngestTask.id != task.id,
            IngestTask.source_file_hash == task.source_file_hash,
            IngestTask.result_asset_id.is_(None),
            IngestTask.status.in_(
                [
                    IngestStatus.pending_confirmation.value,
                    IngestStatus.waiting_review.value,
                    IngestStatus.rejected.value,
                ]
            ),
        ]
        if scope == KnowledgeScope.personal.value:
            pending_conditions.append(IngestTask.created_by == caller.user_id)
        elif scope == KnowledgeScope.project.value:
            pending_conditions.extend(
                [
                    IngestTask.target_scope == scope,
                    IngestTask.target_project_id == project_id,
                ]
            )
        else:
            pending_conditions.append(IngestTask.target_scope == scope)
        pending_match = await session.scalar(
            select(func.count()).select_from(IngestTask).where(*pending_conditions)
        )
        asset_conditions = [
            KnowledgeAsset.scope == scope,
            KnowledgeAsset.asset_status == "active",
            KnowledgeAssetVersion.file_hash == task.source_file_hash,
        ]
        if scope == KnowledgeScope.personal.value:
            asset_conditions.append(KnowledgeAsset.owner_user_id == caller.user_id)
        elif scope == KnowledgeScope.project.value:
            asset_conditions.append(KnowledgeAsset.project_id == project_id)
        confirmed_match = await session.scalar(
            select(func.count())
            .select_from(KnowledgeAssetVersion)
            .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetVersion.asset_id)
            .where(*asset_conditions)
        )
        if pending_match or confirmed_match:
            notices.append(NamingDuplicateNotice(kind="exact", message="已存在相同文件"))

    candidate_stmt = (
        select(KnowledgeAssetVersion.naming_metadata)
        .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetVersion.asset_id)
        .where(KnowledgeAsset.scope == scope, KnowledgeAsset.asset_status == "active")
    )
    if scope == KnowledgeScope.personal.value:
        candidate_stmt = candidate_stmt.where(KnowledgeAsset.owner_user_id == caller.user_id)
    elif scope == KnowledgeScope.project.value:
        candidate_stmt = candidate_stmt.where(KnowledgeAsset.project_id == project_id)
    candidates = (await session.execute(candidate_stmt.limit(500))).scalars().all()
    keys = ("category_id", "subject", "formed_on", "version")
    if any(
        value and all(value.get(key) == metadata.get(key) for key in keys) for value in candidates
    ):
        notices.append(NamingDuplicateNotice(kind="suspected", message="疑似重复，请核对"))
    return notices


async def render(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    request: NamingPreviewRequest,
) -> RenderedNaming | None:
    scope = request.target_scope.value
    if scope == KnowledgeScope.personal.value:
        return None
    revision = (
        await session.execute(
            select(NamingRuleRevision)
            .where(NamingRuleRevision.status == "published")
            .order_by(NamingRuleRevision.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # Fresh test/dev databases created from metadata may not have migration seed
    # rows yet. Until governance explicitly publishes, preserve the rollout's
    # non-enforcing baseline.
    if revision is None:
        return None
    config = _config(revision)
    if not config.enforced:
        return None
    naming = request.naming
    if naming is None:
        raise _denied(422, "naming_fields_required", "项目或公司入库必须填写规范命名字段")
    category = next((item for item in config.categories if item.id == naming.category_id), None)
    if category is None or not category.enabled or category.scope != scope:
        raise _denied(409, "naming_category_unavailable", "目录类别已停用或不适用于目标库")

    project_code: str | None = None
    if scope == KnowledgeScope.project.value:
        if request.target_project_id is None:
            raise _denied(422, "target_project_required", "项目入库必须指定目标项目")
        project = await session.get(Project, request.target_project_id)
        if (
            project is None
            or project.status != "active"
            or not project.project_code_active
            or not project.project_code
        ):
            raise _denied(409, "project_naming_code_unavailable", "目标项目尚未启用项目代码")
        project_code = project.project_code
        bracket = f"{project_code}-{naming.formed_on.year}-{category.secondary}"
        stem = (
            f"【{bracket}】{naming.subject}_{naming.formed_on:%Y%m%d}_"
            f"{naming.version}_{request.confidentiality_level.value}"
        )
    else:
        if not naming.applicable_to:
            raise _denied(422, "naming_applicable_to_required", "公司资料必须填写适用对象")
        bracket = f"{category.primary}-{category.secondary}"
        stem = (
            f"【{bracket}】{naming.subject}_{naming.applicable_to}_"
            f"{naming.formed_on:%Y%m%d}_{naming.version}_{request.confidentiality_level.value}"
        )
    canonical = f"{stem}{_extension(task.source_file_name)}"
    if len(canonical) > 500:
        raise _denied(422, "canonical_name_too_long", "规范名过长，请缩短主题或适用对象")
    metadata = {
        "scope": scope,
        "project_code": project_code,
        "category_id": str(category.id),
        "category_primary": category.primary,
        "category_secondary": category.secondary,
        "category_prefix": category.prefix,
        "subject": naming.subject,
        "applicable_to": naming.applicable_to,
        "formed_on": naming.formed_on.isoformat(),
        "version": naming.version,
        "confidentiality": request.confidentiality_level.value,
        "extension": _extension(task.source_file_name),
        "rule_version": revision.version,
        "canonical_name": canonical,
    }
    notices = await _duplicate_notices(
        session, caller, task, scope, request.target_project_id, metadata
    )
    return RenderedNaming(canonical, revision.version, metadata, notices)


async def preview(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    request: NamingPreviewRequest,
) -> NamingPreviewResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可预览入库命名")
    task = await session.get(IngestTask, task_id)
    if task is None:
        raise _denied(404, "ingest_task_not_found", "入库任务不存在")
    if not (task.created_by == caller.user_id or caller.can_discover_l5):
        raise _denied(403, "ingest_confirm_forbidden", "无权预览该入库任务")
    scope = request.target_scope.value
    if task.target_scope and task.target_scope != scope:
        raise _denied(409, "ingest_target_locked", "入库目标已由来源规则锁定，不能更改")
    if scope == KnowledgeScope.project.value:
        if request.target_project_id not in caller.active_project_ids:
            raise _denied(403, "project_membership_required", "需为目标项目的有效成员")
        if task.target_project_id and task.target_project_id != request.target_project_id:
            raise _denied(409, "ingest_target_project_locked", "目标项目已由来源规则锁定")
    elif scope == KnowledgeScope.company.value and not caller.can_discover_l5:
        raise _denied(403, "company_confirmation_requires_governance", "公司知识需治理角色确认")
    rendered = await render(session, caller, task, request)
    if rendered is None:
        return NamingPreviewResponse(
            required=False,
            canonical_name=None,
            rule_version=None,
            fields=None,
            message=(
                "个人资料不强制规范命名"
                if scope == KnowledgeScope.personal.value
                else "命名规则尚未发布，不强制规范命名"
            ),
        )
    return NamingPreviewResponse(
        required=True,
        canonical_name=rendered.canonical_name,
        rule_version=rendered.rule_version,
        fields=rendered.metadata,
        notices=rendered.notices,
    )


async def options(
    session: AsyncSession,
    caller: CallerContext,
    scope: KnowledgeScope,
    project_id: uuid.UUID | None,
) -> NamingOptionsResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可读取命名选项")
    if scope == KnowledgeScope.personal:
        return NamingOptionsResponse(
            required=False,
            rule_version=None,
            message="个人资料不强制规范命名",
        )
    revision = (
        await session.execute(
            select(NamingRuleRevision)
            .where(NamingRuleRevision.status == "published")
            .order_by(NamingRuleRevision.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    config = _config(revision) if revision is not None else None
    if scope == KnowledgeScope.project:
        if project_id is None or project_id not in caller.active_project_ids:
            raise _denied(403, "project_membership_required", "需为目标项目的有效成员")
        if config is None or not config.enforced:
            return NamingOptionsResponse(required=False, rule_version=None)
        project = await session.get(Project, project_id)
        if (
            project is None
            or project.status != "active"
            or not project.project_code_active
            or not project.project_code
        ):
            raise _denied(409, "project_naming_code_unavailable", "目标项目尚未启用项目代码")
        default_confidentiality = project.naming_default_confidentiality
    else:
        if not caller.can_discover_l5:
            raise _denied(403, "company_confirmation_requires_governance", "公司知识需治理角色确认")
        if config is None or not config.enforced:
            return NamingOptionsResponse(required=False, rule_version=None)
        default_confidentiality = "L2"
    assert revision is not None and config is not None
    categories = sorted(
        [item for item in config.categories if item.enabled and item.scope == scope.value],
        key=lambda item: (item.sort_order, item.primary, item.secondary),
    )
    return NamingOptionsResponse(
        required=True,
        rule_version=revision.version,
        categories=[
            NamingOptionItem(
                id=item.id,
                primary=item.primary,
                secondary=item.secondary,
                prefix=item.prefix,
                default_confidentiality=item.default_confidentiality,
            )
            for item in categories
        ],
        default_confidentiality=default_confidentiality,
    )
