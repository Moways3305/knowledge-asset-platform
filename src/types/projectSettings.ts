// 项目设置 / 项目成员 API 的 DTO 类型。
// 只含安全治理元数据；企微群只回 bound + 脱敏 label，绝不回全文。前端不构造/展示任何
// token / wecom_user_id / provider 内部标识（后端本就不返回）。

export interface ProjectSettingsDTO {
  project_id: string;
  name: string;
  status: string;
  client_name: string | null;
  coach_name: string | null;
  lifecycle_route_key: string | null;
  lifecycle_phase_key: string | null;
  force_review_on_ingest: boolean;
  wecom_group_bound: boolean;
  wecom_group_label: string | null;
  updated_at: string;
  can_write: boolean;
}

export interface ProjectSettingsUpdateDTO {
  lifecycle_route_key?: string;
  lifecycle_phase_key?: string;
  force_review_on_ingest?: boolean;
  wecom_group_id?: string;
}

export interface ProjectDeletionReadinessDTO {
  can_delete: boolean;
  asset_count: number;
  member_count: number;
  blockers: string[];
}

export interface ProjectMemberDTO {
  member_id: string;
  user_id: string;
  name: string;
  email: string;
  company_roles: string[];
  project_role: string;
  status: string;
  source: string;
  joined_at: string;
  wecom_bound: boolean;
}

export interface ProjectMembersResponseDTO {
  items: ProjectMemberDTO[];
  total: number;
  can_manage: boolean;
}

export interface ProjectMemberPatchDTO {
  project_role?: string;
  status?: string;
}
