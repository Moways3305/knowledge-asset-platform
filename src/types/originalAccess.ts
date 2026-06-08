// 原文访问申请与授权 API 的 DTO 类型。
// 只含安全治理元数据；不含原文 / 对象存储引用 / 外部系统内部 id / token / URL。

export interface OriginalAccessRequestDTO {
  request_id: string;
  asset_id: string;
  asset_title: string | null;
  scope: string | null;
  project_id: string | null;
  requester_user_id: string;
  requester_name: string | null;
  reviewer_user_id: string | null;
  reviewer_name: string | null;
  requested_access_layer: string;
  status: string;
  reason: string | null;
  review_note: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface AccessGrantDTO {
  grant_id: string;
  asset_id: string;
  grantee_user_id: string;
  grant_type: string;
  source_request_id: string | null;
  status: string;
  expires_at: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface CreateRequestResponseDTO {
  status: string; // created / pending_exists / already_granted / approved / rejected
  message: string;
  request: OriginalAccessRequestDTO | null;
  grant: AccessGrantDTO | null;
}

export interface RequestsListResponseDTO {
  items: OriginalAccessRequestDTO[];
  total: number;
}

