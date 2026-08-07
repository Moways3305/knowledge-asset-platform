// 知识资产领域：列表 / 详情 / 语义检索 / 受控预览 / 删除 / 重试索引 / 运营洞察 /
// 生命周期归档 / 原文访问申请与授权。所有响应均为后端经权限网关
// 裁剪、脱敏后的安全字段，前端不构造、不展示任何内部标识（WeKnora id / storage 引用等）。
import { apiGet, apiPost } from "./http";
import type {
  AccessInfoDTO,
  AccessInfoVM,
  BackendVisibility,
  FrontVisibility,
  KnowledgeCardVM,
  KnowledgeDeleteResponseDTO,
  KnowledgeDetailDTO,
  KnowledgeDetailVM,
  KnowledgeListItemDTO,
  KnowledgePageVM,
  KnowledgeQueryParams,
  KnowledgeListResponseDTO,
  RetryIndexResponseDTO,
} from "../types/knowledge";
import type { SearchRequestDTO, SearchResponseDTO } from "../types/search";
import type { KnowledgeOpsInsightsDTO } from "../types/insights";
import type { PreviewEntryVM, PreviewIssueResponseDTO } from "../types/preview";
import type { CreateRequestResponseDTO, RequestsListResponseDTO } from "../types/originalAccess";
import type {
  ArchiveConfirmResponseDTO,
  LifecycleActionResponseDTO,
  LifecycleEventsResponseDTO,
} from "../types/lifecycle";
import { runControlledBulkRequests } from "./bulk";

// ---- 转换 helpers ----
const visibilityToFront = (v: BackendVisibility): FrontVisibility =>
  v === "project_only" ? "project-only" : v;

function mapAccess(a: AccessInfoDTO): AccessInfoVM {
  return {
    discovery: a.discovery,
    summary: a.summary,
    original: a.original,
    effectiveSource: a.effective_source,
    canRequestOriginal: a.can_request_original,
    existingRequestStatus: a.existing_request_status,
    existingGrantExpiresAt: a.existing_grant_expires_at,
    canDelete: a.can_delete,
    canManageLifecycle: a.can_manage_lifecycle ?? false,
    canRetryIndex: a.can_retry_index ?? false,
  };
}

// 列表卡片映射。personal 模块复用同一映射，故导出。
export function mapCard(d: KnowledgeListItemDTO): KnowledgeCardVM {
  return {
    id: d.id,
    title: d.title,
    canonicalName: d.canonical_name ?? "",
    scope: d.scope,
    zone: d.zone,
    assetType: d.asset_type,
    confidentialityLevel: d.confidentiality_level,
    aiAccessLevel: d.ai_access_level,
    assetStatus: d.asset_status,
    visibility: visibilityToFront(d.visibility),
    tags: d.tags,
    summary: d.summary_text ?? "",
    projectName: d.project_name ?? "",
    lifecyclePhase: d.lifecycle_phase ?? "",
    confidence: d.confidence,
    lastCalledAt: d.last_called_at ?? "",
    updatedAt: (d.updated_at ?? "").slice(0, 10),
    access: mapAccess(d.access_info),
    indexStatus: d.index_status ?? null,
    parseStatus: d.weknora_parse_status ?? null,
    indexErrorMessage: d.index_error_message ?? null,
    indexedAt: d.indexed_at ?? null,
  };
}

function mapDetail(d: KnowledgeDetailDTO): KnowledgeDetailVM {
  const card = mapCard({
    ...d,
    summary_text: d.summary?.one_liner ?? null,
  } as KnowledgeListItemDTO);
  return {
    ...card,
    projectId: d.project_id,
    maintainerName: d.maintainer?.name ?? "",
    archivedAt: d.archived_at,
    archiveReason: d.archive_reason,
    oneLiner: d.summary?.one_liner ?? "",
    detailed: d.summary?.detailed ?? "",
    keyPoints: d.summary?.key_points ?? [],
    currentVersionNo: d.current_version?.display_version ?? d.current_version?.version_no ?? null,
    indexErrorCode: d.index_error_code ?? null,
  };
}

