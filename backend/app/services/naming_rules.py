"""Published naming policy governance, rendering and safe duplicate notices."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
from types import SimpleNamespace
from typing import cast

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject, KnowledgeAssetVersion
from app.models.naming import NamingRuleRevision
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    ConfidentialityLevel,
    KnowledgeScope,
)
from app.schemas.naming import (
    BatchNamingPreviewItemResponse,
    BatchNamingPreviewRequest,
    BatchNamingPreviewResponse,
    DirectoryOptionItem,
    FormalDirectoryConfig,
    NamingDraftUpdateRequest,
    NamingDuplicateNotice,
    NamingOptionsResponse,
    NamingPreviewRequest,
    NamingPreviewResponse,
    NamingPublishRequest,
    NamingRuleCenterOut,
    NamingRuleConfig,
    NamingRuleRevisionOut,
)
from app.schemas.permission import CallerContext
from app.schemas.upload_duplicates import UploadDuplicateReadModel
from app.services import audit as audit_service
from app.services.directories import (
    default_directory_config,
    legacy_directory_key,
    published_directories,
    validate_directory,
)
from app.services.naming_advice import naming_preview_advice, safe_naming_advice
from app.services.upload_duplicates import read_duplicate


@dataclass(frozen=True, slots=True)
class RenderedNaming:
    canonical_name: str
    rule_version: int
    metadata: dict
    notices: list[NamingDuplicateNotice]
    duplicate: UploadDuplicateReadModel


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
    initial = NamingRuleConfig(enforced=True, directories=_default_directories()).model_dump(
        mode="json"
    )
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


def _default_directories() -> list[FormalDirectoryConfig]:
    return [FormalDirectoryConfig.model_validate(item) for item in default_directory_config()]


def _config(revision: NamingRuleRevision) -> NamingRuleConfig:
    try:
        config = NamingRuleConfig.model_validate(revision.config)
        return config.model_copy(
            update={"directories": config.directories or _default_directories()}
        )
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


def _missing_asset_type_ids(config: NamingRuleConfig) -> list[uuid.UUID]:
    return [item.id for item in config.categories if item.enabled and item.asset_type is None]


def _normalized_config(config: NamingRuleConfig) -> NamingRuleConfig:
    return config.model_copy(
        update={
            "schema_version": 2,
            "directories": config.directories or _default_directories(),
            "migration_missing_asset_type_category_ids": _missing_asset_type_ids(config),
        }
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
    current_config = _config(draft)
    # Categories and project-code projections are historical, read-only data.
    # The current write contract accepts formal directories only.
    normalized_config = _normalized_config(
        current_config.model_copy(
            update={
                "directories": request.directories,
                "enforced": True,
            }
        )
    )
    draft.config = normalized_config.model_dump(mode="json")
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
            "directory_count": len(normalized_config.directories),
            "enforced": normalized_config.enforced,
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
    config = _normalized_config(_config(draft))
    now = datetime.now(timezone.utc)
    draft.config = config.model_dump(mode="json")
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
            "directory_count": len(config.directories),
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


def _project_subject_aliases(project: Project, config: NamingRuleConfig) -> list[str]:
    """Return aliases only for the already-authorized target project."""
    aliases = [" ".join(project.name.strip().split())]
    policy = next(
        (item for item in config.project_codes if item.project_id == project.id),
        None,
    )
    if policy is not None and policy.client_aliases_enabled:
        aliases.extend(policy.client_aliases)
    return sorted(
        {alias for alias in aliases if len(alias) >= 2},
        key=len,
        reverse=True,
    )


def _subject_contains_alias(subject: str, aliases: list[str]) -> bool:
    return any(re.search(re.escape(alias), subject, re.IGNORECASE) for alias in aliases)


def _deidentify_project_subject(subject: str, aliases: list[str]) -> tuple[str, bool]:
    """Keep the user's business subject and flag controlled project/customer aliases."""
    normalized = " ".join(subject.strip().split())
    return normalized, _subject_contains_alias(normalized, aliases)


def _duplicate_notices(duplicate: UploadDuplicateReadModel) -> list[NamingDuplicateNotice]:
    notices: list[NamingDuplicateNotice] = []
    if duplicate.duplicate_state in {"exact_content", "same_batch"}:
        notices.append(
            NamingDuplicateNotice(
                code="exact_duplicate",
                kind="exact",
                message=(
                    "本批存在内容完全相同的文件，请选择保留项"
                    if duplicate.duplicate_state == "same_batch"
                    else "已存在内容完全相同的资料，请确认是否仍需独立入库"
                ),
            )
        )
    if duplicate.duplicate_state == "suspected_metadata":
        notices.append(
            NamingDuplicateNotice(
                code="suspected_duplicate",
                kind="suspected",
                message="主题、日期和版本疑似重复，请核对",
            )
        )
    return notices


