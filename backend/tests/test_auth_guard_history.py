"""Large successful histories must not be materialized during failed-login checks."""

from datetime import timedelta

import pytest
from sqlalchemy import event

from app.core.config import Settings
from app.db.utils import utc_now
from app.models.auth_security import AuthLoginAttempt
from app.services import auth_security


async def test_success_history_is_not_loaded_as_attempt_objects(db_session):
    now = utc_now()
    db_session.add_all(
        AuthLoginAttempt(
            identifier_hash="a" * 64,
            ip_hash="b" * 64,
            result="success",
            created_at=now - timedelta(seconds=1),
        )
        for _ in range(500)
    )
    await db_session.commit()
    db_session.expunge_all()
    loaded = []

    def record_load(attempt, context):
        loaded.append(attempt.id)

    event.listen(AuthLoginAttempt, "load", record_load)
    try:
        result = await auth_security.check_login_guard(
            db_session, identifier_hash="a" * 64, ip_hash="b" * 64
        )
    finally:
        event.remove(AuthLoginAttempt, "load", record_load)
    assert not result.blocked
    assert result.failed_count == 0
    assert loaded == [], "Guard loaded full history instead of aggregate failure statistics"


@pytest.mark.parametrize("anchor", ["success", "unlocked"])
async def test_aggregate_preserves_strict_reset_and_independent_ip_window(
    db_session, monkeypatch, anchor
):
    now = utc_now()
    monkeypatch.setattr(auth_security, "utc_now", lambda: now)
    entries = [
        # Out of the 15-minute window, including a newer reset than other history.
        ("failed", 901),
        ("failed", 900),  # inclusive start
        ("failed", 60),  # same instant as reset is excluded only for identifier
        (anchor, 60),
        ("failed", 30),
        ("locked", 20),
        ("rate_limited", 10),
    ]
    db_session.add_all(
        AuthLoginAttempt(
            identifier_hash="a" * 64,
            ip_hash="b" * 64,
            result=result,
            created_at=now - timedelta(seconds=age),
        )
        for result, age in entries
    )
    await db_session.commit()
    settings = Settings(auth_max_failed_attempts=4, auth_ip_max_failed_attempts=5)
    identifier = await auth_security.check_login_guard(
        db_session, identifier_hash="a" * 64, ip_hash=None, settings=settings
    )
    assert not identifier.blocked
    assert identifier.failed_count == 3
    ip = await auth_security.check_login_guard(
        db_session, identifier_hash="a" * 64, ip_hash="b" * 64, settings=settings
    )
    assert ip.blocked and ip.result == "rate_limited" and ip.failed_count == 5


async def test_identifier_lock_expires_until_a_new_failure(db_session, monkeypatch):
    now = utc_now()
    monkeypatch.setattr(auth_security, "utc_now", lambda: now)
    db_session.add_all(
        AuthLoginAttempt(
            identifier_hash="a" * 64,
            result="failed",
            created_at=now - timedelta(minutes=age),
        )
        for age in [8, 7, 6]
    )
    await db_session.commit()
    settings = Settings(auth_max_failed_attempts=3, auth_lockout_minutes=5)
    result = await auth_security.check_login_guard(
        db_session, identifier_hash="a" * 64, ip_hash=None, settings=settings
    )
    assert not result.blocked and result.failed_count == 3
    db_session.add(AuthLoginAttempt(identifier_hash="a" * 64, result="failed", created_at=now))
    await db_session.commit()
    result = await auth_security.check_login_guard(
        db_session, identifier_hash="a" * 64, ip_hash=None, settings=settings
    )
    assert result.blocked and result.result == "locked" and result.failed_count == 4
