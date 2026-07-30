import { describe, expect, it, vi } from "vitest";

import {
  BULK_REQUEST_BATCH_SIZE,
  ControlledBulkRequestError,
  runControlledBulkRequests,
} from "./bulk";
import type { BulkOperationResponseDTO } from "../types/bulk";

function terminalResponse(itemIds: readonly string[]): BulkOperationResponseDTO {
  return {
    operation_id: "00000000-0000-4000-8000-000000000001",
    status: "completed",
    execution_mode: itemIds.length > 50 ? "controlled_batch" : "synchronous",
    submitted: itemIds.length,
    succeeded: itemIds.length,
    skipped: 0,
    failed: 0,
    items: itemIds.map((itemId) => ({
      item_id: itemId,
      status: "succeeded",
      reason_code: null,
      message: null,
    })),
  };
}

describe("runControlledBulkRequests", () => {
  it.each([
    [501, [200, 200, 101]],
    [700, [200, 200, 200, 100]],
    [1001, [200, 200, 200, 200, 200, 1]],
  ])(
    "splits %i selected items without treating the API limit as a business limit",
    async (total, expected) => {
      const items = Array.from({ length: total }, (_, index) => `item-${index}`);
      const observedSizes: number[] = [];
      const observedContexts: Array<{
        clientOperationId: string;
        requestIndex: number;
        requestCount: number;
        totalSubmitted: number;
      }> = [];

      const result = await runControlledBulkRequests({
        items,
        getItemId: (itemId) => itemId,
        submitBatch: async (batch, context) => {
          observedSizes.push(batch.length);
          observedContexts.push(context);
          return terminalResponse(batch);
        },
      });

      expect(BULK_REQUEST_BATCH_SIZE).toBeLessThanOrEqual(500);
      expect(observedSizes).toEqual(expected);
      expect(observedContexts).toEqual(
        expected.map((_, index) =>
          expect.objectContaining({
            requestIndex: index + 1,
            requestCount: expected.length,
            totalSubmitted: total,
          }),
        ),
      );
      expect(new Set(observedContexts.map((context) => context.clientOperationId)).size).toBe(1);
      expect(result.submitted).toBe(total);
      expect(result.succeeded).toBe(total);
      expect(result.items.map((item) => item.item_id)).toEqual(items);
    },
  );

  it("preserves completed batches and exposes only the failed and unsubmitted suffix for retry", async () => {
    const items = Array.from({ length: 700 }, (_, index) => `item-${index}`);
    const submitBatch = vi
      .fn<(batch: readonly string[]) => Promise<BulkOperationResponseDTO>>()
      .mockImplementationOnce(async (batch) => terminalResponse(batch))
      .mockRejectedValueOnce(new Error("network unavailable"));

    let caught: ControlledBulkRequestError<string> | null = null;
    try {
      await runControlledBulkRequests({
        items,
        getItemId: (itemId) => itemId,
        submitBatch,
      });
    } catch (error) {
      if (error instanceof ControlledBulkRequestError) caught = error;
    }

    expect(caught).not.toBeNull();
    expect(submitBatch).toHaveBeenCalledTimes(2);
    expect(caught?.partialResult.submitted).toBe(200);
    expect(caught?.partialResult.succeeded).toBe(200);
    expect(caught?.retryItems).toEqual(items.slice(200));

    const retrySizes: number[] = [];
    const retryResult = await runControlledBulkRequests({
      items: caught?.retryItems ?? [],
      getItemId: (itemId) => itemId,
      submitBatch: async (batch) => {
        retrySizes.push(batch.length);
        return terminalResponse(batch);
      },
    });
    expect(retrySizes).toEqual([200, 200, 100]);
    expect(retryResult.succeeded).toBe(500);
  });
});
