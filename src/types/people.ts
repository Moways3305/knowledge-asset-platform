// 人员 / 公司角色 / 项目成员关系 API 的 DTO 类型。
// 仅安全身份/治理元数据：无 token / session / OAuth code·state / 企微内部标识 / 业务原文。

export interface CompanyRoleDTO {
  role_id: string;
  company_role: string;
  status: string;
}

export interface PersonProjectMembershipDTO {
  membership_id: string;
  project_id: string;
  project_name: string;
  project_role: string;
  status: string;
  joined_at: string;
}

export interface PersonDTO {
  user_id: string;
  name: string;
  email: string;
  phone: string | null;
  wecom_bound: boolean;
  status: string;
  created_at: string;
  updated_at: string;
  company_roles: CompanyRoleDTO[];
  project_memberships: PersonProjectMembershipDTO[];
  recent_session_at: string | null;
  // 活动平台会话数（安全计数；详情接口返回，列表为 0）。
  active_session_count?: number;
  // 仅安全布尔 + 时间（绝不含 password_hash / salt / digest）。
  password_set: boolean;
  password_set_at: string | null;
}

export interface PeopleListResponseDTO {
  items: PersonDTO[];
  total: number;
}
