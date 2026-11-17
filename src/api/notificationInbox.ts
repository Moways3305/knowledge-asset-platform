import { apiGet, apiPost, apiPut } from "./http";
import type { BusinessNotificationDTO } from "../types/notification";

export type InboxView = "inbox" | "unread" | "archived" | "trash";
export interface InboxFilter {
  view: InboxView;
  category?: string;
  project_id?: string;
  before?: string;
  after?: string;
  read_only?: boolean;
  include_archived?: boolean;
}
export interface NotificationGroup {
  id: string;
  latest: BusinessNotificationDTO;
  event_count: number;
  unread_count: number;
  failed_count: number;
  completed_count: number;
  action_required: boolean;
}
export interface InboxResponse {
  items: NotificationGroup[];
  total: number;
  unread_count: number;
  unseen_count: number;
  snapshot_at: string;
  categories: string[];
  projects: { id: string; name: string }[];
}
export type InboxActionName = "read" | "unread" | "archive" | "delete" | "restore" | "seen";
export interface InboxAction {
  action: InboxActionName;
  snapshot_at: string;
  filters: InboxFilter;
  group_ids?: string[];
  all_matching?: boolean;
}
export interface NotificationPreferences {
  categories: Record<string, { in_app: boolean; wecom: "off" | "immediate" | "hourly" }>;
  auto_archive_days: 0 | 30 | 90 | 180;
}
function query(values: object) {
  return new URLSearchParams(
    Object.entries(values)
      .filter(([, value]) => value != null && value !== "")
      .map(([key, value]) => [key, String(value)]),
  ).toString();
}
export function fetchInbox(
  filters: InboxFilter,
  page = 1,
  snapshot?: string,
  signal?: AbortSignal,
): Promise<InboxResponse> {
  return apiGet(
    `/api/v1/notifications/inbox?${query({ ...filters, page, snapshot_at: snapshot })}`,
    signal,
  );
}
export function actOnInbox(body: InboxAction): Promise<{ affected_count: number }> {
  return apiPost("/api/v1/notifications/inbox/actions", body);
}
export function fetchNotificationEvents(
  group: string,
  filters: InboxFilter,
  snapshot: string,
  page = 1,
  signal?: AbortSignal,
): Promise<{ items: BusinessNotificationDTO[]; total: number }> {
  return apiGet(
    `/api/v1/notifications/inbox/events?${query({ ...filters, group_id: group, snapshot_at: snapshot, page })}`,
    signal,
  );
}
export function fetchNotificationPreferences(): Promise<NotificationPreferences> {
  return apiGet("/api/v1/notifications/preferences");
}
export function saveNotificationPreferences(
  body: NotificationPreferences,
): Promise<NotificationPreferences> {
  return apiPut("/api/v1/notifications/preferences", body);
}
