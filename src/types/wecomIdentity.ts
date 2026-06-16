// 企微身份对账 DTO。仅安全字段：平台 user_id / 显示名 / 状态 / 归一 wecom_status /
// 计数。绝不含 raw wecom_user_id / access_token / app_secret / OAuth code·state / 通讯录档案 /
// token / cookie / 上游 errmsg。

export interface WecomReconcileItemDTO {
  user_id: string;
  user_name: string;
  previous_status: string;
  new_status: string;
  wecom_status: string;
  sessions_revoked: number;
  error_code: string | null;
}

export interface WecomReconcileResponseDTO {
  ok: boolean;
  checked: number;
  deactivated: number;
  already_inactive: number;
  failed: number;
  dry_run: boolean;
  items: WecomReconcileItemDTO[];
}
