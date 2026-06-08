"""企微微盘扫描 API 的请求 / 响应 schema（R6，契约 §17）。

响应只含安全运营元数据：**绝不**含内部存储引用 / 源文件引用 / 微盘下载 URL /
微盘 file_id / access_token / WeKnora id / 业务原文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


# ---- 微盘目录浏览（admin-only 配置 UI 用）----
# 只承载目录**选择**所需安全字段：space_ref / directory_ref（= 可保存的配置串）/ name。
# 绝不含普通文件 file_id / download_url / access_token / cookie / 原始 payload。
class WecomDriveSpaceOut(BaseModel):
    space_ref: str
    name: str


class WecomDriveSpacesResponse(BaseModel):
    items: list[WecomDriveSpaceOut]


class WecomDriveDirectoryOut(BaseModel):
    directory_ref: str  # `spaceid:<id>;fatherid:<id>`：可直接存入 directory_path
    name: str
    parent_ref: str | None = None
    has_children: bool | None = None


class WecomDriveDirectoriesResponse(BaseModel):
    space_ref: str
    items: list[WecomDriveDirectoryOut]


class WecomScanConfigOut(BaseModel):
    id: uuid.UUID
    name: str | None
    directory_path: str
    scope_type: str
    related_project_id: uuid.UUID | None
    related_project_name: str | None = None
    enabled: bool
    # created_by 即"待确认任务业务归属人"：扫描产物的 IngestTask.created_by。
    # 配置操作人是当前 admin（见审计 actor），与此业务归属人不是同一概念。
    created_by: uuid.UUID
    task_owner_name: str | None = None
    task_owner_role_label: str | None = None
    scan_frequency: str | None
    last_scan_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WecomScanConfigsResponse(BaseModel):
    items: list[WecomScanConfigOut]


class WecomScanConfigCreateBody(BaseModel):
    """创建扫描配置请求。

    directory_path 仍为内部格式 `spaceid:<id>;fatherid:<id>`（server-only 不拆字段外泄）。
    `task_owner_user_id`：扫描产物（path_a_wecom IngestTask）的业务归属人，必须是合法业务
    用户（active、含业务公司角色、非纯 admin），写入 `WecomScanConfig.created_by`；配置操作人
    仍是当前 admin（审计 actor）。
    """

    name: str
    directory_path: str
    target_scope: str
    target_project_id: uuid.UUID | None = None
    task_owner_user_id: uuid.UUID
    enabled: bool = True


class WecomScanConfigUpdateBody(BaseModel):
    """编辑扫描配置请求。全部可选；仅传入字段被更新（含启停）。"""

    name: str | None = None
    directory_path: str | None = None
    target_scope: str | None = None
    target_project_id: uuid.UUID | None = None
    task_owner_user_id: uuid.UUID | None = None
    enabled: bool | None = None


class WecomProjectOptionOut(BaseModel):
    """项目候选项（仅安全字段：id + 名称），供创建/编辑配置时选择目标项目。"""

    id: uuid.UUID
    name: str


class WecomProjectOptionsResponse(BaseModel):
    items: list[WecomProjectOptionOut]


class WecomOwnerOptionOut(BaseModel):
    """业务归属人候选（仅安全字段）：active 业务用户。

    project_ids / is_governance 供前端按 target_scope 做候选提示；后端最终校验为准。
    绝不含 token / session / wecom_user_id 明文 / ip / device。
    """

    user_id: uuid.UUID
    name: str
    role_label: str | None = None
    project_ids: list[uuid.UUID] = []
    is_governance: bool = False


class WecomOwnerOptionsResponse(BaseModel):
    items: list[WecomOwnerOptionOut]


class WecomScanRecordOut(BaseModel):
    id: uuid.UUID
    config_id: uuid.UUID
    trace_id: str | None
    scan_started_at: datetime
    scan_completed_at: datetime | None
    discovered_count: int
    new_count: int
    duplicate_count: int
    failed_count: int
    scan_status: str
    error_type: str | None
    error_message: str | None
    created_at: datetime


class WecomScanRecordsResponse(BaseModel):
    items: list[WecomScanRecordOut]

