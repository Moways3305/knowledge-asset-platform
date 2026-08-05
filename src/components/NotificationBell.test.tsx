import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NotificationBell from "./NotificationBell";
import {
  fetchNotificationUnreadCount,
  fetchNotifications,
  markNotificationRead,
  markNotificationsRead,
} from "../api/notifications";
import type { BusinessNotificationDTO } from "../types/notification";

vi.mock("../api/notifications", () => ({
  fetchNotificationUnreadCount: vi.fn(),
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
  target: { route_key: "reviews", resource_id: "00000000-0000-0000-0000-000000000001" },
};

function renderBell() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <NotificationBell />
    </MemoryRouter>,
  );
}

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchNotificationUnreadCount).mockResolvedValue({ unread_count: 1 });
    vi.mocked(fetchNotifications).mockResolvedValue({
      items: [notification],
      total: 1,
      page: 1,
      page_size: 20,
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
    fireEvent.click(screen.getByRole("button", { name: "通知" }));
    expect(await screen.findByText("项目事项待确认")).toBeInTheDocument();
    expect(screen.getByText("有一项项目事项等待你确认。")).toBeInTheDocument();
  });

  it("marks a notification read when opened", async () => {
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: "通知" }));
    fireEvent.click(await screen.findByRole("button", { name: /项目事项待确认/ }));
    await waitFor(() => expect(markNotificationRead).toHaveBeenCalledWith("notif-1"));
  });

  it("marks all unread notifications as read", async () => {
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: "通知" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部已读" }));
    await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledWith(["notif-1"]));
  });

  it("shows an empty state when there are no unread notifications", async () => {
    vi.mocked(fetchNotificationUnreadCount).mockResolvedValue({ unread_count: 0 });
    vi.mocked(fetchNotifications).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    renderBell();
    fireEvent.click(screen.getByRole("button", { name: "通知" }));
    expect(await screen.findByText("暂无未读通知")).toBeInTheDocument();
  });
});
