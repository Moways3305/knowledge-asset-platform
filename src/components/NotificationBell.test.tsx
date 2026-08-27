import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NotificationBell from "./NotificationBell";
import {
  fetchNotifications,
  markNotificationRead,
  markNotificationsRead,
} from "../api/notifications";
import type { BusinessNotificationDTO } from "../types/notification";

vi.mock("../api/notifications", () => ({
  fetchNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markNotificationsRead: vi.fn(),
}));

const notification: BusinessNotificationDTO = {
  id: "notif-1",
  event_type: "review.project_pending",
  category: "review",
  title: "项目事项待确认",
  summary: "有一项项目事项等待你确认。",
  created_at: "2026-08-05T08:00:00+00:00",
  is_read: false,
  read_at: null,
  project_name: "示例项目",
  object_name: "项目事项待确认",
  task_status: "needs_action",
  task_group: "my_tasks",
  action_required: true,
  next_action_label: "前往处理",
  delivery_status: "pending",
  target: { route_key: "reviews", resource_id: "00000000-0000-0000-0000-000000000001" },
};

function renderBell() {
  function LocationProbe() {
    const location = useLocation();
    return <span data-testid="location-probe">{`${location.pathname}${location.search}`}</span>;
  }
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <NotificationBell />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchNotifications).mockReset();
    vi.mocked(markNotificationRead).mockReset();
    vi.mocked(markNotificationsRead).mockReset();
    vi.mocked(fetchNotifications).mockResolvedValue({
      items: [notification],
      total: 1,
      page: 1,
      page_size: 20,
      unread_count: 1,
      pending_count: 1,
      categories: ["review"],
    });
    vi.mocked(markNotificationRead).mockResolvedValue({
      ...notification,
      is_read: true,
      read_at: "2026-08-05T08:10:00+00:00",
    });
    vi.mocked(markNotificationsRead).mockResolvedValue({
      requested_count: 1,
      marked_count: 1,
      already_read_count: 0,
    });
  });

  it("shows the unread badge and opens the notification panel", async () => {
    renderBell();
    await waitFor(() => expect(screen.getByText("1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    expect(await screen.findByText("项目事项待确认")).toBeInTheDocument();
    expect(screen.getByText("有一项项目事项等待你确认。")).toBeInTheDocument();
  });

  it("marks a notification read when opened", async () => {
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    fireEvent.click(await screen.findByRole("button", { name: "前往处理" }));
    await waitFor(() => expect(markNotificationRead).toHaveBeenCalledWith("notif-1"));
  });

  it("marks all unread notifications as read", async () => {
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    fireEvent.click(await screen.findByRole("button", { name: "全部已读" }));
    await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledWith(["notif-1"]));
  });

  it("shows an empty state when there are no unread notifications", async () => {
    vi.mocked(fetchNotifications).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      unread_count: 0,
      pending_count: 0,
      categories: [],
    });
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    expect(await screen.findByText("暂时没有待处理事项")).toBeInTheDocument();
  });

  it("separates pending work from status updates", async () => {
    const update = {
      ...notification,
      id: "notif-2",
      title: "入库已完成",
      action_required: false,
      task_status: "completed" as const,
      task_group: "recent_completed" as const,
    };
    vi.mocked(fetchNotifications).mockResolvedValueOnce({
      items: [notification, update],
      total: 2,
      page: 1,
      page_size: 20,
      unread_count: 2,
      pending_count: 1,
      categories: ["review"],
    });
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    expect(await screen.findByText(notification.title)).toBeInTheDocument();
    expect(screen.queryByText(update.title)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /动态/ }));
    expect(await screen.findByText(update.title)).toBeInTheDocument();
    expect(screen.queryByText(notification.title)).not.toBeInTheDocument();
  });

  it("renders duplicate skipped as a distinct terminal notification status", async () => {
    const duplicate = {
      ...notification,
      id: "notif-duplicate",
      category: "ingest",
      title: "重复资料已跳过",
      action_required: false,
      task_status: "duplicate_skipped" as const,
      task_group: "recent_completed" as const,
      next_action_label: "查看记录",
      target: { route_key: "upload", resource_id: "ingest-safe-1" },
    };
    vi.mocked(fetchNotifications).mockResolvedValueOnce({
      items: [duplicate],
      total: 1,
      page: 1,
      page_size: 20,
      unread_count: 1,
      pending_count: 0,
      categories: ["ingest"],
    });
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    fireEvent.click(await screen.findByRole("tab", { name: /动态/ }));
    expect(await screen.findByText("重复跳过")).toBeInTheDocument();
    expect(screen.queryByText("状态更新")).not.toBeInTheDocument();
  });

  it("keeps the drawer and unread state when marking read fails", async () => {
    vi.mocked(fetchNotifications).mockResolvedValueOnce({
      items: [notification],
      total: 1,
      page: 1,
      page_size: 20,
      unread_count: 1,
      pending_count: 1,
      categories: ["review"],
    });
    vi.mocked(markNotificationRead).mockRejectedValueOnce(new Error("temporary failure"));
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    fireEvent.click(await screen.findByRole("button", { name: "前往处理" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("未能标记为已读");
    expect(screen.getByRole("dialog", { name: "通知中心" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /通知中心，1 项待处理/ })).toBeInTheDocument();
  });

  it("opens an index update at the governed knowledge detail route", async () => {
    const indexUpdate = {
      ...notification,
      id: "notif-index",
      event_type: "index.status_changed",
      category: "indexing",
      title: "索引状态已更新",
      action_required: false,
      task_status: "completed" as const,
      task_group: "recent_completed" as const,
      next_action_label: "查看记录",
      target: { route_key: "knowledge_detail", resource_id: "asset-safe-1" },
    };
    vi.mocked(fetchNotifications).mockResolvedValue({
      items: [indexUpdate],
      total: 1,
      page: 1,
      page_size: 20,
      unread_count: 1,
      pending_count: 0,
      categories: ["indexing"],
    });
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: /通知中心/ }));
    fireEvent.click(await screen.findByRole("tab", { name: /动态/ }));
    fireEvent.click(await screen.findByRole("button", { name: "查看记录" }));
    await waitFor(() =>
      expect(screen.getByTestId("location-probe")).toHaveTextContent(
        "/knowledge/asset-safe-1?target_id=asset-safe-1",
      ),
    );
  });
});
