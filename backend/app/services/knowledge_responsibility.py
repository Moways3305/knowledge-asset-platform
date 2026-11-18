"""One live responsibility policy for manual maintenance and scheduled scans."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.identity import User
from app.services.permission import build_caller_context, knowledge_maintainer_allowed


async def maintainer_contexts(session):
    users = (
        await session.scalars(
            select(User)
            .where(User.status == "active")
            .options(selectinload(User.company_roles), selectinload(User.project_members))
        )
    ).all()
    return [
        (
            user,
            [
                build_caller_context(user, active_company_role=role.company_role)
                for role in user.company_roles
                if role.status == "active"
            ],
        )
        for user in users
    ]


def eligible_maintainers(asset, candidates):
    # Any assigned active business identity may qualify, regardless of default identity.
    return [
        {"id": str(user.id), "name": user.name}
        for user, contexts in candidates
        if any(
            asset.deleted_at is None and knowledge_maintainer_allowed(ctx, asset)
            for ctx in contexts
        )
    ]


def responsible_for(asset, candidates):
    ids = [uuid.UUID(item["id"]) for item in eligible_maintainers(asset, candidates)]
    return [asset.maintainer_user_id] if asset.maintainer_user_id in ids else ids


async def responsible_recipients(session, asset):
    return responsible_for(asset, await maintainer_contexts(session))
