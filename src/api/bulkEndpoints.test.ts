import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IngestConfirmRequestDTO } from "../types/ingest";
import type { BulkOperationResponseDTO } from "../types/bulk";

const { apiPostMock } = vi.hoisted(() => ({ apiPostMock: vi.fn() }));

vi.mock("./http", () => ({
  BASE_URL: "",
  apiDelete: vi.fn(),
  apiGet: vi.fn(),
  apiPost: apiPostMock,
  apiPostNoBody: vi.fn(),
  csrfHeaders: vi.fn(),
  handleResponse: vi.fn(),
  withCsrfRetry: vi.fn(),
  createClientUuid: () => "00000000-0000-4000-8000-000000000099",
}));

import { bulkConfirmIngest } from "./ingest";
import { bulkDeleteKnowledgeAssets } from "./knowledge";
import { bulkRequestAssetConfirmation, bulkRequestCompanyUpgrade } from "./review";

function responseFor(itemIds: string[]): BulkOperationResponseDTO {
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

describe("bounded bulk endpoint clients", () => {
  beforeEach(() => {
    apiPostMock
      .mockReset()
      .mockImplementation(async (path: string, body: Record<string, unknown>) => {
        const itemIds =
          path === "/api/v1/ingest/bulk-confirm"
            ? (body.items as Array<{ task_id: string }>).map((item) => item.task_id)
            : (body.item_ids as string[]);
        return responseFor(itemIds);
      });
  });

  it.each([501, 700, 1001])(
    "splits %i upload confirmations into bounded requests",
    async (total) => {
      const items = Array.from({ length: total }, (_, index) => ({
        taskId: `task-${index}`,
        confirmation: {} as IngestConfirmRequestDTO,
      }));
      const result = await bulkConfirmIngest({ items, targetScope: "personal" });

      expect(apiPostMock).toHaveBeenCalledTimes(Math.ceil(total / 200));
      expect(apiPostMock.mock.calls.map((call) => call[1].items.length)).toEqual(
        Array.from({ length: Math.ceil(total / 200) }, (_, index) =>
          Math.min(200, total - index * 200),
        ),
      );
      expect(result.submitted).toBe(total);
      expect(result.succeeded).toBe(total);
    },
  );

  it.each([501, 700, 1001])("splits %i project deletes into bounded requests", async (total) => {
    const itemIds = Array.from({ length: total }, (_, index) => `asset-${index}`);
    const result = await bulkDeleteKnowledgeAssets({
      itemIds,
      scope: "project",
      projectId: "00000000-0000-4000-8000-000000000002",
    });

    expect(apiPostMock).toHaveBeenCalledTimes(Math.ceil(total / 200));
    expect(apiPostMock.mock.calls.map((call) => call[1].item_ids.length)).toEqual(
      Array.from({ length: Math.ceil(total / 200) }, (_, index) =>
        Math.min(200, total - index * 200),
      ),
    );
    expect(new Set(apiPostMock.mock.calls.map((call) => call[1].client_operation_id)).size).toBe(1);
    expect(result.submitted).toBe(total);
    expect(result.succeeded).toBe(total);
  });

  it("splits project company upgrades and keeps one operation identity", async () => {
    const itemIds = Array.from({ length: 501 }, (_, index) => `asset-${index}`);
    const result = await bulkRequestCompanyUpgrade({
      projectId: "00000000-0000-4000-8000-000000000002",
      itemIds,
    });

    expect(apiPostMock).toHaveBeenCalledTimes(3);
    expect(apiPostMock.mock.calls.map((call) => call[1].item_ids.length)).toEqual([200, 200, 101]);
    expect(new Set(apiPostMock.mock.calls.map((call) => call[1].client_operation_id)).size).toBe(1);
    expect(result.submitted).toBe(501);
  });

  it("splits project material confirmations into bounded requests", async () => {
    const itemIds = Array.from({ length: 501 }, (_, index) => `material-${index}`);
    const result = await bulkRequestAssetConfirmation({
      projectId: "00000000-0000-4000-8000-000000000002",
      itemIds,
    });

    expect(apiPostMock).toHaveBeenCalledTimes(3);
    expect(apiPostMock.mock.calls.map((call) => call[1].item_ids.length)).toEqual([200, 200, 101]);
    expect(result.submitted).toBe(501);
  });
});
