"""Move private delegations into the shared workspace without replaying old actions.

The retired table is kept as rollback material. No runtime reads or writes it.
Downgrade deliberately retains imported conversations: users may have continued
them after upgrade, and rolling schema back must not delete their new work.
"""

import uuid
from datetime import timedelta

import sqlalchemy as sa

from alembic import op
from app.core.personal_information import redact_personal_information

revision = "0098_legacy_agent_sessions"
down_revision = "0097_agent_runtime"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    legacy = sa.Table("knowledge_agent_tasks", metadata, autoload_with=bind)
    sessions = sa.Table("ai_workspace_sessions", metadata, autoload_with=bind)
    runs = sa.Table("ai_workspace_runs", metadata, autoload_with=bind)
    messages = sa.Table("ai_workspace_messages", metadata, autoload_with=bind)
    # Keyset pages keep the migration bounded even for a large private history.
    last = None
    while True:
        query = sa.select(legacy).order_by(legacy.c.id).limit(200)
        if last is not None:
            query = query.where(legacy.c.id > last)
        rows = bind.execute(query).mappings().all()
        if not rows:
            break
        for item in rows:
            task_id = item["id"]
            last = task_id
            if bind.scalar(sa.select(sessions.c.id).where(sessions.c.id == task_id)):
                # A replay must not overwrite a renamed or continued conversation.
                # 0097's downgrade removes agent_key; restore only that identity
                # for an imported conversation when upgrading through it again.
                bind.execute(
                    sessions.update()
                    .where(sessions.c.id == task_id, sessions.c.agent_key.is_(None))
                    .values(agent_key="knowledge-maintenance")
                )
                continue
            identity = task_id if isinstance(task_id, uuid.UUID) else uuid.UUID(str(task_id))
            run_id = uuid.uuid5(identity, "workspace-legacy-run").hex
            content = redact_personal_information(item["instruction"]) or "历史资料查找任务"
            finished = item["status"] in {"ready", "empty"}
            bind.execute(
                sessions.insert().values(
                    id=task_id,
                    user_id=item["user_id"],
                    role=item["role"],
                    title=content[:48],
                    agent_key="knowledge-maintenance",
                    active_run_id=None,
                    event_seq=0,
                    created_at=item["created_at"],
                    updated_at=item["created_at"],
                )
            )
            # Reflected UUID columns use their dialect-native Python type.
            uuid_type = isinstance(runs.c.id.type, sa.Uuid)
            persisted_run_id = uuid.UUID(run_id) if uuid_type else run_id
            bind.execute(
                runs.insert().values(
                    id=persisted_run_id,
                    session_id=task_id,
                    status="completed" if finished else "failed",
                    model_ref="system_default",
                    context_key=item["library_key"],
                    instruction=content,
                    source_refs=[],
                    runtime_state={"legacy_task": True},
                    error_code=None if finished else "interrupted",
                    created_at=item["created_at"],
                    finished_at=item["created_at"],
                )
            )
            response = (
                "历史资料查找任务已迁入本会话。原结果未重新核验，请继续交代需要查找或维护的内容。"
                if finished
                else "历史任务未完成，未自动重新执行。请继续说明当前目标后重新处理。"
            )
            for role, value in (("user", content), ("assistant", response)):
                message_id = uuid.uuid5(identity, "workspace-legacy-" + role)
                bind.execute(
                    messages.insert().values(
                        id=message_id
                        if isinstance(messages.c.id.type, sa.Uuid)
                        else message_id.hex,
                        session_id=task_id,
                        run_id=persisted_run_id,
                        role=role,
                        content=value,
                        created_at=item["created_at"]
                        + (timedelta(microseconds=1) if role == "assistant" else timedelta()),
                    )
                )


def downgrade():
    # Data copies are retained to protect post-upgrade messages and edits. The
    # previous schema supports these rows; 0097 removes only its schema additions.
    pass
