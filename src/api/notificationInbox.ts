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
export async function fetchInbox(
  filters: InboxFilter,
  page = 1,
  snapshot?: string,
  signal?: AbortSignal,
): Promise<InboxResponse> {
  const data = await apiGet<InboxResponse>(
    `/api/v1/notifications/inbox?${query({ ...filters, page, snapshot_at: snapshot })}`,
    signal,
  );
  if (
    !data ||
    !Array.isArray(data.items) ||
    !Array.isArray(data.projects) ||
    !Array.isArray(data.categories) ||
    !data.categories.every((value) => typeof value === "string") ||
    !count(data.total) ||
    !count(data.unread_count) ||
    !count(data.unseen_count) ||
    typeof data.snapshot_at !== "string" ||
    !Number.isFinite(Date.parse(data.snapshot_at)) ||
    !data.projects.every(
      (project) => project && typeof project.id === "string" && typeof project.name === "string",
    ) ||
    !data.items.every(
      (group) =>
        group &&
        typeof group.id === "string" &&
        notice(group.latest) &&
        count(group.event_count) &&
        count(group.unread_count) &&
        count(group.failed_count) &&
        count(group.completed_count) &&
        typeof group.action_required === "boolean",
    )
  ) {
    throw new Error("invalid_notification_inbox_response");
  }
  return data;
}
export async function actOnInbox(body: InboxAction): Promise<{ affected_count: number }> {
  const result = await apiPost<{ affected_count: number }>(
    "/api/v1/notifications/inbox/actions",
    body,
  );
  if (!result || !count(result.affected_count))
    throw new Error("invalid_notification_action_response");
  return result;
}
export async function fetchNotificationEvents(
  group: string,
  filters: InboxFilter,
  snapshot: string,
  page = 1,
  signal?: AbortSignal,
): Promise<{ items: BusinessNotificationDTO[]; total: number }> {
  const result = await apiGet<{ items: BusinessNotificationDTO[]; total: number }>(
    `/api/v1/notifications/inbox/events?${query({ ...filters, group_id: group, snapshot_at: snapshot, page })}`,
    signal,
  );
  if (
    !result ||
    !count(result.total) ||
    !Array.isArray(result.items) ||
    !result.items.every(notice)
  ) {
    throw new Error("invalid_notification_events_response");
  }
  return result;
}
export async function fetchNotificationPreferences(): Promise<NotificationPreferences> {
  return preferences(await apiGet<NotificationPreferences>("/api/v1/notifications/preferences"));
}
export async function saveNotificationPreferences(
  body: NotificationPreferences,
): Promise<NotificationPreferences> {
  return preferences(
    await apiPut<NotificationPreferences>("/api/v1/notifications/preferences", body),
  );
}

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function notice(value: BusinessNotificationDTO): boolean {
  if (!value || typeof value !== "object" || !value.target) return false;
  return (
    [
      value.id,
      value.event_type,
      value.category,
      value.title,
      value.summary,
      value.created_at,
      value.task_status,
      value.task_group,
      value.next_action_label,
      value.target.route_key,
      value.target.resource_id,
    ].every((item) => typeof item === "string") &&
    [value.project_name, value.failure_reason, value.recovery_suggestion].every(
      (item) => item == null || typeof item === "string",
    ) &&
    typeof value.is_read === "boolean" &&
    typeof value.action_required === "boolean"
  );
}
function preferences(value: NotificationPreferences): NotificationPreferences {
  if (
    !value ||
    !value.categories ||
    typeof value.categories !== "object" ||
    Array.isArray(value.categories) ||
    ![0, 30, 90, 180].includes(value.auto_archive_days) ||
    !Object.values(value.categories).every(
      (category) =>
        category &&
        typeof category.in_app === "boolean" &&
        ["off", "hourly", "immediate"].includes(category.wecom),
    )
  ) {
    throw new Error("invalid_notification_preferences_response");
  }
  return value;
}