// ---- 列表 / 详情 ----
export async function fetchKnowledgePage(
  params: KnowledgeQueryParams = {},
): Promise<KnowledgePageVM> {
  const qs = new URLSearchParams();
  if (params.page != null) qs.set("page", String(params.page));
  if (params.pageSize != null) qs.set("page_size", String(params.pageSize));
  if (params.keyword) qs.set("keyword", params.keyword);
  if (params.scope) qs.set("scope", params.scope);
  if (params.projectId) qs.set("project_id", params.projectId);
  if (params.zone) qs.set("zone", params.zone);
  if (params.assetType) qs.set("asset_type", params.assetType);
  if (params.assetStatus) qs.set("asset_status", params.assetStatus);
  if (params.confidentialityLevel) qs.set("confidentiality_level", params.confidentialityLevel);
  if (params.createdFrom) qs.set("created_from", params.createdFrom);
  if (params.createdTo) qs.set("created_to", params.createdTo);
  if (params.updatedFrom) qs.set("updated_from", params.updatedFrom);
  if (params.updatedTo) qs.set("updated_to", params.updatedTo);
  if (params.sortBy) qs.set("sort_by", params.sortBy);
  if (params.sortDirection) qs.set("sort_direction", params.sortDirection);
  if (params.includeArchived) qs.set("include_archived", "true");
  const query = qs.toString();
  const data = await apiGet<KnowledgeListResponseDTO>(
    `/api/v1/knowledge${query ? `?${query}` : ""}`,
  );
  return {
    items: data.items.map(mapCard),
    total: data.total,
    page: data.page,
    pageSize: data.page_size,
    hasNext: data.has_next,
  };
}

// Legacy list consumers keep their array contract but now receive the server's
// bounded first page when they do not pass explicit pagination parameters.
export async function fetchKnowledgeList(params: KnowledgeQueryParams): Promise<KnowledgeCardVM[]> {
  return (await fetchKnowledgePage(params)).items;
}

export async function fetchKnowledgeDetail(id: string): Promise<KnowledgeDetailVM> {
  const data = await apiGet<KnowledgeDetailDTO>(`/api/v1/knowledge/${id}`);
  return mapDetail(data);
}

// 受控删除 / 撤下知识资产。后端按 scope 权威校验删除权。
export async function deleteKnowledgeAsset(
  id: string,
  reason?: string,
): Promise<KnowledgeDeleteResponseDTO> {
  return apiPost<KnowledgeDeleteResponseDTO>(`/api/v1/knowledge/${id}/delete`, {
    reason: reason ?? null,
  });
}

export async function bulkDeleteKnowledgeAssets(input: {
  itemIds: string[];
  scope: "personal" | "project";
  projectId?: string;
  reason?: string;
}): Promise<import("../types/bulk").BulkOperationResponseDTO> {
  return runControlledBulkRequests({
    items: input.itemIds,
    getItemId: (itemId) => itemId,
    submitBatch: (batch, context) =>
      apiPost("/api/v1/knowledge/bulk-delete", {
        item_ids: batch,
        scope: input.scope,
        project_id: input.projectId ?? null,
        reason: input.reason ?? null,
        client_operation_id: context.clientOperationId,
        request_index: context.requestIndex,
        request_count: context.requestCount,
        total_submitted: context.totalSubmitted,
      }),
  });
}

// 重试底座索引。仅对 index_failed / not_indexed / skipped 且调用人有业务管理权。
export async function retryKnowledgeIndex(id: string): Promise<RetryIndexResponseDTO> {
  return apiPost<RetryIndexResponseDTO>(`/api/v1/knowledge/${id}/retry-index`, {});
}

