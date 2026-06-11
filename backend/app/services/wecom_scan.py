"""企微微盘扫描服务（Path A）。

把"扫描配置目录 → 列文件 → 下载字节 → 经平台存储落盘 → 建 path_a_wecom IngestTask →
复用统一处理链"收口到这里。文件仍走既有 `/upload` 确认流后才成为知识资产（不变）。

强约束：
- 字节**只经平台后端**抓取并落 `LocalFileStorage`；source_file_ref 是 server-only。
- **绝不**持久化/外泄企微下载 URL / access_token / file_id；去重用内容 hash。
- admin 仅运营：可配置/触发扫描，但不因此获得业务原文/AI 结果内容（沿用 ingest 读权限）。
- 单文件失败不中断整批；列目录失败则整次扫描标记 failed。
- 幂等：同 config + Idempotency-Key 命中已存在记录则不重扫；同内容 hash 已有任务则记为重复。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project, ProjectMember, User
from app.models.ingest import IngestTask
from app.models.wecom import WecomScanConfig, WecomScanRecord
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    CompanyRole,
    IngestSource,
    IngestStatus,
    KnowledgeScope,
    KnowledgeZone,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.permission import build_caller_context
from app.services.storage import LocalFileStorage, StorageError, safe_filename
from app.services.wecom_client import WeComError
from app.worker.enqueue import enqueue_ingest_processing


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"denied_reason": reason, "message": message})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _is_governance(caller: CallerContext) -> bool:
    return caller.can_discover_l5  # boss / consulting_director


def _require_reader(caller: CallerContext) -> None:
    """读配置/记录：admin 或 boss / 咨询总监。"""
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(403, "wecom_scan_forbidden", "无权查看微盘扫描配置/记录")


def _require_admin(caller: CallerContext) -> None:
    """启停/触发扫描：admin（PATCH/scan 要求 admin；admin 仅运营，不得业务原文）。"""
    if not _is_admin(caller):
        raise _denied(403, "wecom_scan_admin_required", "仅 admin 可配置/触发微盘扫描")


async def _owner_actor(session: AsyncSession, config: WecomScanConfig) -> CallerContext:
    """以配置归属业务用户身份做 ingest.task_created 审计（后续由该用户确认）。"""
    user = (
        await session.execute(
            select(User).where(User.id == config.created_by).options(
                selectinload(User.company_roles),
                selectinload(User.project_members).selectinload(ProjectMember.project),
            )
        )
    ).scalar_one_or_none()
    if user is not None:
        return build_caller_context(user)
    return CallerContext(
        user_id=config.created_by, is_active=True,
        active_company_roles=set(), active_project_ids=set(),
    )


async def _find_by_key(session: AsyncSession, config_id: uuid.UUID, idempotency_key: str):
    """按 (config_id, idempotency_key) 查既有扫描记录（幂等快路径 + 冲突重查）。"""
    return (
        await session.execute(
            select(WecomScanRecord)
            .where(WecomScanRecord.config_id == config_id)
            .where(WecomScanRecord.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()


async def _hash_exists(session: AsyncSession, content_hash: str) -> bool:
    """是否已存在同内容 hash 的入库任务（去重，防重复 active 任务）。"""
    row = (
        await session.execute(
            select(IngestTask.id).where(IngestTask.source_file_hash == content_hash).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


# ---------------------------------------------------------------------------
# 配置 / 记录 读写（API）
# ---------------------------------------------------------------------------
def _config_out(
    c: WecomScanConfig,
    project_name: str | None = None,
    owner_name: str | None = None,
    owner_role_label: str | None = None,
):
    from app.schemas.wecom import WecomScanConfigOut

    return WecomScanConfigOut(
        id=c.id, name=c.name, directory_path=c.directory_path, scope_type=c.scope_type,
        related_project_id=c.related_project_id, related_project_name=project_name,
        enabled=c.enabled, created_by=c.created_by,
        task_owner_name=owner_name, task_owner_role_label=owner_role_label,
        scan_frequency=c.scan_frequency, last_scan_at=c.last_scan_at,
        created_at=c.created_at, updated_at=c.updated_at,
    )


_VALID_SCOPES = {
    KnowledgeScope.personal.value,
    KnowledgeScope.project.value,
    KnowledgeScope.company.value,
}

# 业务公司角色 → 中文标签（仅展示，安全；admin 是系统身份，不作业务归属人候选）。
_ROLE_LABELS = {
    CompanyRole.consultant.value: "顾问",
    CompanyRole.boss.value: "Boss",
    CompanyRole.consulting_director.value: "咨询总监",
}


def _role_label(active_company_roles: set[str]) -> str | None:
    labels = [_ROLE_LABELS[r] for r in _ROLE_LABELS if r in active_company_roles]
    return " / ".join(labels) if labels else None


async def _load_user_with_context(session: AsyncSession, user_id: uuid.UUID):
    """加载 User（含 active 角色/成员）并构建 CallerContext，返回 (user, ctx) 或 (None, None)。"""
    user = (
        await session.execute(
            select(User).where(User.id == user_id).options(
                selectinload(User.company_roles),
                selectinload(User.project_members),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        return None, None
    return user, build_caller_context(user)


async def _owner_meta(session: AsyncSession, owner_id: uuid.UUID) -> tuple[str | None, str | None]:
    user, ctx = await _load_user_with_context(session, owner_id)
    if user is None or ctx is None:
        return None, None
    return user.name, _role_label(ctx.active_company_roles)


async def _validate_task_owner(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    scope_type: str,
    related_project_id: uuid.UUID | None,
) -> User:
    """校验扫描产物的业务归属人合法性。

    归属人将写入 `WecomScanConfig.created_by`，并成为扫描生成的 path_a_wecom
    IngestTask.created_by；必须能完成后续 `/upload` Path A 确认。规则：
    - 存在 + active；
    - 是业务用户（含 active 业务公司角色，**非纯 admin**）；
    - project scope：必须是 target project 的 active 成员；
    - company scope：必须是业务治理角色（boss / 咨询总监），与 ingest.confirm 公司级一致。
    """
    user, ctx = await _load_user_with_context(session, owner_user_id)
    if user is None or ctx is None:
        raise _denied(422, "task_owner_not_found", "业务归属人不存在")
    if not ctx.is_active:
        raise _denied(422, "task_owner_inactive", "业务归属人已停用，不能作为待确认任务归属人")
    if not ctx.is_business_user:
        raise _denied(422, "task_owner_not_business", "业务归属人必须是业务用户（纯 admin 不可）")
    if scope_type == KnowledgeScope.project.value:
        if related_project_id not in ctx.active_project_ids:
            raise _denied(
                422, "task_owner_not_project_member",
                "业务归属人必须是目标项目的有效成员，否则无法确认项目级任务",
            )
    elif scope_type == KnowledgeScope.company.value:
        if not ctx.can_discover_l5:
            raise _denied(
                422, "task_owner_not_governance",
                "公司级配置的业务归属人必须是 Boss / 咨询总监",
            )
    return user


async def _owner_still_valid(session: AsyncSession, config: WecomScanConfig) -> bool:
    """扫描运行时复核业务归属人是否仍合法（停用 / 移出项目 / 失去治理角色即失效）。

    复用 `_validate_task_owner` 的全部规则；不抛 HTTP，只返回布尔，供 trigger / run_scan
    在创建任务前 fail-closed。`config.created_by` 即业务归属人。
    """
    try:
        await _validate_task_owner(
            session, owner_user_id=config.created_by,
            scope_type=config.scope_type, related_project_id=config.related_project_id,
        )
        return True
    except HTTPException:
        return False


async def _project_name(session: AsyncSession, project_id: uuid.UUID | None) -> str | None:
    if project_id is None:
        return None
    return (
        await session.execute(select(Project.name).where(Project.id == project_id))
    ).scalar_one_or_none()


async def _validate_config_fields(
    session: AsyncSession,
    *,
    name: str | None,
    directory_path: str | None,
    scope_type: str | None,
    related_project_id: uuid.UUID | None,
) -> tuple[str, str, str, uuid.UUID | None]:
    """校验扫描配置安全字段，返回归一化后的 (name, directory_path, scope_type, project_id)。

    一致策略：project scope 必须有存在的 target_project_id；personal/company scope
    **拒绝**携带 project_id（不静默清空，明确 422，便于前端纠正）。directory_path 仅做
    格式校验，错误信息为安全中文文案，不回显上游敏感载体。
    """
    from app.services.wecom_client import parse_directory_path

    clean_name = (name or "").strip()
    if not clean_name:
        raise _denied(422, "wecom_scan_name_required", "配置名称不能为空")
    if len(clean_name) > 200:
        raise _denied(422, "wecom_scan_name_too_long", "配置名称过长（最多 200 字）")

    clean_dir = (directory_path or "").strip()
    try:
        parse_directory_path(clean_dir)
    except WeComError:
        raise _denied(
            422, "wecom_invalid_directory",
            "扫描目录格式应为 'spaceid:<id>;fatherid:<id>'",
        )

    if scope_type not in _VALID_SCOPES:
        raise _denied(422, "wecom_scan_invalid_scope", "非法的目标知识库类型")

    if scope_type == KnowledgeScope.project.value:
        if related_project_id is None:
            raise _denied(422, "target_project_required", "项目级配置必须指定目标项目")
        exists = (
            await session.execute(select(Project.id).where(Project.id == related_project_id))
        ).scalar_one_or_none()
        if exists is None:
            raise _denied(422, "target_project_not_found", "目标项目不存在")
    else:
        if related_project_id is not None:
            raise _denied(
                422, "target_project_not_allowed",
                "个人 / 公司级配置不应指定目标项目",
            )

    return clean_name, clean_dir, scope_type, related_project_id


async def create_config(session: AsyncSession, caller: CallerContext, body, trace_id: str):
    """创建扫描配置（仅 admin）。

    配置操作人是当前 admin（审计 actor）；`created_by` 写入校验通过的**业务归属人**
    （body.task_owner_user_id），使扫描产物的 path_a_wecom IngestTask 归属合法业务用户、
    可被其在 `/upload` Path A 确认。纯 admin 不再成为任务归属人。
    """
    _require_admin(caller)
    name, directory_path, scope_type, project_id = await _validate_config_fields(
        session,
        name=body.name, directory_path=body.directory_path,
        scope_type=body.target_scope, related_project_id=body.target_project_id,
    )
    owner = await _validate_task_owner(
        session, owner_user_id=body.task_owner_user_id,
        scope_type=scope_type, related_project_id=project_id,
    )
    config = WecomScanConfig(
        name=name, directory_path=directory_path, scope_type=scope_type,
        related_project_id=project_id, enabled=body.enabled, created_by=owner.id,
    )
    session.add(config)
    await session.flush()
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.wecom_scan_config_created.value, trace_id=trace_id,
        target_type="wecom_scan_config", target_id=config.id,
        # 安全配置元数据。task_owner_user_id 记录业务归属人；审计 actor 仍是当前 admin
        # （两者不混淆）。directory_path 只记"已设置"标记，不写原值/上游标识。
        after={
            "name": name, "enabled": config.enabled, "scope_type": scope_type,
            "target_project_id": str(project_id) if project_id else None,
            "task_owner_user_id": str(owner.id),
            "directory_path_set": True,
        },
        project_id=project_id,
    )
    await session.commit()
    owner_name, owner_role = await _owner_meta(session, owner.id)
    return _config_out(config, await _project_name(session, project_id), owner_name, owner_role)


async def list_project_options(session: AsyncSession, caller: CallerContext):
    """目标项目候选（仅 active 项目的 id + 名称），供创建/编辑配置选择。读权限同配置读。"""
    from app.schemas.wecom import WecomProjectOptionOut, WecomProjectOptionsResponse

    _require_reader(caller)
    rows = (
        await session.execute(
            select(Project.id, Project.name)
            .where(Project.status == "active")
            .order_by(Project.name)
        )
    ).all()
    return WecomProjectOptionsResponse(
        items=[WecomProjectOptionOut(id=r.id, name=r.name) for r in rows]
    )


async def list_owner_options(session: AsyncSession, caller: CallerContext):
    """业务归属人候选：active 业务用户（含 active 业务公司角色，排除纯 admin）。

    读权限同配置读。返回安全字段 + project_ids / is_governance 供前端按 scope 提示；
    后端在创建/编辑时最终校验为准。绝不含 token / session / wecom_user_id / ip / device。
    """
    from app.schemas.wecom import WecomOwnerOptionOut, WecomOwnerOptionsResponse

    _require_reader(caller)
    users = (
        await session.execute(
            select(User).where(User.status == "active").options(
                selectinload(User.company_roles),
                selectinload(User.project_members),
            ).order_by(User.name)
        )
    ).scalars().all()
    items = []
    for u in users:
        ctx = build_caller_context(u)
        if not ctx.is_business_user:
            continue
        items.append(
            WecomOwnerOptionOut(
                user_id=u.id, name=u.name,
                role_label=_role_label(ctx.active_company_roles),
                project_ids=sorted(ctx.active_project_ids),
                is_governance=ctx.can_discover_l5,
            )
        )
    return WecomOwnerOptionsResponse(items=items)


def _record_out(r: WecomScanRecord):
    from app.schemas.wecom import WecomScanRecordOut

    return WecomScanRecordOut(
        id=r.id, config_id=r.config_id, trace_id=r.trace_id,
        scan_started_at=r.scan_started_at, scan_completed_at=r.scan_completed_at,
        discovered_count=r.discovered_count, new_count=r.new_count,
        duplicate_count=r.duplicate_count, failed_count=r.failed_count,
        scan_status=r.scan_status, error_type=r.error_type, error_message=r.error_message,
        created_at=r.created_at,
    )


async def list_configs(session: AsyncSession, caller: CallerContext):
    from app.schemas.wecom import WecomScanConfigsResponse

    _require_reader(caller)
    rows = list(
        (await session.execute(select(WecomScanConfig).order_by(WecomScanConfig.created_at)))
        .scalars().all()
    )
    # 批量解析关联项目名（仅安全字段）。
    pids = {c.related_project_id for c in rows if c.related_project_id is not None}
    name_map: dict[uuid.UUID, str] = {}
    if pids:
        for pid, pname in (
            await session.execute(select(Project.id, Project.name).where(Project.id.in_(pids)))
        ).all():
            name_map[pid] = pname
    # 批量解析业务归属人姓名 + 角色标签（created_by = 业务归属人）。
    owner_ids = {c.created_by for c in rows}
    owner_map: dict[uuid.UUID, tuple[str | None, str | None]] = {}
    if owner_ids:
        users = (
            await session.execute(
                select(User).where(User.id.in_(owner_ids)).options(
                    selectinload(User.company_roles),
                )
            )
        ).scalars().all()
        for u in users:
            roles = {r.company_role for r in u.company_roles if r.status == "active"}
            owner_map[u.id] = (u.name, _role_label(roles))
    return WecomScanConfigsResponse(
        items=[
            _config_out(
                c, name_map.get(c.related_project_id),
                *owner_map.get(c.created_by, (None, None)),
            )
            for c in rows
        ]
    )


async def update_config(session: AsyncSession, caller: CallerContext, config_id: uuid.UUID, body, trace_id: str):
    """编辑扫描配置（仅 admin）。支持 name / directory_path / target_scope /
    target_project_id / enabled 局部更新；仅启停时不触发字段重校验。"""
    _require_admin(caller)
    config = await session.get(WecomScanConfig, config_id)
    if config is None:
        raise _denied(404, "wecom_scan_config_not_found", "扫描配置不存在")

    # 计算生效后的取值（提供则覆盖；scope 改为非项目时清空 project）。
    new_name = body.name if body.name is not None else config.name
    new_dir = body.directory_path if body.directory_path is not None else config.directory_path
    new_scope = body.target_scope if body.target_scope is not None else config.scope_type
    if body.target_project_id is not None:
        new_project = body.target_project_id
    elif body.target_scope is not None and body.target_scope != KnowledgeScope.project.value:
        new_project = None
    else:
        new_project = config.related_project_id
    new_owner = body.task_owner_user_id if body.task_owner_user_id is not None else config.created_by

    # 涉及 name/dir/scope/project 任一变更时做字段组合校验（纯启停 / 仅改归属人时跳过字段校验）。
    if any(v is not None for v in (body.name, body.directory_path, body.target_scope, body.target_project_id)):
        new_name, new_dir, new_scope, new_project = await _validate_config_fields(
            session, name=new_name, directory_path=new_dir,
            scope_type=new_scope, related_project_id=new_project,
        )
    # 当归属人 / scope / project 任一变更时，重新校验业务归属人与（新）scope 的一致性，
    # 避免改 scope 后旧归属人无法确认新口径任务。
    if any(v is not None for v in (body.task_owner_user_id, body.target_scope, body.target_project_id)):
        await _validate_task_owner(
            session, owner_user_id=new_owner,
            scope_type=new_scope, related_project_id=new_project,
        )

    before = {
        "name": config.name, "enabled": config.enabled, "scope_type": config.scope_type,
        "target_project_id": str(config.related_project_id) if config.related_project_id else None,
        "task_owner_user_id": str(config.created_by),
    }
    config.name = new_name
    config.directory_path = new_dir
    config.scope_type = new_scope
    config.related_project_id = new_project
    config.created_by = new_owner
    if body.enabled is not None:
        config.enabled = body.enabled

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.wecom_scan_config_updated.value, trace_id=trace_id,
        target_type="wecom_scan_config", target_id=config.id,
        before=before,
        after={
            "name": config.name, "enabled": config.enabled, "scope_type": config.scope_type,
            "target_project_id": str(config.related_project_id) if config.related_project_id else None,
            "task_owner_user_id": str(config.created_by),
            "directory_path_changed": body.directory_path is not None,
        },
        project_id=config.related_project_id,
    )
    await session.commit()
    owner_name, owner_role = await _owner_meta(session, config.created_by)
    return _config_out(config, await _project_name(session, config.related_project_id), owner_name, owner_role)


# ---------------------------------------------------------------------------
# 微盘目录浏览
# ---------------------------------------------------------------------------
def _wrap_wecom(exc: WeComError) -> HTTPException:
    """企微目录浏览错误 → 安全 HTTP：未配置 → 503（只回缺失项名）；其余 → 502 固定安全文案。

    **绝不**回显上游 errmsg / payload / token / url（WeComError.message 本就安全，但仍统一固定）。
    """
    if exc.code == "wecom_not_configured":
        from app.core.config import get_settings

        s = get_settings()
        miss = [n for n, v in (("WECOM_CORP_ID", s.wecom_corp_id), ("WECOM_APP_SECRET", s.wecom_app_secret)) if not v]
        return HTTPException(503, detail={
            "denied_reason": "wecom_not_configured", "message": "企业微信未配置",
            "missing_config": miss or ["WECOM_CORP_ID", "WECOM_APP_SECRET"],
        })
    return HTTPException(502, detail={
        "denied_reason": "wecom_drive_browse_failed",
        "message": "企业微信微盘访问失败，请检查配置或稍后重试",
    })


async def list_drive_spaces(caller: CallerContext, drive):
    """列微盘空间（仅 admin）。返回安全选择元数据（space_ref/name），不含 token/url/file_id。"""
    _require_admin(caller)
    try:
        spaces = await drive.list_spaces()
    except WeComError as exc:
        raise _wrap_wecom(exc)
    from app.schemas.wecom import WecomDriveSpaceOut, WecomDriveSpacesResponse

    return WecomDriveSpacesResponse(
        items=[WecomDriveSpaceOut(space_ref=s.space_ref, name=s.name) for s in spaces]
    )


async def list_drive_directories(caller: CallerContext, drive, *, space_ref: str, parent_ref: str | None):
    """列某空间/父目录下的子目录（仅 admin）。

    `space_ref`=空间选择引用（spaceid）；`parent_ref`=父目录的 directory_ref（`spaceid:<id>;fatherid:<id>`，
    钻取用）或空（根）。后端把 directory_ref 解析为 fatherid 后调用底层 client。
    """
    from app.services.wecom_client import parse_directory_path

    _require_admin(caller)
    space = (space_ref or "").strip()
    if not space or ":" in space or ";" in space:
        # space_ref 必须是裸 spaceid（不接受 directory_path 整串）。
        raise _denied(422, "wecom_invalid_space", "微盘空间标识非法")
    fatherid: str | None = None
    if parent_ref:
        try:
            sp, fid = parse_directory_path(parent_ref)
        except WeComError:
            raise _denied(422, "wecom_invalid_directory_ref", "目录标识格式非法")
        if sp != space:
            raise _denied(422, "wecom_directory_space_mismatch", "目录与所选空间不一致")
        fatherid = fid or None
    try:
        dirs = await drive.list_directories(space, fatherid)
    except WeComError as exc:
        raise _wrap_wecom(exc)
    from app.schemas.wecom import WecomDriveDirectoriesResponse, WecomDriveDirectoryOut

    return WecomDriveDirectoriesResponse(
        space_ref=space,
        items=[
            WecomDriveDirectoryOut(
                directory_ref=d.directory_ref, name=d.name,
                parent_ref=parent_ref, has_children=d.has_children,
            )
            for d in dirs
        ],
    )


async def list_records(session: AsyncSession, caller: CallerContext, config_id: uuid.UUID):
    from app.schemas.wecom import WecomScanRecordsResponse

    _require_reader(caller)
    config = await session.get(WecomScanConfig, config_id)
    if config is None:
        raise _denied(404, "wecom_scan_config_not_found", "扫描配置不存在")
    rows = list(
        (
            await session.execute(
                select(WecomScanRecord)
                .where(WecomScanRecord.config_id == config_id)
                .order_by(WecomScanRecord.created_at.desc())
            )
        ).scalars().all()
    )
    return WecomScanRecordsResponse(items=[_record_out(r) for r in rows])


# ---------------------------------------------------------------------------
# 触发扫描（API，admin）
# ---------------------------------------------------------------------------
async def trigger_scan(
    session: AsyncSession,
    caller: CallerContext,
    config_id: uuid.UUID,
    *,
    drive,
    storage: LocalFileStorage,
    llm,
    desensitizer,
    trace_id: str,
    idempotency_key: str | None,
):
    _require_admin(caller)
    config = await session.get(WecomScanConfig, config_id)
    if config is None:
        raise _denied(404, "wecom_scan_config_not_found", "扫描配置不存在")
    if not config.enabled:
        raise _denied(409, "wecom_scan_disabled", "扫描配置已停用")

    # 运行时复核业务归属人仍合法（停用 / 移出项目 / 失去治理角色 → fail-closed，不建任何任务/记录）。
    if not await _owner_still_valid(session, config):
        raise _denied(
            409, "wecom_scan_owner_invalid",
            "扫描业务归属人当前不合法（已停用 / 移出目标项目 / 失去治理角色），已阻止扫描",
        )

    # 幂等（快路径）：同 config + key 命中已存在记录 → 直接返回（不重扫）。
    if idempotency_key:
        existing = await _find_by_key(session, config_id, idempotency_key)
        if existing is not None:
            return _record_out(existing)

    record = WecomScanRecord(
        config_id=config.id, trace_id=trace_id, idempotency_key=idempotency_key,
        scan_started_at=_now(), scan_status="running",
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError:
        # 并发安全网：另一请求已抢先建同 key 记录（命中部分唯一索引）→ 回滚后重查返回，
        # 不重复扫描 / 不重复建任务；不向调用方泄露 SQL 错误或内部标识。
        await session.rollback()
        config = await session.get(WecomScanConfig, config_id)
        existing = await _find_by_key(session, config_id, idempotency_key) if idempotency_key else None
        if existing is not None:
            return _record_out(existing)
        raise _denied(409, "wecom_scan_conflict", "扫描触发冲突，请稍后重试")
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.wecom_scan_triggered.value, trace_id=trace_id,
        target_type="wecom_scan_config", target_id=config.id,
        extra={"scan_record_id": str(record.id), "scope_type": config.scope_type},
    )
    await session.commit()

    # eager 内联执行（本地/测试，返回最终计数）；非 eager 入队，由 worker 执行（返回 running）。
    from app.core.config import get_settings

    if get_settings().celery_task_always_eager:
        await run_scan(
            session, config, record,
            drive=drive, storage=storage, llm=llm, desensitizer=desensitizer,
            trace_id=trace_id, actor_caller=caller,
        )
        await session.refresh(record)
    else:
        from app.worker.tasks.wecom import drive_scan

        drive_scan.delay(str(config.id), str(record.id), trace_id)
    return _record_out(record)


# ---------------------------------------------------------------------------
# 扫描核心流程
# ---------------------------------------------------------------------------
async def run_scan(
    session: AsyncSession,
    config: WecomScanConfig,
    record: WecomScanRecord,
    *,
    drive,
    storage: LocalFileStorage,
    llm,
    desensitizer,
    trace_id: str | None,
    actor_caller: CallerContext | None,
) -> WecomScanRecord:
    """对一个配置执行一次扫描，回写 record 计数 + 终态。返回 record。"""
    # 运行时归属人复核（覆盖 Celery worker / 定时扫描的共同路径）：归属人失效 → fail-closed，
    # 不列目录、不下载、不建任何 IngestTask；扫描记录置失败 + 安全审计（不泄露内部数据）。
    if not await _owner_still_valid(session, config):
        record.scan_status = "failed"
        record.error_type = "wecom_scan_owner_invalid"
        record.error_message = "扫描业务归属人当前不合法，已 fail-closed 阻止扫描（详见审计）"
        record.scan_completed_at = _now()
        await _scan_terminal_audit(
            session, actor_caller, AuditAction.wecom_scan_failed.value, config, record,
            trace_id, extra={"error_code": "wecom_scan_owner_invalid", "stage": "owner_check"},
        )
        await session.commit()
        return record

    owner_actor = await _owner_actor(session, config)
    zone = KnowledgeZone.material.value  # Path A 入项目/公司库默认 material

    # 列目录失败 → 整次扫描 failed（不部分成功）。
    try:
        files = await drive.list_files(config.directory_path)
    except WeComError as exc:
        record.scan_status = "failed"
        record.error_type = exc.code  # 安全 code，不含上游 payload
        record.error_message = "微盘目录列举失败（详见审计）"
        record.scan_completed_at = _now()
        await _scan_terminal_audit(
            session, actor_caller, AuditAction.wecom_scan_failed.value, config, record,
            trace_id, extra={"error_code": exc.code, "stage": "list"},
        )
        await session.commit()
        return record

    discovered = len(files)
    new = dup = failed = 0
    project_id = (
        config.related_project_id
        if config.scope_type == KnowledgeScope.project.value else None
    )
    for f in files:
        # 阶段1：抓取/落盘（**无 DB 写**）。失败 → 计数后 continue，无需 rollback。
        try:
            content_hash = f.content_hash
            if content_hash and await _hash_exists(session, content_hash):
                dup += 1
                continue
            data = await drive.download_file(f.file_id)
            if not data:
                failed += 1
                continue
            if not content_hash:
                content_hash = hashlib.sha256(data).hexdigest()
                if await _hash_exists(session, content_hash):
                    dup += 1
                    continue
            # 字节经平台存储落盘（server-only ref）。
            storage_ref = storage.save(data, original_name=f.name)
        except (WeComError, StorageError, OSError):
            # 单文件抓取/落盘失败不中断整批；尚未建任务，无悬挂 ref。
            failed += 1
            continue

        # 阶段2：建 path_a_wecom 任务 + 审计 + 复用统一处理链（提交后 enqueue 不阻断）。
        task = IngestTask(
            source=IngestSource.path_a_wecom.value,
            source_file_ref=storage_ref,
            source_file_name=safe_filename(f.name),
            source_file_mime_type=f.mime,
            source_file_size=len(data),
            source_file_hash=content_hash,
            status=IngestStatus.processing.value,
            target_scope=config.scope_type,
            target_project_id=project_id,
            target_zone=zone,
            created_by=config.created_by,
        )
        session.add(task)
        await session.flush()
        await audit_service.record_event(
            session, caller=owner_actor, log_type=AuditLogType.operation,
            action=AuditAction.ingest_task_created.value, trace_id=trace_id or "",
            target_type="ingest_task", target_id=task.id,
            after={"status": task.status, "source": task.source, "target_scope": task.target_scope},
            project_id=project_id,
        )
        await session.commit()
        # 复用统一处理链（与 Path B 完全一致）：eager 内联 / 非 eager 入队。
        # 任务已提交；enqueue 失败也只是处理待重试，不丢任务、不破坏批次。
        await enqueue_ingest_processing(
            session, task.id, storage=storage, llm=llm, desensitizer=desensitizer, trace_id=trace_id
        )
        new += 1

    record.discovered_count = discovered
    record.new_count = new
    record.duplicate_count = dup
    record.failed_count = failed
    record.scan_status = "completed"
    record.scan_completed_at = _now()
    config.last_scan_at = _now()
    await _scan_terminal_audit(
        session, actor_caller, AuditAction.wecom_scan_completed.value, config, record,
        trace_id, extra={"discovered": discovered, "new": new, "duplicate": dup, "failed": failed},
    )
    await session.commit()
    return record


async def _scan_terminal_audit(session, actor_caller, action, config, record, trace_id, *, extra):
    """扫描级终态审计：手动触发归属 admin caller；定时扫描无业务发起人 → system 事件。"""
    safe_extra = {"scan_record_id": str(record.id), "scope_type": config.scope_type, **extra}
    if actor_caller is not None:
        await audit_service.record_event(
            session, caller=actor_caller, log_type=AuditLogType.operation,
            action=action, trace_id=trace_id or "",
            target_type="wecom_scan_config", target_id=config.id, extra=safe_extra,
        )
    else:
        await audit_service.record_system_event(
            session, log_type=AuditLogType.operation, action=action, trace_id=trace_id or "",
            target_type="wecom_scan_config", target_id=config.id, extra=safe_extra,
        )


async def scan_config_by_id(
    session: AsyncSession,
    config_id: uuid.UUID,
    *,
    drive,
    storage: LocalFileStorage,
    llm,
    desensitizer,
    trace_id: str | None,
) -> None:
    """定时/worker 入口：按 config_id 跑一次扫描（system 归属，无 admin caller）。"""
    config = await session.get(WecomScanConfig, config_id)
    if config is None or not config.enabled:
        return
    record = WecomScanRecord(
        config_id=config.id, trace_id=trace_id, scan_started_at=_now(), scan_status="running",
    )
    session.add(record)
    await session.flush()
    await run_scan(
        session, config, record,
        drive=drive, storage=storage, llm=llm, desensitizer=desensitizer,
        trace_id=trace_id, actor_caller=None,
    )

