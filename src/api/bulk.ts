import { createClientUuid } from "./http";
import type { BulkItemResultDTO, BulkOperationResponseDTO } from "../types/bulk";

export const BULK_REQUEST_BATCH_SIZE = 200;
export const BULK_SERVER_REQUEST_LIMIT = 500;

export interface ControlledBulkRequestContext {
  clientOperationId: string;
  requestIndex: number;
  requestCount: number;
  totalSubmitted: number;
}

interface ControlledBulkRequestOptions<T> {
  items: readonly T[];
  getItemId: (item: T) => string;
  submitBatch: (
    batch: readonly T[],
    context: ControlledBulkRequestContext,
  ) => Promise<BulkOperationResponseDTO>;
  onBatchCompleted?: (
    response: BulkOperationResponseDTO,
    batch: readonly T[],
    context: ControlledBulkRequestContext,
  ) => void;
  requestBatchSize?: number;
}

export class ControlledBulkRequestError<T> extends Error {
  readonly partialResult: BulkOperationResponseDTO;
  readonly retryItems: T[];

  constructor(partialResult: BulkOperationResponseDTO, retryItems: T[]) {
    super("bulk_request_incomplete");
    this.name = "ControlledBulkRequestError";
    this.partialResult = partialResult;
    this.retryItems = retryItems;
  }
}

function emptyAggregate(operationId: string, total: number): BulkOperationResponseDTO {
  return {
    operation_id: operationId,
    status: "completed",
    execution_mode: total > 50 ? "controlled_batch" : "synchronous",
    submitted: 0,
    succeeded: 0,
    skipped: 0,
    failed: 0,
    items: [],
  };
}

function appendResult(
  aggregate: BulkOperationResponseDTO,
  response: BulkOperationResponseDTO,
): void {
  aggregate.submitted += response.submitted;
  aggregate.succeeded += response.succeeded;
  aggregate.skipped += response.skipped;
  aggregate.failed += response.failed;
  aggregate.items.push(...response.items);
  if (aggregate.skipped > 0 || aggregate.failed > 0) {
    aggregate.status = "completed_with_errors";
  }
}

function validateBatchResponse<T>(
  batch: readonly T[],
  response: BulkOperationResponseDTO,
  getItemId: (item: T) => string,
): void {
  const expectedIds = new Set(batch.map(getItemId));
  const responseIds = new Set(response.items.map((item) => item.item_id));
  if (
    response.submitted !== batch.length ||
    response.items.length !== batch.length ||
    responseIds.size !== expectedIds.size ||
    [...responseIds].some((itemId) => !expectedIds.has(itemId))
  ) {
    throw new Error("bulk_response_mismatch");
  }
}

export async function runControlledBulkRequests<T>(
  options: ControlledBulkRequestOptions<T>,
): Promise<BulkOperationResponseDTO> {
  const requestBatchSize = options.requestBatchSize ?? BULK_REQUEST_BATCH_SIZE;
  if (requestBatchSize < 1 || requestBatchSize > BULK_SERVER_REQUEST_LIMIT) {
    throw new Error("invalid_bulk_request_batch_size");
  }

  // Bind execution to an immutable selection snapshot. Later filter/page changes
  // cannot add items to an operation that is already running.
  const snapshot = [...options.items];
  const itemIds = snapshot.map(options.getItemId);
  if (new Set(itemIds).size !== itemIds.length) {
    throw new Error("duplicate_bulk_item");
  }

  const clientOperationId = createClientUuid();
  const requestCount = Math.ceil(snapshot.length / requestBatchSize);
  const aggregate = emptyAggregate(clientOperationId, snapshot.length);
  if (snapshot.length === 0) return aggregate;

  for (let offset = 0; offset < snapshot.length; offset += requestBatchSize) {
    const batch = snapshot.slice(offset, offset + requestBatchSize);
    const context: ControlledBulkRequestContext = {
      clientOperationId,
      requestIndex: offset / requestBatchSize + 1,
      requestCount,
      totalSubmitted: snapshot.length,
    };
    try {
      const response = await options.submitBatch(batch, context);
      validateBatchResponse(batch, response, options.getItemId);
      appendResult(aggregate, response);
      options.onBatchCompleted?.(response, batch, context);
    } catch {
      aggregate.status = "completed_with_errors";
      throw new ControlledBulkRequestError(aggregate, snapshot.slice(offset));
    }
  }

  return aggregate;
}

export function retryItemIds<T>(
  error: ControlledBulkRequestError<T>,
  getItemId: (item: T) => string,
): string[] {
  return error.retryItems.map(getItemId);
}

export function completedItemResults<T>(error: ControlledBulkRequestError<T>): BulkItemResultDTO[] {
  return error.partialResult.items;
}