// Knowledge 运营洞察。真实表安全聚合；纯 admin title_visible=false。
export async function fetchKnowledgeOpsInsights(params?: {
  scope?: string;
  days?: number;
  limit?: number;
}): Promise<KnowledgeOpsInsightsDTO> {
  const q = new URLSearchParams();
  if (params?.scope) q.set("scope", params.scope);
  if (params?.days != null) q.set("days", String(params.days));
  if (params?.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiGet<KnowledgeOpsInsightsDTO>(`/api/v1/knowledge/ops-insights${qs ? `?${qs}` : ""}`);
}

// 统一语义检索 / 问答。后端经权限网关裁剪、脱敏与审计，响应只含安全字段
// （业务标识 + 安全摘要 + 相关度 + 脱敏引用），不含任何 WeKnora id / storage 引用 / 原文全文。
export async function searchKnowledge(input: SearchRequestDTO): Promise<SearchResponseDTO> {
  return apiPost<SearchResponseDTO>(`/api/v1/knowledge/search`, input);
}

// ---- 受控预览 ----
export async function issuePreview(assetId: string): Promise<PreviewIssueResponseDTO> {
  return apiPost<PreviewIssueResponseDTO>(`/api/v1/knowledge/${assetId}/preview`, {});
}

export async function fetchPreviewEntry(entryUrl: string): Promise<PreviewEntryVM> {
  const data = await apiGet<Record<string, unknown>>(entryUrl);
  return {
    previewType: String(data.preview_type ?? ""),
    documentTitle: String(data.document_title ?? ""),
    expiresAt: String(data.expires_at ?? ""),
    status: String(data.credential_status ?? ""),
    renderType: typeof data.render_type === "string" ? data.render_type : null,
    fileUrl: typeof data.file_url === "string" ? data.file_url : null,
    onlyofficeConfig: (data["onlyoffice_" + "config"] as Record<string, unknown> | null) ?? null,
    message: typeof data.message === "string" ? data.message : null,
  };
}

// 平台受控预览入口的绝对地址（用于前端打开后端受控预览入口，不含对象存储 URL / 完整 token）。
// ---- 知识生命周期归档 ----
// 治理流程：request 仅产生预警/候选，confirm 才人工确认状态变更；Agent 不执行治理动作。
export async function lifecycleArchiveRequest(
  assetId: string,
  body: { reason: string; candidate_source?: string },
): Promise<LifecycleActionResponseDTO> {
  return apiPost<LifecycleActionResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/archive-request`,
    body,
  );
}

export async function lifecycleArchiveConfirm(
  assetId: string,
  body: { reason: string },
): Promise<ArchiveConfirmResponseDTO> {
  return apiPost<ArchiveConfirmResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/archive-confirm`,
    body,
  );
}

export async function fetchLifecycleEvents(assetId: string): Promise<LifecycleEventsResponseDTO> {
  return apiGet<LifecycleEventsResponseDTO>(`/api/v1/knowledge/${assetId}/lifecycle/events`);
}

// ---- 原文访问申请与授权 ----
// 申请=业务用户且可发现该资产；审批/拒绝=项目经理 / 治理角色。响应只含安全元数据。
export async function requestOriginalAccess(
  assetId: string,
  reason?: string,
): Promise<CreateRequestResponseDTO> {
  return apiPost<CreateRequestResponseDTO>(`/api/v1/knowledge/${assetId}/original-access/request`, {
    reason: reason ?? null,
  });
}

export async function fetchOriginalAccessRequests(
  box: "mine" | "inbox" = "mine",
): Promise<RequestsListResponseDTO> {
  return apiGet<RequestsListResponseDTO>(`/api/v1/original-access/requests?box=${box}`);
}

export async function approveOriginalAccess(
  requestId: string,
  note?: string,
): Promise<CreateRequestResponseDTO> {
  return apiPost<CreateRequestResponseDTO>(
    `/api/v1/original-access/requests/${requestId}/approve`,
    { note: note ?? null },
  );
}

export async function rejectOriginalAccess(
  requestId: string,
  note?: string,
): Promise<CreateRequestResponseDTO> {
  return apiPost<CreateRequestResponseDTO>(`/api/v1/original-access/requests/${requestId}/reject`, {
    note: note ?? null,
  });
}

export async function bulkOriginalAccessAction(input: {
  itemIds: string[];
  action: "approve" | "reject";
  note?: string;
}): Promise<import("../types/bulk").BulkOperationResponseDTO> {
  return runControlledBulkRequests({
    items: input.itemIds,
    getItemId: (itemId) => itemId,
    submitBatch: (batch, context) =>
      apiPost("/api/v1/original-access/requests/bulk-action", {
        item_ids: batch,
        action: input.action,
        note: input.note ?? null,
        client_operation_id: context.clientOperationId,
        request_index: context.requestIndex,
        request_count: context.requestCount,
        total_submitted: context.totalSubmitted,
      }),
  });
}