def _legacy_category_id(naming: object) -> uuid.UUID | None:
    """Read a retired request field without exposing it in the current schema."""
    extra = getattr(naming, "__pydantic_extra__", None)
    raw = extra.get("category_id") if isinstance(extra, dict) else None
    try:
        return uuid.UUID(str(raw)) if raw else None
    except (TypeError, ValueError):
        return None


def _directory_naming_code(directory: dict) -> str:
    configured = str(directory.get("naming_code") or "").strip()
    if configured:
        return configured
    display_name = str(directory.get("display_name") or "正式目录").strip()
    return re.sub(r"^\d{2}\s*", "", display_name) or display_name


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
    naming = request.naming
    if naming is None:
        raise _denied(422, "naming_fields_required", "项目或公司入库必须填写规范命名字段")
    directory_key = naming.directory_key
    category = None
    if directory_key:
        directory_rule_version, directory = await validate_directory(
            session,
            directory_key=directory_key,
            scope=scope,
            project_id=request.target_project_id,
        )
        directory_source = "formal_directory"
        naming_code = _directory_naming_code(directory)
    else:
        # Read-only compatibility for clients created before formal-directory
        # publication.  New schemas and UIs never emit category_id.
        legacy_category_id = _legacy_category_id(naming)
        category = next((item for item in config.categories if item.id == legacy_category_id), None)
        if category is None or not category.enabled or category.scope != scope:
            raise _denied(422, "directory_required", "请选择一个已启用的正式目录")
        directory_key = category.suggested_directory_key or legacy_directory_key(
            {
                "scope": scope,
                "category_primary": category.primary,
                "category_secondary": category.secondary,
            }
        )
        if not directory_key:
            raise _denied(422, "directory_required", "请选择一个已启用的正式目录")
        directory_rule_version, directory = await validate_directory(
            session,
            directory_key=directory_key,
            scope=scope,
            project_id=request.target_project_id,
        )
        directory_source = "legacy_category_mapping"
        naming_code = (
            category.secondary
            if scope == KnowledgeScope.project.value
            else (f"{category.primary}-{category.secondary}")
        )
    project_code: str | None = None
    rendered_subject = naming.subject
    subject_has_business_name = False
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
        rendered_subject, subject_has_business_name = _deidentify_project_subject(
            naming.subject,
            _project_subject_aliases(project, config),
        )
        bracket = f"{project_code}-{naming.formed_on.year}-{naming_code}"
        stem = (
            f"【{bracket}】{rendered_subject}_{naming.formed_on:%Y%m%d}_"
            f"{naming.version}_{request.confidentiality_level.value}"
        )
    else:
        if not naming.applicable_to:
            raise _denied(422, "naming_applicable_to_required", "公司资料必须填写适用对象")
        bracket = naming_code
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
        "subject": rendered_subject,
        "subject_deidentified": False,
        "subject_business_name_warning": subject_has_business_name,
        "applicable_to": naming.applicable_to,
        "formed_on": naming.formed_on.isoformat(),
        "version": naming.version,
        "confidentiality": request.confidentiality_level.value,
        "extension": _extension(task.source_file_name),
        "rule_version": revision.version,
        "directory_key": directory_key,
        "directory_rule_version": directory_rule_version,
        "directory_source": directory_source,
        "directory_name": directory.get("display_name"),
        "directory_naming_code": naming_code,
        "canonical_name": canonical,
    }
    if category is not None:
        metadata.update(
            {
                "legacy_category_id": str(category.id),
                "category_id": str(category.id),
                "category_primary": category.primary,
                "category_secondary": category.secondary,
                "category_prefix": category.prefix,
                "asset_type": category.asset_type.value if category.asset_type else "unclassified",
            }
        )
    notices: list[NamingDuplicateNotice] = []
    if subject_has_business_name:
        notices.append(
            NamingDuplicateNotice(
                code="project_subject_business_name",
                kind="semantic",
                message="主题可能包含客户名、项目简称或业务专名，请确认是否保留",
            )
        )
    ai = await session.scalar(
        select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == task.id)
    )
    advice = safe_naming_advice(ai)
    if advice["version_source"] == "default_needs_confirmation":
        notices.append(
            NamingDuplicateNotice(
                code="version_source_unreliable",
                kind="advisory",
                message="版本来自规则默认值，请人工核对",
            )
        )
    if advice["confidentiality_source"] == "default_needs_confirmation":
        notices.append(
            NamingDuplicateNotice(
                code="confidentiality_source_unreliable",
                kind="advisory",
                message="密级未由 AI 可靠确定，请人工核对",
            )
        )
    if ai is not None and ai.naming_compliant is False:
        notices.append(
            NamingDuplicateNotice(
                code="historical_naming_noncompliant",
                kind="advisory",
                message="来源文件名不符合当前规范，但不影响人工确认入库",
            )
        )
    if ai is not None and (ai.confidence is None or ai.confidence < 0.7):
        notices.append(
            NamingDuplicateNotice(
                code="ai_suggestion_uncertain",
                kind="advisory",
                message="AI 对部分命名建议不确定，请人工核对",
            )
        )
    duplicate = (
        await read_duplicate(
            session,
            caller,
            task,
            scope=scope,
            project_id=request.target_project_id,
            metadata=metadata,
        )
        if isinstance(task, IngestTask)
        else UploadDuplicateReadModel()
    )
    notices.extend(_duplicate_notices(duplicate))
    return RenderedNaming(canonical, revision.version, metadata, notices, duplicate)


