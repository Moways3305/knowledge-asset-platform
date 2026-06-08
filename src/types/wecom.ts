// 企微微盘扫描 API 的 DTO 类型（R6，契约 §17）。
// 响应只含安全运营元数据：绝不含微盘 file_id / 下载 URL / access_token / cookie /
// 存储引用 / WeKnora id / 业务原文。

export interface WecomScanConfigDTO {
  id: string;
  name: string | null;
  directory_path: string;
  scope_type: string;
  related_project_id: string | null;
  related_project_name: string | null;
  enabled: boolean;
  // created_by = 待确认任务业务归属人（非配置操作人 admin）。
  created_by: string;
  task_owner_name: string | null;
  task_owner_role_label: string | null;
  scan_frequency: string | null;
  last_scan_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WecomScanConfigsResponseDTO {
  items: WecomScanConfigDTO[];
}

// 创建扫描配置请求。directory_path 为内部格式 spaceid:<id>;fatherid:<id>。
// task_owner_user_id：扫描产物（path_a_wecom 任务）的业务归属人，由后端校验合法性。
export interface WecomScanConfigCreateBody {
  name: string;
  directory_path: string;
  target_scope: string;
  target_project_id?: string | null;
  task_owner_user_id: string;
  enabled: boolean;
}

// 编辑请求（全部可选，仅传入字段更新；含启停 / 改归属人）。
export interface WecomScanConfigUpdateBody {
  name?: string;
  directory_path?: string;
  target_scope?: string;
  target_project_id?: string | null;
  task_owner_user_id?: string;
  enabled?: boolean;
}

export interface WecomProjectOptionDTO {
  id: string;
  name: string;
}

export interface WecomProjectOptionsResponseDTO {
  items: WecomProjectOptionDTO[];
}

// 业务归属人候选（仅安全字段）。project_ids / is_governance 供前端按 scope 提示。
export interface WecomOwnerOptionDTO {
  user_id: string;
  name: string;
  role_label: string | null;
  project_ids: string[];
  is_governance: boolean;
}

export interface WecomOwnerOptionsResponseDTO {
  items: WecomOwnerOptionDTO[];
}

export interface WecomScanRecordDTO {
  id: string;
  config_id: string;
  trace_id: string | null;
  scan_started_at: string;
  scan_completed_at: string | null;
  discovered_count: number;
  new_count: number;
  duplicate_count: number;
  failed_count: number;
  scan_status: string;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
}

export interface WecomScanRecordsResponseDTO {
  items: WecomScanRecordDTO[];
}

export interface WecomAuthorizeDTO {
  authorize_url: string;
}

// 目录浏览。directory_ref 即可保存的 directory_path；不含文件 file_id / 下载 URL / token。
export interface WecomDriveSpaceDTO {
  space_ref: string;
  name: string;
}
export interface WecomDriveSpacesResponseDTO {
  items: WecomDriveSpaceDTO[];
}
export interface WecomDriveDirectoryDTO {
  directory_ref: string;
  name: string;
  parent_ref: string | null;
  has_children: boolean | null;
}
export interface WecomDriveDirectoriesResponseDTO {
  space_ref: string;
  items: WecomDriveDirectoryDTO[];
}

