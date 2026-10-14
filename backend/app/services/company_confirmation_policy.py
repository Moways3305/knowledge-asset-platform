"""Shared read/write policy for independent company confirmation seats."""

from app.models.review import CompanyAssetReviewDecision
from app.schemas.enums import CompanyAssetDecision, CompanyRole
from app.schemas.permission import CallerContext


def select_confirmation_role(
    caller: CallerContext, states: dict[str, CompanyAssetReviewDecision]
) -> str | None:
    for role in (CompanyRole.boss.value, CompanyRole.consulting_director.value):
        if role not in caller.active_company_roles:
            continue
        current = states.get(role)
        if current is not None and current.decision == CompanyAssetDecision.confirmed.value:
            continue
        other_role = (
            CompanyRole.consulting_director.value
            if role == CompanyRole.boss.value
            else CompanyRole.boss.value
        )
        other = states.get(other_role)
        if (
            other is not None
            and other.decision == CompanyAssetDecision.confirmed.value
            and other.actor_user_id == caller.user_id
        ):
            continue
        return role
    return None