async def render_asset_publication(
    session: AsyncSession,
    caller: CallerContext,
    asset: KnowledgeAsset,
    request: NamingPreviewRequest,
) -> RenderedNaming:
    """Render target-scope naming for a governed derivative publication.

    Existing assets do not have an ingest task. A read-only source projection lets
    the established renderer enforce the same published categories, project code,
    directory scope, canonical name and duplicate checks without mutating the source.
    """
    version = await session.get(KnowledgeAssetVersion, asset.current_version_id)
    original_name = None
    if version is not None:
        original_name = await session.scalar(
            select(KnowledgeAssetFileObject.file_name).where(
                KnowledgeAssetFileObject.version_id == version.id,
                KnowledgeAssetFileObject.file_variant == "original",
            )
        )
    source_name = asset.canonical_name or original_name or asset.title
    proxy = SimpleNamespace(
        id=uuid.uuid4(),
        source_file_name=source_name,
        source_file_hash=version.file_hash if version is not None else None,
    )
    # The shared renderer reads only these task projection fields. This source
    # is an existing asset rather than an ingest task, so keep that contract
    # explicit to mypy without widening the renderer's production input.
    rendered = await render(session, caller, cast(IngestTask, proxy), request)
    if rendered is None:
        raise _denied(
            409,
            "publication_naming_policy_required",
            "目标知识库尚未发布可用的命名规则",
        )
    return rendered


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
    ai = await session.scalar(
        select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == task.id)
    )
    advice = naming_preview_advice(ai)
    rendered = await render(session, caller, task, request)
    if rendered is None:
        duplicate = await read_duplicate(
            session,
            caller,
            task,
            scope=scope,
            project_id=request.target_project_id,
            metadata=request.naming.model_dump(mode="json") if request.naming else None,
        )
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
            duplicate=duplicate,
            **advice,
        )
    return NamingPreviewResponse(
        required=True,
        canonical_name=rendered.canonical_name,
        rule_version=rendered.rule_version,
        fields=rendered.metadata,
        notices=rendered.notices,
        duplicate=rendered.duplicate,
        **advice,
    )


def _batch_validation_error(exc: ValidationError) -> tuple[str, str]:
    locations = {str(part) for error in exc.errors() for part in error.get("loc", ())}
    if "formed_on" in locations:
        return "naming_formed_on_invalid", "请填写有效的文件形成日期"
    if "version" in locations:
        return "naming_version_invalid", "请填写有效版本，例如 V1 或 V1.1"
    if "directory_key" in locations:
        return "directory_required", "请选择有效且已启用的正式目录"
    if "subject" in locations:
        return "naming_subject_invalid", "请填写有效主题"
    if "applicable_to" in locations:
        return "naming_applicable_to_required", "公司库资料必须填写有效适用对象"
    return "naming_fields_invalid", "请补齐或修改该资料的命名字段"


def _batch_http_error(exc: HTTPException) -> tuple[str, str]:
    detail: dict[str, object] = exc.detail if isinstance(exc.detail, dict) else {}
    reason = str(detail.get("denied_reason") or "item_state_changed")
    if exc.status_code in {403, 404}:
        return "item_unavailable", "该资料不存在或当前不可核对"
    safe_messages = {
        "naming_fields_required": "请补齐该资料的命名字段",
        "directory_required": "请选择一个已启用的正式目录",
        "directory_unavailable": "正式目录不存在或已停用，请刷新后重新选择",
        "directory_scope_mismatch": "所选正式目录不适用于当前目标",
        "naming_applicable_to_required": "公司库资料必须填写适用对象",
        "canonical_name_too_long": "规范名过长，请缩短主题或适用对象",
        "ingest_target_locked": "资料目标已由来源规则锁定",
        "ingest_target_project_locked": "目标项目已由来源规则锁定",
    }
    return reason, safe_messages.get(reason, "当前状态已变化，请刷新后重新核对")


