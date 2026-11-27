"""Deliver merged PR #244 from the completed v1.6.0 release with no schema change."""

import deploy_maintenance_update as delivery
import deploy_stage_release as stage
import execute_production_cutover as cutover
from prepare_production_release import require
from production_frontend_shutdown import FRONTEND, stop_frontend, validate_frontend

REVISION = "f9d4cdbf220e65255b88513bb16fffd9f8d36c1f"
VERSION = "v1.6.1"
BASELINE = "57cd2720d6e2cef035adc6368846f7888bbfafa1"
BASELINE_VERSION = "v1.6.0"
BASELINE_SCHEMA = "0096_ai_workspace"
SCHEMA = "0096_ai_workspace"
ENTRIES = [
    {
        "kind": "fixed",
        "text": "知识维护 Agent 留在 AI 工作空间内，切换和返回时保留会话、未发送输入与文档草稿。",
    },
    {
        "kind": "fixed",
        "text": "通知与任务直达对应记录，正确处理已完成审批、历史上传和跨知识库维护待办。",
    },
    {
        "kind": "improved",
        "text": "知识、项目和审批列表保留筛选与分页，查看详情后可返回原位置。",
    },
    {
        "kind": "fixed",
        "text": "修正上传来源、项目删除和帮助章节等返回路径，并按账号与角色隔离返回记录。",
    },
]


class NavigationRuntime(stage.StageRuntime):
    def stop(self, name, identity, *, grace=120):
        if name != FRONTEND:
            return super().stop(name, identity, grace=grace)
        original = self.state["originals"][name]
        if identity == original["Id"]:
            reference, token = original, None
        else:
            require(self.state["new"].get(name) == identity, "unexpected_frontend_identity")
            reference, token = self.owned(identity), self.token
        stop_frontend(self.r, reference, token=token)


def validate_inventory(runner, directory):
    old = delivery.capture_inventory(runner, directory)
    validate_frontend(old[FRONTEND])
    return old


def select_profile(record):
    revision = record.get("revision")
    require(revision != REVISION, "release_already_deployed")
    require(
        revision == BASELINE and record.get("version") == BASELINE_VERSION,
        "unsupported_baseline",
    )
    stage.BASELINE = BASELINE
    stage.BASELINE_VERSION = BASELINE_VERSION
    stage.BASELINE_SCHEMA = BASELINE_SCHEMA
    stage.RELEASE_ENTRIES = [dict(entry) for entry in ENTRIES]


def configure():
    delivery.REVISION, delivery.VERSION = REVISION, VERSION
    delivery.select_profile = select_profile
    delivery.configure()
    stage.SCHEMA = SCHEMA
    stage.RELEASE_TITLE = "全站导航与 Agent 工作空间修复"
    stage.validate_inventory = validate_inventory
    stage.StageRuntime = NavigationRuntime
    # Include all existing workspace sessions, artifacts and model settings in
    # the unchanged-row verification, alongside every other business table.
    stage.table_snapshot = cutover.table_snapshot


if __name__ == "__main__":
    raise SystemExit(delivery.main(configure))
