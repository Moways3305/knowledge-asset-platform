import { beforeEach, expect, it, vi } from "vitest";
import { apiGet, apiPost } from "./http";
import {
  actOnInbox,
  fetchInbox,
  fetchNotificationEvents,
  fetchNotificationPreferences,
} from "./notificationInbox";

vi.mock("./http", () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
const empty = {
  items: [],
  projects: [],
  categories: [],
  total: 0,
  unread_count: 0,
  unseen_count: 0,
  snapshot_at: "2026-11-17T00:00:00Z",
};
beforeEach(() => vi.resetAllMocks());

it.each([
  null,
  {},
  { ...empty, projects: undefined },
  { ...empty, items: [{}] },
  { ...empty, unseen_count: "99" },
  { ...empty, snapshot_at: "invalid" },
  { ...empty, projects: [{ id: "x", name: {} }] },
])("rejects malformed inbox data before it can crash the surrounding page: %j", async (value) => {
  vi.mocked(apiGet).mockResolvedValue(value);
  await expect(fetchInbox({ view: "inbox" })).rejects.toThrow(
    "invalid_notification_inbox_response",
  );
});
it("accepts an empty inbox and preserves its authoritative counters", async () => {
  vi.mocked(apiGet).mockResolvedValue(empty);
  expect(await fetchInbox({ view: "inbox" })).toEqual(empty);
});
it("rejects malformed event details and preferences locally", async () => {
  vi.mocked(apiGet).mockResolvedValue({ items: [{}], total: 1 });
  await expect(
    fetchNotificationEvents("one", { view: "inbox" }, empty.snapshot_at),
  ).rejects.toThrow("invalid_notification_events_response");
  vi.mocked(apiGet).mockResolvedValue({ categories: { review: {} }, auto_archive_days: 0 });
  await expect(fetchNotificationPreferences()).rejects.toThrow(
    "invalid_notification_preferences_response",
  );
});
it("does not report successful cleanup from an incomplete response", async () => {
  vi.mocked(apiPost).mockResolvedValue({});
  await expect(
    actOnInbox({
      action: "delete",
      all_matching: true,
      filters: { view: "inbox" },
      snapshot_at: empty.snapshot_at,
    }),
  ).rejects.toThrow("invalid_notification_action_response");
});
