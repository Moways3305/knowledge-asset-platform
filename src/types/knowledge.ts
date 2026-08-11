// 后端 Knowledge 读 API 的 DTO 类型（snake_case，对齐后端响应）。
// 以及前端使用的 ViewModel 类型（camelCase / 前端枚举口径）。

export type BackendVisibility = "public" | "project_only" | "confidential";
export type FrontVisibility = "public" | "project-only" | "confidential";
export type ConfidentialityLevel = "L1" | "L2" | "L3" | "L4" | "L5";
export type AiAccessLevel = "A1" | "A2" | "A3" | "A4";
export type AssetStatus = "active" | "needs_update" | "deprecated" | "archived";
export type KnowledgeScope = "personal" | "project" | "company";
export type KnowledgeZone = "material" | "asset";
export type AssetType = "methodology" | "deliverable" | "case" | "template" | "insight";
export type KnowledgeSortField =
  | "updated_at"
  | "created_at"
  | "title"
  | "confidentiality_level"
  | "asset_status";
export type SortDirection = "asc" | "desc";

// ---- 后端 DTO ----
export interface AccessInfoDTO {
  discovery: boolean;
  summary: boolean;
  original: boolean;
  effective_source: string;
  can_request_original: boolean;
  existing_request_status: string | null;
  existing_grant_expires_at: string | null;
  can_delete: boolean;
  can_manage_lifecycle: boolean;
  can_retry_index?: boolean;
}

// 平台级底座索引安全状态（无 kb/doc id / 内部存储引用）。
export type IndexStatus = "not_indexed" | "indexing" | "indexed" | "index_failed" | "skipped";

export interface RetryIndexResponseDTO {
  asset_id: string;
  index_status: string;
  weknora_parse_status: string | null;
  index_error_code: string | null;
  index_error_message: string | null;
  trace_id: string | null;
}

export interface KnowledgeDeleteResponseDTO {
  asset_id: string;
  asset_status: string;
  deleted_at: string | null;
  trace_id: string | null;
}

export interface KnowledgeListItemDTO {
  id: string;
  title: string;
  canonical_name?: string | null;
  scope: KnowledgeScope;
  zone: string;
  asset_type: string;
  confidentiality_level: ConfidentialityLevel;
  ai_access_level: AiAccessLevel;
  asset_status: AssetStatus;
  visibility: BackendVisibility;
  tags: string[];
  summary_text: string | null;
  project_name: string | null;
  lifecycle_phase: string | null;
  confidence: number | null;
  last_called_at: string | null;
  updated_at: string | null;
  access_info: AccessInfoDTO;
  index_status?: string | null;
  weknora_parse_status?: string | null;
  index_error_message?: string | null;
  indexed_at?: string | null;
}

export interface KnowledgeItemsResponseDTO {
  items: KnowledgeListItemDTO[];
  total: number;
}

export interface KnowledgeListResponseDTO extends KnowledgeItemsResponseDTO {
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface KnowledgeQueryParams {
  page?: number;
  pageSize?: number;
  keyword?: string;
  scope?: KnowledgeScope;
  projectId?: string;
  zone?: KnowledgeZone;
  assetType?: AssetType;
  assetStatus?: AssetStatus;
  confidentialityLevel?: ConfidentialityLevel;
  createdFrom?: string;
  createdTo?: string;
  updatedFrom?: string;
  updatedTo?: string;
  sortBy?: KnowledgeSortField;
  sortDirection?: SortDirection;
  includeArchived?: boolean;
}

export interface KnowledgeDetailDTO {
  id: string;
  title: string;
  canonical_name?: string | null;
  scope: KnowledgeScope;
  zone: string;
  asset_type: string;
  confidentiality_level: ConfidentialityLevel;
  ai_access_level: AiAccessLevel;
  asset_status: AssetStatus;
  visibility: BackendVisibility;
  tags: string[];
  project_id: string | null;
  project_name: string | null;
  lifecycle_phase: string | null;
  maintainer: { id: string; name: string } | null;
  confidence: number | null;
  last_called_at: string | null;
  updated_at: string | null;
  archived_at: string | null;
  archive_reason: string | null;
  summary: { one_liner: string | null; detailed: string | null; key_points: string[] } | null;
  current_version: {
    id: string;
    version_no: string;
    version_status: string;
    display_version?: string | null;
  } | null;
  canonical_markdown_status?: "generated" | "not_generated";
  access_info: AccessInfoDTO;
  index_status?: string | null;
  weknora_parse_status?: string | null;
  index_error_code?: string | null;
  index_error_message?: string | null;
  indexed_at?: string | null;
}

// ---- 前端 ViewModel ----
export interface AccessInfoVM {
  discovery: boolean;
  summary: boolean;
  original: boolean;
  effectiveSource: string;
  canRequestOriginal: boolean;
  existingRequestStatus: string | null;
  existingGrantExpiresAt: string | null;
  canDelete: boolean;
  canManageLifecycle: boolean;
  canRetryIndex: boolean;
}

export interface KnowledgeCardVM {
  id: string;
  title: string;
  canonicalName?: string;
  scope: KnowledgeScope;
  zone: string;
  assetType: string;
  confidentialityLevel: ConfidentialityLevel;
  aiAccessLevel: AiAccessLevel;
  assetStatus: AssetStatus;
  visibility: FrontVisibility;
  tags: string[];
  summary: string;
  projectName: string;
  lifecyclePhase: string;
  confidence: number | null;
  lastCalledAt: string;
  updatedAt: string;
  access: AccessInfoVM;
  indexStatus: string | null;
  parseStatus: string | null;
  indexErrorMessage: string | null;
  indexedAt: string | null;
}

export interface KnowledgePageVM {
  items: KnowledgeCardVM[];
  total: number;
  page: number;
  pageSize: number;
  hasNext: boolean;
}

export interface KnowledgeDetailVM extends KnowledgeCardVM {
  projectId: string | null;
  maintainerName: string;
  archivedAt: string | null;
  archiveReason: string | null;
  oneLiner: string;
  detailed: string;
  keyPoints: string[];
  currentVersionNo: string | null;
  indexErrorCode: string | null;
  canonicalMarkdownStatus: "generated" | "not_generated";
}
