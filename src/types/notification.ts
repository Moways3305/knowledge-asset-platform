// 个人业务通知（铃铛）DTO。通知只是入口提示，绝不作为授权依据；
// 后端读取时仍会按当前身份重新校验目标可见性。

export interface NotificationTargetDTO {
  route_key: string;
  resource_id: string;
}

export interface BusinessNotificationDTO {
  id: string;
  event_type: string;
  category: string;
  title: string;
  summary: string;
  created_at: string;
  is_read: boolean;
  read_at: string | null;
  target: NotificationTargetDTO;
}

export interface BusinessNotificationListResponseDTO {
  items: BusinessNotificationDTO[];
  total: number;
  page: number;
  page_size: number;
}

export interface UnreadCountResponseDTO {
  unread_count: number;
}

export interface MarkReadBatchResponseDTO {
  requested_count: number;
  marked_count: number;
  already_read_count: number;
}
