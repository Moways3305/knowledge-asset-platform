import { describe, expect, it } from "vitest";
import { taskTarget } from "./taskTargets";

describe("permission-filtered task destinations", () => {
  it("keeps terminal review identity and selects its completed queue", () => {
    expect(taskTarget({ routeKey: "reviews", resourceId: "review one", status: "rejected" })).toBe(
      "/review?target_id=review+one&queue=completed",
    );
    expect(taskTarget({ routeKey: "reviews", status: "completed" })).toBe("/review/completed");
  });
  it.each(["completed", "rejected", "cancelled", "duplicate_skipped", "waiting_review"])(
    "opens exact upload history for %s",
    (status) => {
      const target = taskTarget({ routeKey: "upload", resourceId: "task/one", status })!;
      const params = new URL(target, "https://kap.test").searchParams;
      expect(params.get("task_id")).toBe("task/one");
      expect(params.get("view")).toBe("history");
    },
  );
  it("lets pending uploads resolve their authorized source instead of forcing local upload", () => {
    expect(taskTarget({ routeKey: "upload", resourceId: "task", status: "needs_action" })).toBe(
      "/upload?target_id=task&task_id=task",
    );
  });
  it("retains the maintenance digest under the canonical agent route", () => {
    expect(
      taskTarget({ routeKey: "maintenance_agent", resourceId: "digest", status: "completed" }),
    ).toBe("/ai-workspace/agents/knowledge-maintenance?target_id=digest&mine=true&status=all");
  });
  it("opens aggregated maintenance across knowledge bases rather than the default company library", () => {
    expect(taskTarget({ routeKey: "maintenance_agent", status: "needs_action" })).toBe(
      "/ai-workspace/agents/knowledge-maintenance?view=mine&mine=true",
    );
  });
  it("does not interpret an arbitrary route or an absent resource as a destination", () => {
    expect(taskTarget({ routeKey: "https://outside.test", status: "completed" })).toBeNull();
    expect(taskTarget({ routeKey: "knowledge_detail", status: "completed" })).toBeNull();
  });
});
