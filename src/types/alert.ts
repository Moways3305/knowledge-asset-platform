// Admin 告警设置 API 的 DTO 类型。
// 通知记录只含安全元数据；前端不构造、不展示任何内部标识（后端本就不返回）。

export interface AlertRuleDTO {
  id: string;
  rule_name: string;
  severity: string;
  threshold: number | null;
  threshold_unit: string | null;
  enabled: boolean;
  notification_channels: string[];
  dedup_strategy: string | null;
  updated_at: string;
}

export interface AlertRulesResponseDTO {
  items: AlertRuleDTO[];
}

export interface AlertRuleUpdateDTO {
  enabled?: boolean;
  threshold?: number;
  notification_channels?: string[];
}

export interface NotificationDTO {
  id: string;
  alert_rule_id: string | null;
  audit_event_id: string | null;
  recipient_user_id: string;
  recipient_name: string | null;
  channel: string;
  title: string;
  content: string;
  send_status: string;
  sent_at: string | null;
  created_at: string;
}

export interface NotificationsResponseDTO {
  items: NotificationDTO[];
}
