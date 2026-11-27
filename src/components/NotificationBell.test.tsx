import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NotificationBell from "./NotificationBell";
import {
  fetchInbox,
  actOnInbox,
  fetchNotificationEvents,
  fetchNotificationPreferences,
  saveNotificationPreferences,
  type InboxResponse,
} from "../api/notificationInbox";
import type { BusinessNotificationDTO } from "../types/notification";
import { TASK_STATUS_INVALIDATED_EVENT } from "../workbench/taskStatusEvents";
vi.mock("../api/notificationInbox", () => ({
  fetchInbox: vi.fn(),
  actOnInbox: vi.fn(),
  fetchNotificationEvents: vi.fn(),
  fetchNotificationPreferences: vi.fn(),
  saveNotificationPreferences: vi.fn(),
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

const snapshot = "2026-11-17T01:00:00Z";
const group = {
  id: "review:one",
  latest: notification,
  event_count: 3,
  unread_count: 3,
  failed_count: 0,
  completed_count: 0,
  action_required: true,
};
const initial: InboxResponse = {
  items: [group],
  total: 1,
  unread_count: 1,
  unseen_count: 1,
  snapshot_at: snapshot,
  categories: ["review"],
  projects: [],
};
function renderBell(entry = "/", state?: unknown) {
  function Probe() {
    const location = useLocation();
    return <output data-testid="location">{JSON.stringify(location)}</output>;
  }
  return render(
    <MemoryRouter initialEntries={[{ pathname: entry, state }]}>
      <NotificationBell />
      <Probe />
    </MemoryRouter>,
  );
}
async function open() {
  fireEvent.click(await screen.findByRole("button", { name: /通知中心，1 条新提醒/ }));
  await waitFor(() =>
    expect(actOnInbox).toHaveBeenCalledWith(expect.objectContaining({ action: "seen" })),
  );
  await screen.findByRole("button", { name: "查看详情" });
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchInbox).mockResolvedValue(structuredClone(initial));
  vi.mocked(actOnInbox).mockResolvedValue({ affected_count: 3 });
  vi.mocked(fetchNotificationEvents).mockResolvedValue({ items: [notification], total: 1 });
  vi.mocked(fetchNotificationPreferences).mockResolvedValue({
    categories: {},
    auto_archive_days: 0,
  });
  vi.mocked(saveNotificationPreferences).mockImplementation(async (body) => body);
});
describe("Notification inbox lifecycle", () => {
  it.each(["needs_action", "completed"] as const)(
    "opens the exact maintenance digest for %s work",
    async (status) => {
      const notice = {
        ...notification,
        event_type: "maintenance.digest",
        task_status: status,
        target: { route_key: "maintenance_agent", resource_id: "daily-digest" },
      };
      vi.mocked(fetchNotificationEvents).mockResolvedValue({ items: [notice], total: 1 });
      vi.mocked(fetchInbox).mockResolvedValue({
        ...initial,
        items: [{ ...group, latest: { ...notice, title: "知识维护巡检摘要" } }],
      });
      renderBell();
      await open();
      if (status === "completed") {
        fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
        fireEvent.click(await screen.findByRole("button", { name: "前往处理" }));
      } else {
        fireEvent.click(screen.getByRole("button", { name: "知识维护巡检摘要" }));
      }
      await waitFor(() =>
        expect(JSON.parse(screen.getByTestId("location").textContent!).pathname).toBe(
          "/ai-workspace/agents/knowledge-maintenance",
        ),
      );
      const route = JSON.parse(screen.getByTestId("location").textContent!);
      const params = new URLSearchParams(route.search);
      expect(params.get("target_id")).toBe("daily-digest");
      expect(params.get("status")).toBe(status === "completed" ? "all" : null);
    },
  );
  it("opening clears new badge without marking unread work complete", async () => {
    renderBell();
    await open();
    expect(actOnInbox).toHaveBeenCalledWith({
      action: "seen",
      all_matching: true,
      filters: { view: "inbox" },
      snapshot_at: snapshot,
    });
    expect(
      screen.getByRole("button", { name: "通知中心，0 条新提醒，1 组未读" }),
    ).toBeInTheDocument();
    expect(screen.getByText("待处理")).toBeInTheDocument();
    expect(actOnInbox).not.toHaveBeenCalledWith(expect.objectContaining({ action: "read" }));
  });
  it("marks all pages read using a server snapshot, never a loaded id list", async () => {
    vi.mocked(fetchInbox).mockResolvedValue({ ...initial, total: 3500 });
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "全部已读" }));
    await waitFor(() =>
      expect(actOnInbox).toHaveBeenCalledWith({
        action: "read",
        all_matching: true,
        filters: { view: "inbox" },
        snapshot_at: snapshot,
      }),
    );
  });
  it("clears all historical pages including archive with explicit confirmation", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "清理历史" }));
    expect(actOnInbox).not.toHaveBeenCalledWith(expect.objectContaining({ action: "delete" }));
    fireEvent.click(screen.getByRole("button", { name: "确认清理全部历史消息" }));
    await waitFor(() =>
      expect(actOnInbox).toHaveBeenCalledWith({
        action: "delete",
        all_matching: true,
        snapshot_at: snapshot,
        filters: { view: "inbox", include_archived: true },
      }),
    );
  });
  it("keeps date cleanup limited to the chosen Beijing date", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "清理历史" }));
    fireEvent.change(screen.getByLabelText(/只清理此日期/), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("button", { name: "确认清理日期之前消息" }));
    await waitFor(() =>
      expect(actOnInbox).toHaveBeenCalledWith(
        expect.objectContaining({
          filters: { view: "inbox", include_archived: true, before: "2026-10-01T00:00:00+08:00" },
        }),
      ),
    );
  });
  it("supports cross-page selection and single group deletion without losing the scope", async () => {
    vi.mocked(fetchInbox).mockResolvedValue({ ...initial, total: 250 });
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "选择全部 250 组（跨页）" }));
    const bar = screen.getByText("已选 250 组").closest("div")!;
    fireEvent.click(within(bar).getByRole("button", { name: "归档" }));
    await waitFor(() =>
      expect(actOnInbox).toHaveBeenCalledWith(
        expect.objectContaining({ action: "archive", all_matching: true }),
      ),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "删除" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() =>
      expect(actOnInbox).toHaveBeenCalledWith(
        expect.objectContaining({ action: "delete", group_ids: [group.id] }),
      ),
    );
  });
  it("restores personal messages from trash", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("tab", { name: "回收站" }));
    fireEvent.click(await screen.findByRole("button", { name: "恢复" }));
    await waitFor(() =>
      expect(actOnInbox).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "restore",
          filters: { view: "trash" },
          group_ids: [group.id],
        }),
      ),
    );
  });
  it("retains selection and content if an operation fails", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByLabelText("选择当前已加载消息"));
    vi.mocked(actOnInbox).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getAllByRole("button", { name: "归档" })[0]);
    await screen.findByRole("alert");
    expect(screen.getByLabelText("选择当前已加载消息")).toBeChecked();
    expect(screen.getByRole("button", { name: "查看详情" })).toBeInTheDocument();
  });
  it("preserves expanded details and selection while new events wait behind a banner", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    const detail = await screen.findByRole("region", { name: "消息详情" });
    fireEvent.click(screen.getByLabelText("选择当前已加载消息"));
    const next = { ...group, id: "new-group", latest: { ...notification, title: "刚到的新消息" } };
    vi.mocked(fetchInbox).mockImplementation(async (_filters, _page, at) =>
      at
        ? initial
        : {
            ...initial,
            snapshot_at: "2026-11-17T02:00:00Z",
            items: [next, group],
            total: 2,
            unseen_count: 1,
          },
    );
    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    await screen.findByRole("button", { name: /有 1 组新提醒/ });
    expect(screen.getByRole("region", { name: "消息详情" })).toBe(detail);
    expect(screen.queryByText("刚到的新消息")).not.toBeInTheDocument();
    expect(screen.getByLabelText("选择当前已加载消息")).toBeChecked();
  });
  it("removes revoked targets and details when background authorization changes", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    await screen.findByRole("region", { name: "消息详情" });
    vi.mocked(fetchInbox).mockResolvedValue({
      ...initial,
      items: [],
      total: 0,
      unseen_count: 0,
      unread_count: 0,
    });
    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "消息详情" })).not.toBeInTheDocument(),
    );
  });
  it.each(["/my/knowledge", "/knowledge/previous-asset"])(
    "retains safe return navigation from %s",
    async (entry) => {
      const item = {
        ...notification,
        target: { route_key: "knowledge_detail", resource_id: "asset-safe" },
      };
      vi.mocked(fetchNotificationEvents).mockResolvedValue({ items: [item], total: 1 });
      renderBell(entry, { backTo: "/my/knowledge", backLabel: "返回我的知识", source: "personal" });
      await open();
      fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
      fireEvent.click(await screen.findByRole("button", { name: "前往处理" }));
      await waitFor(() =>
        expect(JSON.parse(screen.getByTestId("location").textContent!).pathname).toBe(
          "/knowledge/asset-safe",
        ),
      );
      expect(JSON.parse(screen.getByTestId("location").textContent!).state.backTo).toBe(
        "/my/knowledge",
      );
    },
  );
  it("rejects unknown target routes without navigating", async () => {
    vi.mocked(fetchNotificationEvents).mockResolvedValue({
      items: [{ ...notification, target: { route_key: "https://invalid.test", resource_id: "x" } }],
      total: 1,
    });
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    fireEvent.click(await screen.findByRole("button", { name: "前往处理" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("目标页暂不可用");
    expect(JSON.parse(screen.getByTestId("location").textContent!).pathname).toBe("/");
  });
  it("keeps settings drafts during background updates and saves channels plus retention", async () => {
    renderBell();
    await open();
    fireEvent.click(screen.getByRole("button", { name: "通知设置" }));
    fireEvent.change(await screen.findByLabelText("审核企业微信"), { target: { value: "hourly" } });
    fireEvent.change(screen.getByLabelText("自动归档已读历史"), { target: { value: "30" } });
    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    expect(screen.getByLabelText("审核企业微信")).toHaveValue("hourly");
    fireEvent.click(screen.getByRole("button", { name: "保存通知设置" }));
    await waitFor(() =>
      expect(saveNotificationPreferences).toHaveBeenCalledWith({
        categories: { review: { in_app: true, wecom: "hourly" } },
        auto_archive_days: 30,
      }),
    );
  });
});
