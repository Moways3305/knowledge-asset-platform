"""自助 WorkBuddy 接入 token 的请求 / 响应 schema。

安全：状态视图绝不含 token 明文 / token_hash / header / cookie / provider 内部标识。
明文 token 仅在生成 / 重置成功时一次性返回。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WorkbuddyPlatform = Literal["windows", "macos"]
WorkbuddyArchitecture = Literal["x64", "arm64"]


class WorkbuddyTokenStatusOut(BaseModel):
    """当前用户的 WorkBuddy 绑定状态（无 token 明文 / token_hash）。"""

    enabled: bool
    provider: str = "workbuddy"
    bound_user_name: str | None = None
    last_rotated_at: datetime | None = None
    last_connected_at: datetime | None = None


class WorkbuddyTokenRegenerateIn(BaseModel):
    """平台只影响本次下发的本地命令；绑定用户始终从服务端 caller 解析。"""

    platform: WorkbuddyPlatform


class WorkbuddyTokenCreatedOut(BaseModel):
    """生成 / 重置结果：明文 token 仅此一次返回，附可直接复制的 mcp.json 配置。"""

    token: str
    mcp_config: dict
    platform: WorkbuddyPlatform


class WorkbuddyConnectorArtifactOut(BaseModel):
    platform: WorkbuddyPlatform
    architecture: WorkbuddyArchitecture
    version: str
    filename: str
    sha256: str
    download_path: str
    release_status: Literal["production", "internal"]
    signed: bool
    notarized: bool


class WorkbuddyConnectorManifestOut(BaseModel):
    version: str
    artifacts: list[WorkbuddyConnectorArtifactOut]
