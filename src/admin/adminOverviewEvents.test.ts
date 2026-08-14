import { describe, expect, it, vi } from "vitest";
import {
  ADMIN_OVERVIEW_INVALIDATED_EVENT,
  affectsAdminOverview,
  invalidateAdminOverview,
} from "./adminOverviewEvents";

describe("admin overview invalidation", () => {
  it("recognizes admin and project membership writes without matching unrelated project paths", () => {
    expect(affectsAdminOverview("/api/v1/admin/alerts/rules/rule-safe")).toBe(true);
    expect(affectsAdminOverview("/admin/ops/indexing/retry")).toBe(true);
    expect(affectsAdminOverview("/api/v1/projects/project-safe/members")).toBe(true);
    expect(affectsAdminOverview("/api/v1/projects/project-safe/members/member-safe")).toBe(true);
    expect(affectsAdminOverview("/api/v1/projects/project-safe/members?status=active")).toBe(true);
    expect(affectsAdminOverview("/api/v1/projects/project-safe")).toBe(false);
    expect(affectsAdminOverview("/api/v1/projects/project-safe/member-settings")).toBe(false);
  });

  it("dispatches scoped invalidation events for both mutation families", () => {
    const listener = vi.fn();
    window.addEventListener(ADMIN_OVERVIEW_INVALIDATED_EVENT, listener);
    invalidateAdminOverview("/api/v1/admin/wecom-scan/configs/config-safe");
    invalidateAdminOverview("/api/v1/projects/project-safe/members/member-safe");
    invalidateAdminOverview("/api/v1/projects/project-safe");
    window.removeEventListener(ADMIN_OVERVIEW_INVALIDATED_EVENT, listener);

    expect(listener).toHaveBeenCalledTimes(2);
  });
});