async def batch_preview(
    session: AsyncSession,
    caller: CallerContext,
    request: BatchNamingPreviewRequest,
) -> BatchNamingPreviewResponse:
    """Preview governed names independently without leaking another item's data."""
    # Authorize the common destination before touching any task identifiers.
    destination = await options(
        session,
        caller,
        request.target_scope,
        request.target_project_id,
    )
    results: list[BatchNamingPreviewItemResponse] = []
    for item in request.items:
        try:
            item_request = NamingPreviewRequest.model_validate(
                {
                    "target_scope": request.target_scope,
                    "target_project_id": request.target_project_id,
                    "confidentiality_level": item.confidentiality_level,
                    "naming": item.naming.model_dump() if item.naming is not None else None,
                }
            )
            rendered = await preview(session, caller, item.task_id, item_request)
            results.append(
                BatchNamingPreviewItemResponse(
                    task_id=item.task_id,
                    submittable=not destination.required or rendered.canonical_name is not None,
                    canonical_name=rendered.canonical_name,
                    rule_version=rendered.rule_version,
                    fields=rendered.fields,
                    notices=rendered.notices,
                    duplicate=rendered.duplicate,
                    error_code=None,
                    message=None,
                    suggested_version=rendered.suggested_version,
                    version_source=rendered.version_source,
                    version_confidence=rendered.version_confidence,
                    version_reason=rendered.version_reason,
                    suggested_confidentiality_level=rendered.suggested_confidentiality_level,
                    confidentiality_source=rendered.confidentiality_source,
                    confidentiality_confidence=rendered.confidentiality_confidence,
                    confidentiality_reason=rendered.confidentiality_reason,
                )
            )
        except ValidationError as exc:
            code, message = _batch_validation_error(exc)
            results.append(
                BatchNamingPreviewItemResponse(
                    task_id=item.task_id,
                    submittable=False,
                    error_code=code,
                    message=message,
                )
            )
        except HTTPException as exc:
            code, message = _batch_http_error(exc)
            results.append(
                BatchNamingPreviewItemResponse(
                    task_id=item.task_id,
                    submittable=False,
                    error_code=code,
                    message=message,
                )
            )
    return BatchNamingPreviewResponse(items=results)


async def options(
    session: AsyncSession,
    caller: CallerContext,
    scope: KnowledgeScope,
    project_id: uuid.UUID | None,
) -> NamingOptionsResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可读取命名选项")
    if scope == KnowledgeScope.personal:
        _version, directory_rows = await published_directories(session)
        return NamingOptionsResponse(
            required=False,
            rule_version=None,
            directories=[
                DirectoryOptionItem.model_validate(item)
                for item in directory_rows
                if item.get("enabled", True) and item.get("scope") == "personal"
            ],
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
        if config is None:
            return NamingOptionsResponse(required=False, rule_version=None)
        project = await session.get(Project, project_id)
        if (
            project is None
            or project.status != "active"
            or not project.project_code_active
            or not project.project_code
        ):
            raise _denied(409, "project_naming_code_unavailable", "目标项目尚未启用项目代码")
        fallback_confidentiality = ConfidentialityLevel(project.naming_default_confidentiality)
    else:
        is_project_manager = any(
            role == "project_manager" for role in caller.active_project_roles.values()
        )
        if not caller.can_discover_l5 and not is_project_manager:
            raise _denied(403, "company_confirmation_requires_governance", "公司知识需治理角色确认")
        if config is None:
            return NamingOptionsResponse(required=False, rule_version=None)
        fallback_confidentiality = ConfidentialityLevel.L2
    assert revision is not None and config is not None
    directories = sorted(
        [item for item in config.directories if item.enabled and item.scope == scope.value],
        key=lambda item: (item.sort_order, item.display_name),
    )
    return NamingOptionsResponse(
        required=True,
        rule_version=revision.version,
        directories=[DirectoryOptionItem.model_validate(item.model_dump()) for item in directories],
        default_confidentiality=(
            directories[0].default_confidentiality if directories else fallback_confidentiality
        ),
        message=None if directories else "当前目标尚未配置启用的正式目录",
    )
