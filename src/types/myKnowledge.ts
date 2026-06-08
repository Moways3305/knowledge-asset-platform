// 个人知识写动作 API 的 DTO 类型。
// 只含安全治理元数据；不含原文 / 摘要全文 / 附件真实 URL / 内部存储引用（后端本就不返回）。

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

