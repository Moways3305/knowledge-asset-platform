// 个人业务通知 API（铃铛）。与管理员的运维告警通知（admin/alerts/notifications）分离。
import { apiGet, apiPost, apiPostNoBody } from "./http";
import type {
  BusinessNotificationDTO,
  BusinessNotificationListResponseDTO,
  MarkReadBatchResponseDTO,
  UnreadCountResponseDTO,
} from "../types/notification";

export interface NotificationListParams {
  page?: number;
  pageSize?: number;
  category?: string;
  unreadOnly?: boolean;
}

export function fetchNotifications(
  params: NotificationListParams = {},
): Promise<BusinessNotificationListResponseDTO> {
  const query = new URLSearchParams();
  if (params.page != null) query.set("page", String(params.page));
  if (params.pageSize != null) query.set("page_size", String(params.pageSize));
  if (params.category) query.set("category", params.category);
  if (params.unreadOnly) query.set("unread_only", "true");
  const suffix = query.toString();
  return apiGet(`/api/v1/notifications${suffix ? `?${suffix}` : ""}`);
}

export function fetchNotificationUnreadCount(): Promise<UnreadCountResponseDTO> {
  return apiGet("/api/v1/notifications/unread-count");
}

export function markNotificationRead(notificationId: string): Promise<BusinessNotificationDTO> {
  return apiPostNoBody(`/api/v1/notifications/${notificationId}/read`);
}

export function markNotificationsRead(
  notificationIds: string[],
): Promise<MarkReadBatchResponseDTO> {
  return apiPost("/api/v1/notifications/read-batch", { notification_ids: notificationIds });
}
