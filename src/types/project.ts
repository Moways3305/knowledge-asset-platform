// 项目知识库列表 / 创建 API 的 DTO 类型。
// 仅安全治理元数据：绝不含 WeKnora id / 企微群全文 / token / URL。

export interface ProjectListItemDTO {
  id: string;
  name: string;
  client_name: string | null;
  status: string;
  lifecycle_route_key: string | null;
  lifecycle_phase_key: string | null;
  created_at: string;
  project_role: string;
  can_manage: boolean;
}

export interface ProjectListResponseDTO {
  items: ProjectListItemDTO[];
}

export interface ProjectCreateRequestDTO {
  name: string;
  client_name?: string | null;
  project_manager_user_id: string;
  project_code: string;
  project_code_active: boolean;
  naming_default_confidentiality: string;
  coach_user_id?: string | null;
  lifecycle_route_key?: string | null;
  lifecycle_phase_key?: string | null;
}

export interface ProjectCreateResponseDTO {
  id: string;
  name: string;
  client_name: string | null;
  status: string;
  lifecycle_route_key: string | null;
  lifecycle_phase_key: string | null;
  project_manager_user_id: string;
  coach_user_id: string | null;
  created_at: string;
}

export interface ProjectOverviewDTO {
  project: {
    project_id: string;
    name: string;
    client_name: string | null;
    status: string;
    project_role: string;
    lifecycle_route_key: string | null;
    lifecycle_phase_key: string | null;
    can_manage: boolean;
  };
  capabilities: {
    can_view_knowledge: boolean;
    can_upload_material: boolean;
    can_manage_members: boolean;
    can_manage_kb: boolean;
    can_confirm_assets: boolean;
  };
  counts: {
    material_count: number;
    asset_count: number;
    pending_confirmation_count: number;
    pending_review_count: number;
    original_access_request_count: number;
  };
  knowledge_base: { configured: boolean; status: string | null };
  members: Array<{ user_id: string; name: string; project_role: string; status: string }>;
  recent_activity: Array<{
    asset_id: string;
    title: string;
    zone: string;
    asset_type: string;
    confidentiality_level: string;
    updated_at: string | null;
  }>;
}
