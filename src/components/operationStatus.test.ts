import { describe, expect, it } from "vitest";
import {
  OPERATION_STATUS,
  isTerminalOperationStatus,
  operationStatusFromJob,
} from "./operationStatus";

describe("operation outcomes", () => {
  it.each([
    "rejected",
    "duplicate_skipped",
    "no_action",
    "approval_failed",
    "submitted_pending_index",
  ])("recognizes %s as terminal", (status) => {
    expect(isTerminalOperationStatus(operationStatusFromJob(status))).toBe(true);
  });
  it("does not promise every failure can be retried", () => {
    expect(OPERATION_STATUS.failed.label).not.toContain("重试");
    expect(operationStatusFromJob("waiting_review")).toBe("awaiting_approval");
  });
});
