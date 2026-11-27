"""Deliver merged PR #243 from the completed v1.5.0 release, without changing runtime settings."""

import deploy_maintenance_update as delivery
import deploy_stage_release as stage
import execute_production_cutover as cutover
from prepare_production_release import require

REVISION = "57cd2720d6e2cef035adc6368846f7888bbfafa1"
VERSION = "v1.6.0"
BASELINE = "07d013228b8decb4651ec3dee44ae01900e8d43f"
BASELINE_VERSION = "v1.5.0"
BASELINE_SCHEMA = "0095_knowledge_tasks"
SCHEMA = "0096_ai_workspace"
ENTRIES = [
    {"kind": "new", "text": "新增独立 AI 工作空间，可从平台入口打开新页面，持续处理会话任务。"},
    {
        "kind": "new",
        "text": "支持模型与知识上下文选择、执行进度、停止重试，以及右侧文档预览、编辑和下载。",
    },
    {
        "kind": "improved",
        "text": "Agent 独立于通用会话，知识维护入口和原有巡检、通知、复检流程继续保留。",
    },
    {
        "kind": "improved",
        "text": "工具栏统一使用图标与悬浮说明，优化窄屏布局并保留编辑内容和阅读位置。",
    },
]


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
    stage.RELEASE_TITLE = "AI 工作空间与独立 Agent 入口"
    # 0096 only adds workspace tables. Compare every original table/column
    # unchanged; the 0094 JSON-to-join-table projection is not applicable here.
    stage.table_snapshot = cutover.table_snapshot


if __name__ == "__main__":
    raise SystemExit(delivery.main(configure))
