"""Server-authoritative, session-bound active company-role selection."""

from __future__ import annotations

import hashlib
import hmac
import logging

from app.core.config import Settings, get_settings
from app.models.identity import User
from app.schemas.enums import CompanyRole, RoleStatus

_log = logging.getLogger("auth.identity")

ACTIVE_ROLE_COOKIE_NAME = "kap_active_company_role"
_FALLBACK_SECRET = "kap-dev-active-work-identity-hmac-fallback"
_DEFAULT_ROLE_PRIORITY = (
    CompanyRole.admin.value,
    CompanyRole.boss.value,
    CompanyRole.consulting_director.value,
    CompanyRole.consultant.value,
)
_DEFAULT_BUSINESS_ROLE_PRIORITY = (
    CompanyRole.boss.value,
    CompanyRole.consulting_director.value,
    CompanyRole.consultant.value,
)


class InvalidActiveRoleCookie(ValueError):
    """A session-bound role cookie was present but failed validation."""


def assigned_active_roles(user: User) -> list[str]:
    return [row.company_role for row in user.company_roles if row.status == RoleStatus.active.value]


def default_active_role(user: User) -> str | None:
    assigned = set(assigned_active_roles(user))
    return next((role for role in _DEFAULT_ROLE_PRIORITY if role in assigned), None)


def default_active_business_role(user: User) -> str | None:
    """Resolve the highest-priority assigned business role for non-browser callers."""
    assigned = set(assigned_active_roles(user))
    return next((role for role in _DEFAULT_BUSINESS_ROLE_PRIORITY if role in assigned), None)


def _secret(settings: Settings | None = None) -> bytes:
    configured = ((settings or get_settings()).csrf_token_secret or "").strip()
    return (configured or _FALLBACK_SECRET).encode("utf-8")


def _signature(
    *, session_token: str, user_id: str, role: str, settings: Settings | None = None
) -> str:
    message = f"active-work-identity\n{session_token}\n{user_id}\n{role}".encode()
    return hmac.new(_secret(settings), message, hashlib.sha256).hexdigest()


def issue_role_cookie_value(
    *, session_token: str, user: User, role: str, settings: Settings | None = None
) -> str:
    if role not in assigned_active_roles(user):
        raise ValueError("active_company_role_not_assigned")
    signature = _signature(
        session_token=session_token,
        user_id=str(user.id),
        role=role,
        settings=settings,
    )
    return f"{role}.{signature}"


def resolve_active_role(
    *,
    user: User,
    session_token: str | None,
    cookie_value: str | None,
    settings: Settings | None = None,
) -> str | None:
    fallback = default_active_role(user)
    if not session_token or cookie_value is None:
        return fallback
    if "." not in cookie_value:
        _log.warning("identity.active_role_cookie_invalid reason=malformed")
        raise InvalidActiveRoleCookie("active_company_role_cookie_invalid")
    role, provided = cookie_value.rsplit(".", 1)
    if role not in assigned_active_roles(user):
        _log.warning("identity.active_role_cookie_invalid reason=role_not_assigned role=%s", role)
        raise InvalidActiveRoleCookie("active_company_role_cookie_invalid")
    expected = _signature(
        session_token=session_token,
        user_id=str(user.id),
        role=role,
        settings=settings,
    )
    if not hmac.compare_digest(provided, expected):
        _log.warning("identity.active_role_cookie_invalid reason=signature_mismatch role=%s", role)
        raise InvalidActiveRoleCookie("active_company_role_cookie_invalid")
    return role
