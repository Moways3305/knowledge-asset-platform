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
  can_manage: boolean;
}

export interface ProjectListResponseDTO {
  items: ProjectListItemDTO[];
}

export interface ProjectCreateRequestDTO {
  name: string;
  client_name?: string | null;
  project_manager_user_id: string;
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
