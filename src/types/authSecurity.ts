// 登录风控运维 DTO。仅安全字段：不可逆 hash 前缀、计数、安全用户元数据、
// 时间、原因码。绝不含 raw email / raw IP / 完整 hash / password / token / cookie。

export interface AuthSecurityCountsDTO {
  failed: number;
  locked: number;
  rate_limited: number;
  success: number;
  unlocked: number;
  unique_identifier_count: number;
  unique_ip_count: number;
}

export interface AuthSecurityEventDTO {
  attempt_id: string;
  identifier_hash_prefix: string | null;
  ip_hash_prefix: string | null;
  user_id: string | null;
  user_name: string | null;
  user_status: string | null;
  login_method: string;
  result: string;
  reason_code: string | null;
  created_at: string;
}

export interface AuthSecurityOverviewDTO {
  window_minutes: number;
  counts: AuthSecurityCountsDTO;
  recent_events: AuthSecurityEventDTO[];
}

export interface AuthUnlockResponseDTO {
  ok: boolean;
  unlocked: boolean;
  user_id: string | null;
  identifier_hash_prefix: string | null;
  reset_at: string | null;
}

