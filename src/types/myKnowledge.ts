import type { KnowledgeCardVM, KnowledgeListItemDTO } from "./knowledge";

export type PersonalKnowledgeState =
  | "awaiting_confirmation"
  | "ready_to_submit"
  | "pending_project_review"
  | "active_in_project"
  | "project_rejected"
  | "evidence_registered";

export interface PersonalProjectSubmissionDTO {
  status: string;
  target_project_name: string | null;
  submitted_at: string;
  resolved_at: string | null;
}

export interface PersonalEvidenceSummaryDTO {
  registered_count: number;
  latest_status: string | null;
  updated_at: string | null;
}

export interface PersonalKnowledgeItemDTO extends KnowledgeListItemDTO {
  created_at: string;
  personal_state: PersonalKnowledgeState;
  personal_state_label: string;
  project_submission: PersonalProjectSubmissionDTO | null;
  evidence_summary: PersonalEvidenceSummaryDTO | null;
}

export interface PersonalKnowledgeSummaryDTO {
  total_assets: number;
  awaiting_confirmation: number;
  pending_project_review: number;
  active_in_project: number;
  created_this_month: number;
}

export interface PersonalKnowledgeListDTO {
  items: PersonalKnowledgeItemDTO[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
  summary: PersonalKnowledgeSummaryDTO;
}

export interface PersonalKnowledgeItemVM extends KnowledgeCardVM {
  createdAt: string;
  personalState: PersonalKnowledgeState;
  personalStateLabel: string;
  projectSubmission: PersonalProjectSubmissionDTO | null;
  evidenceSummary: PersonalEvidenceSummaryDTO | null;
}

export interface PersonalKnowledgePageVM {
  items: PersonalKnowledgeItemVM[];
  total: number;
  page: number;
  pageSize: number;
  hasNext: boolean;
  summary: PersonalKnowledgeSummaryDTO;
}

export interface PersonalKnowledgeQuery {
  page?: number;
  pageSize?: number;
  keyword?: string;
  assetType?: string;
  personalState?: PersonalKnowledgeState;
  sortBy?: "updated_at" | "created_at" | "title";
  sortDirection?: "asc" | "desc";
}

export interface PersonalKnowledgeUpdateRequestDTO {
  title?: string;
  asset_type?: string;
  tags?: string[];
}

export interface ConfirmAssetResponseDTO {
  asset_id: string;
  zone: string;
  status: string;
  message: string;
}

export interface SubmitToProjectRequestDTO {
  target_project_id: string;
  note?: string;
}

export interface ValidationCandidateRequestDTO {
  target_project_id: string;
  evidence_type: "internal_sharing" | "client_validation";
  evidence_category: string;
  description?: string;
  note?: string;
}

export interface PersonalKnowledgeSubmissionDTO {
  submission_id: string;
  asset_id: string;
  target_project_id: string | null;
  target_project_name: string | null;
  submission_type: string;
  status: string;
  review_task_id: string | null;
  evidence_id: string | null;
  created_at: string;
  message: string;
  next_action: string;
}
