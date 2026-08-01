// 审核流：待审核列表与通过 / 拒绝动作。响应只含安全治理元数据。
import { apiGet, apiPost } from "./http";
import type { ReviewItemDTO, ReviewListResponseDTO } from "../types/review";
import type { BulkOperationResponseDTO } from "../types/bulk";
import { runControlledBulkRequests } from "./bulk";

export async function fetchReviews(
  params: {
    queue?: "open" | "completed";
    reviewType?: string;
    status?: string;
    page?: number;
    pageSize?: number;
  } = {},
): Promise<ReviewItemDTO[]> {
  return (await fetchReviewPage(params)).items;
}

export async function fetchReviewPage(
  params: {
    queue?: "open" | "completed";
    reviewType?: string;
    status?: string;
    page?: number;
    pageSize?: number;
  } = {},
): Promise<ReviewListResponseDTO> {
  const qs = new URLSearchParams();
  if (params.queue) qs.set("queue", params.queue);
  if (params.reviewType) qs.set("review_type", params.reviewType);
  if (params.status) qs.set("status", params.status);
  if (params.page) qs.set("page", String(params.page));
  if (params.pageSize) qs.set("page_size", String(params.pageSize));
  return apiGet<ReviewListResponseDTO>(`/api/v1/reviews?${qs.toString()}`);
}

export async function approveReview(reviewId: string, comment?: string): Promise<void> {
  await apiPost(`/api/v1/reviews/${reviewId}/approve`, { review_comment: comment ?? null });
}

export async function rejectReview(reviewId: string, comment: string): Promise<void> {
  await apiPost(`/api/v1/reviews/${reviewId}/reject`, { review_comment: comment });
}

export async function bulkReviewAction(input: {
  itemIds: string[];
  action: "approve" | "reject";
  comment?: string;
}): Promise<BulkOperationResponseDTO> {
  return runControlledBulkRequests({
    items: input.itemIds,
    getItemId: (itemId) => itemId,
    submitBatch: (batch, context) =>
      apiPost<BulkOperationResponseDTO>("/api/v1/reviews/bulk-action", {
        item_ids: batch,
        action: input.action,
        review_comment: input.comment ?? null,
        client_operation_id: context.clientOperationId,
        request_index: context.requestIndex,
        request_count: context.requestCount,
        total_submitted: context.totalSubmitted,
      }),
  });
}

export async function withdrawReviewConfirmation(
  reviewId: string,
  comment?: string,
): Promise<void> {
  await apiPost(`/api/v1/reviews/${reviewId}/withdraw`, { review_comment: comment ?? null });
}

export async function requestCompanyUpgrade(
  projectId: string,
  assetId: string,
): Promise<ReviewItemDTO> {
  return apiPost<ReviewItemDTO>(
    `/api/v1/projects/${projectId}/knowledge/${assetId}/upgrade-company`,
    {},
  );
}

export async function bulkRequestCompanyUpgrade(input: {
  projectId: string;
  itemIds: string[];
}): Promise<BulkOperationResponseDTO> {
  return runControlledBulkRequests({
    items: input.itemIds,
    getItemId: (itemId) => itemId,
    submitBatch: (batch, context) =>
      apiPost<BulkOperationResponseDTO>(
        `/api/v1/projects/${input.projectId}/knowledge/bulk-upgrade-company`,
        {
          item_ids: batch,
          client_operation_id: context.clientOperationId,
          request_index: context.requestIndex,
          request_count: context.requestCount,
          total_submitted: context.totalSubmitted,
        },
      ),
  });
}

export async function bulkRequestAssetConfirmation(input: {
  projectId: string;
  itemIds: string[];
}): Promise<BulkOperationResponseDTO> {
  return runControlledBulkRequests({
    items: input.itemIds,
    getItemId: (itemId) => itemId,
    submitBatch: (batch, context) =>
      apiPost<BulkOperationResponseDTO>(
        `/api/v1/projects/${input.projectId}/knowledge/bulk-confirm-asset`,
        {
          item_ids: batch,
          client_operation_id: context.clientOperationId,
          request_index: context.requestIndex,
          request_count: context.requestCount,
          total_submitted: context.totalSubmitted,
        },
      ),
  });
}
