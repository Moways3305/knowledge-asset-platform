import { describe, expect, it, vi } from "vitest";
import {
  ADMIN_OVERVIEW_INVALIDATED_EVENT,
  affectsAdminOverview,
  invalidateAdminOverview,
} from "./adminOverviewEvents";

describe("admin overview invalidation", () => {
  it("only treats successful admin workspace writes as overview-affecting paths", () => {
    expect(affectsAdminOverview("/api/v1/admin/alerts/rules/rule-safe")).toBe(true);
    expect(affectsAdminOverview("/admin/ops/indexing/retry")).toBe(true);
    expect(affectsAdminOverview("/api/v1/projects/project-safe")).toBe(false);
  });

  it("dispatches one scoped invalidation event", () => {
    const listener = vi.fn();
    window.addEventListener(ADMIN_OVERVIEW_INVALIDATED_EVENT, listener);
    invalidateAdminOverview("/api/v1/admin/wecom-scan/configs/config-safe");
    invalidateAdminOverview("/api/v1/projects/project-safe");
    window.removeEventListener(ADMIN_OVERVIEW_INVALIDATED_EVENT, listener);

    expect(listener).toHaveBeenCalledTimes(1);
  });
});
