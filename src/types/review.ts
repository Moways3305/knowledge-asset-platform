// 审核流 API 的 DTO 类型。

export interface ReviewItemDTO {
  id: string;
  review_type: string;
  trigger_source: string;
  status: string;
  target_asset_id: string;
  asset_title: string | null;
  target_scope: string | null;
  target_project_id: string | null;
  project_name: string | null;
  submitted_by: string | null;
  reviewer_user_id: string | null;
  evidence_count: number;
  review_comment: string | null;
  reviewed_at: string | null;
  created_at: string | null;
}

export interface ReviewListResponseDTO {
  items: ReviewItemDTO[];
  total: number;
}
