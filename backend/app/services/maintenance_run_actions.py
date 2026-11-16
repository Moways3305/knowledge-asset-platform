"""Run lifecycle commands. Issues are independent of disposable run history."""

from sqlalchemy import delete, select

from app.db.utils import utc_now
from app.models.maintenance_agent import MaintenanceRun, MaintenanceRunItem
from app.schemas.enums import AuditLogType
from app.schemas.maintenance_agent import RunDeleteResult, RunOut
from app.services import audit
from app.services import maintenance_access as access
from app.services.maintenance_reports import cancel_pending

ACTIVE = {"queued", "running"}


async def _rows(session, caller, key, ids):
    # Policy -> run lock order matches workers and policy changes.
    from app.services.maintenance_agent import _library

    policy = await _library(session, caller, key, lock=True)
    if not policy:
        raise access.reject()
    rows = (
        await session.scalars(
            select(MaintenanceRun)
            .where(MaintenanceRun.policy_id == policy.id, MaintenanceRun.id.in_(ids))
            .order_by(MaintenanceRun.id)
            .with_for_update()
        )
    ).all()
    if len(rows) != len(set(ids)) or any(
        r.includes_l5 and not caller.can_discover_l5 for r in rows
    ):
        raise access.reject()
    return policy, rows


async def _audit(session, caller, run, action, trace_id):
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=action,
        trace_id=trace_id,
        target_type="maintenance_run",
        target_id=run.id,
    )


async def cancel(session, caller, key, run_id, trace_id):
    _, rows = await _rows(session, caller, key, [run_id])
    run = rows[0]
    if run.status == "cancelled":
        return RunOut.model_validate(run, from_attributes=True)
    if run.status not in ACTIVE:
        raise access.reject(409, "本轮巡检已结束，请刷新记录")
    now = utc_now()
    run.status, run.finished_at, run.last_progress_at = "cancelled", now, now
    run.claim_token, run.lease_until = None, None
    await cancel_pending(session, run, "user_cancelled", now)
    await _audit(session, caller, run, "maintenance.run_cancelled", trace_id)
    await session.commit()
    return RunOut.model_validate(run, from_attributes=True)


async def delete_records(session, caller, key, ids, trace_id):
    _, rows = await _rows(session, caller, key, ids)
    if any(r.status in ACTIVE for r in rows):
        raise access.reject(409, "正在执行的巡检请先取消，再删除记录")
    for run in rows:
        await _audit(session, caller, run, "maintenance.run_deleted", trace_id)
    await session.execute(delete(MaintenanceRunItem).where(MaintenanceRunItem.run_id.in_(ids)))
    await session.execute(delete(MaintenanceRun).where(MaintenanceRun.id.in_(ids)))
    await session.commit()
    return RunDeleteResult(deleted_count=len(rows))


async def retry(session, caller, key, run_id, trace_id):
    from app.services.maintenance_jobs import start_run

    policy, rows = await _rows(session, caller, key, [run_id])
    previous = rows[0]
    if previous.status not in {"partial", "cancelled"}:
        raise access.reject(409, "仅可重试已结束巡检中的未完成项")
    if previous.scope_snapshot is None:
        raise access.reject(409, "旧记录未保存逐项结果，请重新发起全面巡检")
    if not caller.can_discover_l5 and policy.authorized_role in {"boss", "consulting_director"}:
        raise access.reject(409, "请先以当前身份重新保存巡检配置")
    run = await start_run(session, policy, kind="retry", retry_run_id=run_id)
    if not run:
        raise access.reject(409, "巡检授权已失效，请重新保存配置授权")
    await _audit(session, caller, run, "maintenance.run_retried", trace_id)
    await session.commit()
    return RunOut.model_validate(run, from_attributes=True)
