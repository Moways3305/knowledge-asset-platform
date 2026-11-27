"""Deliver PR #246 using the existing same-schema, bounded-shutdown rollout."""

from pathlib import Path

import deploy_navigation_update as navigation

REVISION = "3caca683a38886ba491edf9352eb6499514bcad8"
VERSION = "v1.7.1"
BASELINE = "41e68da55b8f353d3ec55821ecfe815557ff6641"
BASELINE_VERSION = "v1.7.0"
SCHEMA = "0098_legacy_agent_sessions"


def configure():
    navigation.REVISION, navigation.VERSION = REVISION, VERSION
    navigation.BASELINE, navigation.BASELINE_VERSION = BASELINE, BASELINE_VERSION
    navigation.BASELINE_SCHEMA = navigation.SCHEMA = SCHEMA
    navigation.ENTRIES = navigation.delivery.read_record(
        Path(__file__).resolve().parents[1]
        / "release-notes"
        / "ai-workspace-composer-agent-picker.json"
    )
    # Ordinary full-table comparison preserves already-used sessions/actions.
    # The one-time 0096 -> 0098 migration proof must not run again here.
    navigation.configure()
    navigation.stage.RELEASE_TITLE = "AI 空间同页导航与会话智能体选择"


if __name__ == "__main__":
    raise SystemExit(navigation.delivery.main(configure))
