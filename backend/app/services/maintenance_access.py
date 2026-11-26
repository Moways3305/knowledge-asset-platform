"""Live authority for scheduled maintenance and its read projections."""

import uuid

from fastapi import HTTPException
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import selectinload

# Compatibility export for scan workers; one shared implementation normalizes time.
from app.db.utils import as_utc as stamp  # noqa: F401
from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import (
    MaintenanceDigest,
    MaintenanceDigestIssue,
    MaintenanceIssue,
    MaintenancePolicy,
)
from app.schemas.permission import AccessChannel, AccessLayer
from app.services.original_access import has_active_grant
from app.services.permission import (
    build_caller_context,
    decide,
    discovery_filter,
)
from app.services.permission_rules import load_access_policy


def reject(status=404, message="知识库或巡检记录不存在或不可访问"):
    return HTTPException(
        status, detail={"denied_reason": "maintenance_agent_denied", "message": message}
    )


def eligible(asset):
    return bool(
        asset
        and asset.deleted_at is None
        and asset.scope in {"company", "project"}
        and asset.asset_status in {"active", "needs_update"}
    )


def scope_filter(project_id=None):
    return and_(
        KnowledgeAsset.deleted_at.is_(None),
        KnowledgeAsset.asset_status.in_(["active", "needs_update"]),
        KnowledgeAsset.scope == ("project" if project_id else "company"),
        KnowledgeAsset.project_id == project_id if project_id else True,
    )


def manager_filter(caller, *, include_inactive=False):
    if not caller.is_active or not caller.is_business_user:
        return false()
    projects = [
        key for key, role in caller.active_project_roles.items() if role == "project_manager"
    ]
    return and_(
        discovery_filter(caller, include_inactive=include_inactive),
        KnowledgeAsset.confidentiality_level != "L5" if not caller.can_discover_l5 else True,
        or_(
            and_(
                KnowledgeAsset.scope == "company",
                or_(
                    caller.can_discover_l5,
                    and_(
                        KnowledgeAsset.maintenance_delegated.is_(True),
                        KnowledgeAsset.maintainer_user_id == caller.user_id,
                    ),
                ),
            ),
            and_(KnowledgeAsset.scope == "project", KnowledgeAsset.project_id.in_(projects)),
        ),
    )


def responsibility_filter(caller):
    business = (
        select(UserCompanyRole.id)
        .where(
            UserCompanyRole.user_id == KnowledgeAsset.maintainer_user_id,
            UserCompanyRole.status == "active",
            UserCompanyRole.company_role.in_(["boss", "consulting_director", "consultant"]),
        )
        .correlate(KnowledgeAsset)
        .exists()
    )
    governor = (
        select(UserCompanyRole.id)
        .where(
            UserCompanyRole.user_id == KnowledgeAsset.maintainer_user_id,
            UserCompanyRole.status == "active",
            UserCompanyRole.company_role.in_(["boss", "consulting_director"]),
        )
        .correlate(KnowledgeAsset)
        .exists()
    )
    project_manager = (
        select(ProjectMember.id)
        .where(
            ProjectMember.user_id == KnowledgeAsset.maintainer_user_id,
            ProjectMember.project_id == KnowledgeAsset.project_id,
            ProjectMember.status == "active",
            ProjectMember.project_role == "project_manager",
        )
        .correlate(KnowledgeAsset)
        .exists()
    )
    active_user = (
        select(User.id)
        .where(User.id == KnowledgeAsset.maintainer_user_id, User.status == "active")
        .correlate(KnowledgeAsset)
        .exists()
    )
    assigned_valid = and_(
        active_user,
        business,
        or_(KnowledgeAsset.confidentiality_level != "L5", governor),
        or_(
            and_(
                KnowledgeAsset.scope == "company",
                or_(governor, KnowledgeAsset.maintenance_delegated.is_(True)),
            ),
            and_(KnowledgeAsset.scope == "project", project_manager),
        ),
    )
    return or_(KnowledgeAsset.maintainer_user_id == caller.user_id, ~assigned_valid)


def visible_issue_query(caller, *, mine=False):
    from app.services.maintenance_rules import RETIRED

    visible = select(KnowledgeAsset.id).where(
        manager_filter(caller),
        KnowledgeAsset.deleted_at.is_(None),
        KnowledgeAsset.scope.in_(["company", "project"]),
        KnowledgeAsset.asset_status.in_(["active", "needs_update"]),
    )
    query = (
        select(MaintenanceIssue)
        .join(KnowledgeAsset, MaintenanceIssue.asset_id == KnowledgeAsset.id)
        .join(MaintenancePolicy, MaintenanceIssue.policy_id == MaintenancePolicy.id)
        .where(
            MaintenanceIssue.rule.notin_(RETIRED),
            MaintenanceIssue.asset_id.in_(visible),
            or_(
                MaintenanceIssue.related_asset_id.is_(None),
                MaintenanceIssue.related_asset_id.in_(visible),
            ),
            or_(
                and_(KnowledgeAsset.scope == "company", MaintenancePolicy.project_id.is_(None)),
                and_(
                    KnowledgeAsset.scope == "project",
                    KnowledgeAsset.project_id == MaintenancePolicy.project_id,
                ),
            ),
        )
    )
    return query.where(responsibility_filter(caller)) if mine else query


def digest_issue_query(caller, digest_id):
    from app.services.maintenance_rules import SUGGESTIONS

    return (
        visible_issue_query(caller, mine=True)
        .join(MaintenanceDigestIssue, MaintenanceDigestIssue.issue_id == MaintenanceIssue.id)
        .join(MaintenanceDigest, MaintenanceDigest.id == MaintenanceDigestIssue.digest_id)
        .where(
            MaintenanceDigest.id == digest_id,
            MaintenanceDigest.recipient_id == caller.user_id,
            MaintenanceIssue.rule.notin_(SUGGESTIONS),
        )
    )


def library_allowed(caller, project_id):
    return bool(
        caller.is_active
        and caller.is_business_user
        and (
            caller.can_discover_l5
            if project_id is None
            else caller.active_project_roles.get(project_id) == "project_manager"
            and project_id in caller.active_project_ids
        )
    )


async def actor_context(session, user_id, role):
    user = await session.scalar(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.company_roles), selectinload(User.project_members))
    )
    if (
        not user
        or user.status != "active"
        or not any(r.company_role == role and r.status == "active" for r in user.company_roles)
    ):
        return None
    return build_caller_context(user, active_company_role=role)


async def original_allowed(session, caller, asset, *, agent=False):
    if not caller or not eligible(asset):
        return False
    policy = await load_access_policy(session)
    grant = await has_active_grant(session, caller.user_id, asset.id)
    return decide(
        caller,
        asset,
        AccessLayer.original,
        channel=AccessChannel.agent if agent else AccessChannel.human,
        policy=policy,
        has_original_grant=grant,
    ).allowed


async def recipients(session, asset):
    """Use the same live assignment/role policy as manual maintenance."""
    from app.services.knowledge_responsibility import maintainer_contexts, responsible_for

    candidates = await maintainer_contexts(session)
    ids = set(responsible_for(asset, candidates))
    return [{"id": str(user.id), "name": user.name} for user, _ in candidates if user.id in ids]


def parse_key(key):
    if key == "company":
        return None
    try:
        prefix, value = key.split(":", 1)
        if prefix == "project":
            return uuid.UUID(value)
    except (ValueError, AttributeError):
        pass
    raise reject()
