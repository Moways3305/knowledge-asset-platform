import { describe, expect, it, vi } from "vitest";
import {
  TASK_STATUS_INVALIDATED_EVENT,
  affectsTaskStatus,
  invalidateTaskStatus,
} from "./taskStatusEvents";

describe("task status invalidation", () => {
  it("recognizes task-changing business writes but ignores unrelated mutations", () => {
    expect(affectsTaskStatus("/api/v1/reviews/review-id/approve")).toBe(true);
    expect(affectsTaskStatus("/api/v1/ingest/task-id/confirm")).toBe(true);
    expect(affectsTaskStatus("/api/v1/knowledge/asset-id/original-access/request")).toBe(true);
    expect(affectsTaskStatus("/api/v1/knowledge/asset-id/retry-index")).toBe(true);
    expect(
      affectsTaskStatus("/api/v1/projects/project-id/knowledge/asset-id/upgrade-company"),
    ).toBe(true);
    expect(affectsTaskStatus("/api/v1/admin/people/user-id/status")).toBe(false);
  });

  it("emits one shared event only after a relevant operation succeeds", () => {
    const listener = vi.fn();
    window.addEventListener(TASK_STATUS_INVALIDATED_EVENT, listener);

    invalidateTaskStatus("/api/v1/reviews/review-id/approve");
    invalidateTaskStatus("/api/v1/admin/people/user-id/status");

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(TASK_STATUS_INVALIDATED_EVENT, listener);
  });
});
