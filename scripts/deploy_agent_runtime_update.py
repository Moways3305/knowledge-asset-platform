"""Deliver merged PR #245 with verified, non-replaying legacy session migration."""

from pathlib import Path

import agent_runtime_migration_check as migration_check
import deploy_maintenance_update as delivery
import deploy_navigation_update as navigation
import deploy_stage_release as stage
from prepare_production_release import require

REVISION = "41e68da55b8f353d3ec55821ecfe815557ff6641"
VERSION = "v1.7.0"
BASELINES = {
    "57cd2720d6e2cef035adc6368846f7888bbfafa1": ("v1.6.0", "0096_ai_workspace"),
    "f9d4cdbf220e65255b88513bb16fffd9f8d36c1f": ("v1.6.1", "0096_ai_workspace"),
}
SCHEMA = "0098_legacy_agent_sessions"


def select_profile(record):
    revision = record.get("revision")
    require(revision != REVISION, "release_already_deployed")
    baseline = BASELINES.get(revision)
    require(baseline is not None and record.get("version") == baseline[0], "unsupported_baseline")
    stage.BASELINE = revision
    stage.BASELINE_VERSION, stage.BASELINE_SCHEMA = baseline
    entries = delivery.read_record(
        Path(__file__).resolve().parents[1]
        / "release-notes"
        / "maintenance-agent-shared-runtime.json"
    )
    if stage.BASELINE_VERSION == "v1.6.0":
        entries = [*navigation.ENTRIES, *entries]
    stage.RELEASE_ENTRIES = entries


class AgentRuntime(navigation.NavigationRuntime):
    """Retain bounded frontend shutdown for original and candidate containers."""

    def helper(self, command, mounts=(), *, image=None, network="none", env=()):
        migrating = command == ["python", "-m", "alembic", "upgrade", "head"]
        if migrating:
            require(
                network == "kap_internal" and image == self.helper_image,
                "unexpected_migration_runtime",
            )
            snapshot = self.directory / "database-before-private.json"
            require(
                snapshot.is_file() and snapshot.resolve(strict=True) == snapshot,
                "migration_snapshot_missing",
            )
        super().helper(command, mounts, image=image, network=network, env=env)
        if migrating:
            print("正在只读核对历史任务迁移与脱敏结果。", flush=True)
            super().helper(
                ["python", "-c", migration_check.redaction_check_code()],
                mounts=(
                    f"type=bind,src={snapshot},dst=/migration-check/database-before-private.json,readonly",
                ),
                image=image,
                network=network,
                env=env,
            )


def configure():
    delivery.REVISION, delivery.VERSION = REVISION, VERSION
    delivery.select_profile = select_profile
    delivery.configure()
    stage.SCHEMA = SCHEMA
    stage.RELEASE_TITLE = "知识维护 Agent 连续任务与共享运行框架"
    stage.validate_inventory = navigation.validate_inventory
    stage.StageRuntime = AgentRuntime
    stage.table_snapshot = migration_check.table_snapshot


if __name__ == "__main__":
    raise SystemExit(delivery.main(configure))
