import { beforeEach, expect, it, vi } from "vitest";
import { apiGet } from "./http";
import { fetchNotifications } from "./notifications";

vi.mock("./http", () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPostNoBody: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

it.each([true, false])("sends the explicit action filter %s to the list API", async (value) => {
  await fetchNotifications({ actionRequired: value, page: 2 });
  expect(apiGet).toHaveBeenCalledWith(
    `/api/v1/notifications?page=2&action_required=${value}`,
    undefined,
  );
});

it("preserves the unfiltered API default for other callers", async () => {
  await fetchNotifications();
  expect(apiGet).toHaveBeenCalledWith("/api/v1/notifications", undefined);
});
