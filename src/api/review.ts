// 审核流：待审核列表与通过 / 拒绝动作。响应只含安全治理元数据。
import { apiGet, apiPost } from "./http";
import type { ReviewItemDTO, ReviewListResponseDTO } from "../types/review";

export async function fetchReviews(params: {
  reviewType?: string;
  status?: string;
} = {}): Promise<ReviewItemDTO[]> {
  const qs = new URLSearchParams();
  if (params.reviewType) qs.set("review_type", params.reviewType);
  if (params.status) qs.set("status", params.status);
  const data = await apiGet<ReviewListResponseDTO>(`/api/v1/reviews?${qs.toString()}`);
  return data.items;
}

export async function approveReview(reviewId: string, comment?: string): Promise<void> {
  await apiPost(`/api/v1/reviews/${reviewId}/approve`, { review_comment: comment ?? null });
}

export async function rejectReview(reviewId: string, comment: string): Promise<void> {
  await apiPost(`/api/v1/reviews/${reviewId}/reject`, { review_comment: comment });
}
