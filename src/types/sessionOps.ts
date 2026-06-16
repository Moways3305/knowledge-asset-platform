// 平台会话运维 DTO。仅安全字段：安全 session_id（非 token hash）、login_method、
// 时间、撤销状态。绝不含 token / token_hash / cookie / OAuth state / ip / device。

export interface UserSessionItemDTO {
  session_id: string;
  login_method: string;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  active: boolean;
  is_current_actor_session: boolean;
}

export interface UserSessionsResponseDTO {
  user_id: string;
  active_count: number;
  sessions: UserSessionItemDTO[];
}

export interface SessionRevokeResponseDTO {
  ok: boolean;
  user_id: string;
  revoked_count: number;
  revoked_at: string | null;
  preserved_current_session: boolean;
}
