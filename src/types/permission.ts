// Admin Permissions API 的 DTO 类型。
// 权限规则只含安全治理元数据；外部 Agent 接入注册（Agent Registry）来自 provider 中立后端
// 兼容接口。前端不构造、不展示任何 token / provider 内部标识（后端本就不返回）。

export interface PermissionRuleDTO {
  rule_id: string;
  rule_key: string;
  rule_group: string;
  rule_type: "numeric" | "toggle" | "fixed_path" | string;
  display_name: string;
  value_bool: boolean | null;
  value_number: number | null;
  value_text: string | null;
  default_bool: boolean | null;
  default_number: number | null;
  default_text: string | null;
  unit: string | null;
  description: string | null;
  editable: boolean;
  enabled: boolean;
  updated_by_user_id: string | null;
  updated_by_name: string | null;
  updated_at: string;
}

export interface PermissionRulesResponseDTO {
  items: PermissionRuleDTO[];
  total: number;
}

export interface PermissionRuleUpdateDTO {
  value_bool?: boolean;
  value_number?: number;
  value_text?: string;
  enabled?: boolean;
}

// ---- 外部 Agent 接入注册（Agent Registry，provider 中立兼容接口）----
export interface AgentRegistryRuleDTO {
  id: string;
  provider: string;
  agent_name: string;
  capability: string;
  allowed_scope: string | null;
  allowed_project_id: string | null;
  max_confidentiality_level: string;
  max_ai_access_level: string;
  enabled: boolean;
  risk_level: string | null;
  risk_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRegistryListResponseDTO {
  items: AgentRegistryRuleDTO[];
}

// PATCH 响应：{ rule, token? }（token 仅在重置时返回，本页不重置 token）。
export interface AgentRegistryUpdateResponseDTO {
  rule: AgentRegistryRuleDTO;
  token: string | null;
}
