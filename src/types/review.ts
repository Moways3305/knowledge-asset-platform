// 审核流 API 的 DTO 类型。

export interface ReviewItemDTO {
  id: string;
  review_type: string;
  trigger_source: string;
  status: string;
  target_asset_id: string | null;
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
  can_decide: boolean;
  can_withdraw: boolean;
  blocking_reason?: string | null;
  general_manager_confirmation_status: string | null;
  consulting_director_confirmation_status: string | null;
}

export interface AssetizationPreflightItemDTO {
  item_id: string;
  title: string;
  status: "ready" | "existing" | "evidence_missing" | "ineligible";
  evidence_count: number;
  reason_code: string | null;
  message: string | null;
}

export interface AssetizationSubmitResponseDTO {
  submitted: number;
  created: number;
  existing: number;
  evidence_missing: number;
  ineligible: number;
  failed: number;
  items: Array<{
    item_id: string;
    status: string;
    review_status: string | null;
    reason_code: string | null;
    message: string | null;
  }>;
}

export interface EvidenceInputDTO {
  evidence_type: "internal_sharing" | "client_validation";
  evidence_category:
    | "meeting_minutes"
    | "wecom_record"
    | "client_email"
    | "acceptance_doc"
    | "delivery_adoption";
  description: string;
  idempotency_key?: string;
}

export interface ReviewListResponseDTO {
  items: ReviewItemDTO[];
  total: number;
  page?: number;
  page_size?: number;
}
