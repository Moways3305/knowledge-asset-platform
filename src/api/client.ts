// 轻量 API client：统一处理 base URL、开发态身份头（X-Dev-User-Id）、错误，
// 以及后端 snake_case DTO 到前端 ViewModel 的转换。
// 页面组件不应直接写 fetch / 字段转换细节。

import type {
  AccessInfoDTO,
  AccessInfoVM,
  BackendVisibility,
  FrontVisibility,
  KnowledgeCardVM,
  KnowledgeDetailDTO,
  KnowledgeDetailVM,
  KnowledgeListItemDTO,
  KnowledgeListResponseDTO,
} from "../types/knowledge";
import type { SearchRequestDTO, SearchResponseDTO } from "../types/search";
import type { KnowledgeDeleteResponseDTO } from "../types/knowledge";
import type {
  ProjectCreateRequestDTO,
  ProjectCreateResponseDTO,
  ProjectListResponseDTO,
} from "../types/project";
import type {
  IngestAiResultDTO,
  IngestConfirmRequestDTO,
  IngestConfirmResponseDTO,
  IngestUploadResponseDTO,
  PendingIngestListResponseDTO,
  PendingIngestItemDTO,
} from "../types/ingest";
import type { ReviewItemDTO, ReviewListResponseDTO } from "../types/review";
import type { PreviewIssueResponseDTO } from "../types/preview";
import type { ProjectQaResponseDTO } from "../types/agent";
import type {
  AuditListResponseDTO,
  AuditTraceResponseDTO,
  MarkProcessedResponseDTO,
} from "../types/audit";
import type {
  AlertRuleDTO,
  AlertRulesResponseDTO,
  AlertRuleUpdateDTO,
  NotificationsResponseDTO,
} from "../types/alert";
import type { AdminIngestListResponseDTO } from "../types/ingest";
import type {
  WecomAuthorizeDTO,
  WecomOwnerOptionsResponseDTO,
  WecomScanConfigCreateBody,
  WecomScanConfigDTO,
  WecomScanConfigsResponseDTO,
  WecomScanConfigUpdateBody,
  WecomProjectOptionsResponseDTO,
  WecomScanRecordDTO,
  WecomScanRecordsResponseDTO,
} from "../types/wecom";
import type {
  PeopleListResponseDTO,
  PersonDTO,
  PersonProjectMembershipDTO,
} from "../types/people";
import type {
  AgentRegistryListResponseDTO,
  AgentRegistryRuleDTO,
  AgentRegistryUpdateResponseDTO,
  PermissionRuleDTO,
  PermissionRulesResponseDTO,
  PermissionRuleUpdateDTO,
} from "../types/permission";
import type {
  ProjectMemberDTO,
  ProjectMemberPatchDTO,
  ProjectMembersResponseDTO,
  ProjectSettingsDTO,
  ProjectSettingsUpdateDTO,
} from "../types/projectSettings";
import type {
  ConfirmAssetResponseDTO,
  PersonalKnowledgeSubmissionDTO,
  SubmitToProjectRequestDTO,
  ValidationCandidateRequestDTO,
} from "../types/myKnowledge";
import type {
  AccessGrantDTO,
  CreateRequestResponseDTO,
  RequestsListResponseDTO,
} from "../types/originalAccess";
import type {
  ArchiveConfirmResponseDTO,
  LifecycleActionResponseDTO,
  LifecycleEventsResponseDTO,
  ReenableConfirmResponseDTO,
} from "../types/lifecycle";

// 默认走 Vite 的 /api 代理；也可用 VITE_API_BASE_URL 覆盖为绝对地址。
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

// 开发态身份覆盖：本地联调时用 X-Dev-User-Id 指定调用人，方便切换角色。
// 正式登录态已由后端 httpOnly cookie 会话（kap_session）承载（见 login/logout）；
// 该 header 仅在设置 VITE_DEV_USER_ID 时附带，留空则完全走 cookie 会话。
const DEV_USER_ID = import.meta.env.VITE_DEV_USER_ID ?? "";

export class ApiError extends Error {
  status: number;
  deniedReason?: string;
  constructor(status: number, message: string, deniedReason?: string) {
    super(message);
    this.status = status;
    this.deniedReason = deniedReason;
  }
}

function devHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (DEV_USER_ID) headers["X-Dev-User-Id"] = DEV_USER_ID;
  return headers;
}

async function handleResponse<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let deniedReason: string | undefined;
    let message = `请求失败（${resp.status}）`;
    try {
      const body = await resp.json();
      const detail = body?.detail;
      if (detail && typeof detail === "object") {
        deniedReason = detail.denied_reason;
        message = detail.message ?? message;
      }
    } catch {
      // 忽略非 JSON 错误体
    }
    throw new ApiError(resp.status, message, deniedReason);
  }
  return (await resp.json()) as T;
}

// 所有请求带上 credentials，使会话 cookie（kap_session, httpOnly）随同发送。
// 同源经 Vite /api 代理时 cookie 正常工作；X-Dev-User-Id 仍作为开发态回退。
async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: devHeaders(),
    credentials: "include",
  });
  return handleResponse<T>(resp);
}

async function apiPost<T>(path: string, body: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: devHeaders({ "Content-Type": "application/json", ...extraHeaders }),
    body: JSON.stringify(body),
    credentials: "include",
  });
  return handleResponse<T>(resp);
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method: "PATCH",
    headers: devHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    credentials: "include",
  });
  return handleResponse<T>(resp);
}

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
  };
}

function mapCard(d: KnowledgeListItemDTO): KnowledgeCardVM {
  return {
    id: d.id,
    title: d.title,
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
    currentVersionNo: d.current_version?.version_no ?? null,
  };
}

// ---- 公开 API ----
export async function fetchKnowledgeList(params: {
  scope?: string;
  includeArchived?: boolean;
}): Promise<KnowledgeCardVM[]> {
  const qs = new URLSearchParams();
  if (params.scope) qs.set("scope", params.scope);
  if (params.includeArchived) qs.set("include_archived", "true");
  const data = await apiGet<KnowledgeListResponseDTO>(`/api/v1/knowledge?${qs.toString()}`);
  return data.items.map(mapCard);
}

export async function fetchKnowledgeDetail(id: string): Promise<KnowledgeDetailVM> {
  const data = await apiGet<KnowledgeDetailDTO>(`/api/v1/knowledge/${id}`);
  return mapDetail(data);
}

// 受控删除 / 撤下知识资产（PBC-10B，软删除）。后端按 scope 权威校验删除权。
export async function deleteKnowledgeAsset(
  id: string,
  reason?: string
): Promise<KnowledgeDeleteResponseDTO> {
  return apiPost<KnowledgeDeleteResponseDTO>(`/api/v1/knowledge/${id}/delete`, {
    reason: reason ?? null,
  });
}

// 项目列表（治理角色 / admin 看全部 active；业务用户看本人 active 项目）。
export async function fetchProjects(): Promise<ProjectListResponseDTO> {
  return apiGet<ProjectListResponseDTO>(`/api/v1/projects`);
}

// 创建项目知识空间（仅 Boss / 咨询总监）。写真实 projects + active project_manager 成员。
export async function createProject(
  body: ProjectCreateRequestDTO
): Promise<ProjectCreateResponseDTO> {
  return apiPost<ProjectCreateResponseDTO>(`/api/v1/projects`, body);
}

export async function fetchMyKnowledge(): Promise<KnowledgeCardVM[]> {
  const data = await apiGet<KnowledgeListResponseDTO>(`/api/v1/my/knowledge`);
  return data.items.map(mapCard);
}

// 统一语义检索 / 问答（R3）。后端经权限网关裁剪、脱敏与审计，响应只含安全字段
// （业务标识 + 安全摘要 + 相关度 + 脱敏引用），不含任何 WeKnora id / storage_ref / 原文全文。
export async function searchKnowledge(input: SearchRequestDTO): Promise<SearchResponseDTO> {
  return apiPost<SearchResponseDTO>(`/api/v1/knowledge/search`, input);
}

// ---- 身份上下文（会话身份；用于顶栏展示与入库时选择目标项目） ----
export interface AuthMeVM {
  userId: string;
  name: string;
  email: string;
  companyRoles: string[];
  isBusinessUser: boolean;
  canDiscoverL5: boolean;
  projects: { projectId: string; projectName: string; projectRole: string }[];
}

interface AuthMeDTO {
  user_id: string;
  name: string;
  email: string;
  status: string;
  company_roles: string[];
  is_business_user: boolean;
  can_discover_l5: boolean;
  project_memberships: { project_id: string; project_name: string; project_role: string; status: string }[];
}

function mapAuthMe(data: AuthMeDTO): AuthMeVM {
  return {
    userId: data.user_id,
    name: data.name,
    email: data.email,
    companyRoles: data.company_roles,
    isBusinessUser: data.is_business_user,
    canDiscoverL5: data.can_discover_l5,
    projects: data.project_memberships
      .filter((m) => m.status === "active")
      .map((m) => ({ projectId: m.project_id, projectName: m.project_name, projectRole: m.project_role })),
  };
}

export async function fetchAuthMe(): Promise<AuthMeVM> {
  return mapAuthMe(await apiGet<AuthMeDTO>(`/api/v1/auth/me`));
}

// 会话登录 / 登出（IMPLEMENT-12）。明文 token 由后端经 httpOnly cookie 下发，
// 前端不接触、不存储 token；登录态完全由 cookie + /auth/me 决定。
export async function login(email: string): Promise<AuthMeVM> {
  return mapAuthMe(await apiPost<AuthMeDTO>(`/api/v1/auth/login`, { email }));
}

export async function logout(): Promise<void> {
  await apiPostNoBody<{ ok: boolean }>(`/api/v1/auth/logout`);
}

// ---- 入库流水线（Path B） ----
// 真实文件上传：以 multipart/form-data 发送选中的文件字节。后端写入受控存储并
// 只返回安全元数据（不返回任何存储引用 / 路径 / URL）。
export async function createIngestUpload(input: {
  file: File;
  targetScope?: string;
}): Promise<IngestUploadResponseDTO> {
  const form = new FormData();
  form.append("file", input.file, input.file.name);
  if (input.targetScope) form.append("target_scope", input.targetScope);
  const resp = await fetch(`${BASE_URL}/api/v1/ingest/upload`, {
    method: "POST",
    headers: devHeaders(), // 不设 Content-Type：浏览器自动带 multipart boundary
    body: form,
    credentials: "include",
  });
  return handleResponse<IngestUploadResponseDTO>(resp);
}

export async function fetchIngestAiResult(taskId: string): Promise<IngestAiResultDTO> {
  return apiGet<IngestAiResultDTO>(`/api/v1/ingest/${taskId}/ai-result`);
}

// Path A（企微微盘）待确认任务列表（PBC-07）。后端按权限只返回调用人可确认的任务，
// 仅安全元数据；纯 admin 403。前端不复制权限逻辑，只展示接口结果。
export async function fetchPendingIngestTasks(
  source = "path_a_wecom"
): Promise<PendingIngestItemDTO[]> {
  const qs = new URLSearchParams({ source });
  const data = await apiGet<PendingIngestListResponseDTO>(
    `/api/v1/ingest/pending?${qs.toString()}`
  );
  return data.items;
}

export async function confirmIngest(
  taskId: string,
  payload: IngestConfirmRequestDTO
): Promise<IngestConfirmResponseDTO> {
  return apiPost<IngestConfirmResponseDTO>(`/api/v1/ingest/${taskId}/confirm`, payload);
}

// ---- 审核流 ----
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

// ---- 预览凭证 ----
export async function issuePreview(assetId: string): Promise<PreviewIssueResponseDTO> {
  return apiPost<PreviewIssueResponseDTO>(`/api/v1/knowledge/${assetId}/preview`, {});
}

// 平台受控预览入口的绝对地址（用于前端打开后端受控预览入口，不含对象存储 URL / 完整 token）。
export function previewEntryHref(entryUrl: string): string {
  return `${BASE_URL}${entryUrl}`;
}

// ---- Admin Audit（审计日志查询 / trace / 标记处理） ----
// 权限：admin 或 boss / 咨询总监；普通业务用户 403。响应按角色脱敏，
// 前端不构造、不展示任何内部标识（后端本就不返回）。
async function apiPostNoBody<T>(path: string, extraHeaders: Record<string, string> = {}): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: devHeaders({ "Content-Type": "application/json", ...extraHeaders }),
    body: "{}",
    credentials: "include",
  });
  return handleResponse<T>(resp);
}

export async function fetchAudit(params: {
  logType?: string;
  action?: string;
  severity?: string;
  isProcessed?: boolean;
  traceId?: string;
  pageSize?: number;
} = {}): Promise<AuditListResponseDTO> {
  const qs = new URLSearchParams();
  if (params.logType) qs.set("log_type", params.logType);
  if (params.action) qs.set("action", params.action);
  if (params.severity) qs.set("severity", params.severity);
  if (params.isProcessed !== undefined) qs.set("is_processed", String(params.isProcessed));
  if (params.traceId) qs.set("trace_id", params.traceId);
  qs.set("page_size", String(params.pageSize ?? 200));
  return apiGet<AuditListResponseDTO>(`/api/v1/admin/audit?${qs.toString()}`);
}

export async function fetchAuditTrace(traceId: string): Promise<AuditTraceResponseDTO> {
  return apiGet<AuditTraceResponseDTO>(`/api/v1/admin/audit/trace/${encodeURIComponent(traceId)}`);
}

export async function markAuditProcessed(eventId: string): Promise<MarkProcessedResponseDTO> {
  return apiPostNoBody<MarkProcessedResponseDTO>(`/api/v1/admin/audit/${eventId}/mark-processed`);
}

// ---- 知识生命周期动作（归档 / 重新启用；契约 §14A） ----
// 治理流程：request 仅产生预警/候选，confirm 才人工确认状态变更；Agent 不执行治理动作。
export async function lifecycleArchiveRequest(
  assetId: string,
  body: { reason: string; candidate_source?: string }
): Promise<LifecycleActionResponseDTO> {
  return apiPost<LifecycleActionResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/archive-request`,
    body
  );
}

export async function lifecycleArchiveConfirm(
  assetId: string,
  body: { reason: string }
): Promise<ArchiveConfirmResponseDTO> {
  return apiPost<ArchiveConfirmResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/archive-confirm`,
    body
  );
}

export async function lifecycleReenableRequest(
  assetId: string,
  body: { reason: string; target_status?: string }
): Promise<LifecycleActionResponseDTO> {
  return apiPost<LifecycleActionResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/reenable-request`,
    body
  );
}

export async function lifecycleReenableConfirm(
  assetId: string,
  body: { reason: string; target_status: string }
): Promise<ReenableConfirmResponseDTO> {
  return apiPost<ReenableConfirmResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/reenable-confirm`,
    body
  );
}

export async function fetchLifecycleEvents(
  assetId: string
): Promise<LifecycleEventsResponseDTO> {
  return apiGet<LifecycleEventsResponseDTO>(
    `/api/v1/knowledge/${assetId}/lifecycle/events`
  );
}

// ---- Admin Alert Settings（告警规则 / 本地通知；契约 §21） ----
// 权限：admin。响应只含安全元数据，前端不构造、不展示任何内部标识。
export async function fetchAlertRules(): Promise<AlertRulesResponseDTO> {
  return apiGet<AlertRulesResponseDTO>(`/api/v1/admin/alerts/rules`);
}

export async function updateAlertRule(
  ruleId: string,
  patch: AlertRuleUpdateDTO
): Promise<AlertRuleDTO> {
  return apiPatch<AlertRuleDTO>(`/api/v1/admin/alerts/rules/${ruleId}`, patch);
}

export async function fetchAlertNotifications(): Promise<NotificationsResponseDTO> {
  return apiGet<NotificationsResponseDTO>(`/api/v1/admin/alerts/notifications`);
}

// ---- Agent / Dify Gateway 项目 Q&A ----
// 前端绝不直连 Dify，也不拼接 Dify token / dataset_id / workflow_id。
// 一律经平台权限网关；引用层级与可见性由后端按调用人权限裁定。
export async function projectQa(
  projectId: string,
  input: { query: string; modelKey?: string }
): Promise<ProjectQaResponseDTO> {
  return apiPost<ProjectQaResponseDTO>(`/api/v1/projects/${projectId}/qa`, {
    query: input.query,
    model_key: input.modelKey ?? "system_default",
    capability: "qa",
  });
}

// ---- Admin 入库运营列表（仅安全运营元数据；admin / 治理角色，普通业务用户 403） ----
export async function fetchAdminIngest(): Promise<AdminIngestListResponseDTO> {
  return apiGet<AdminIngestListResponseDTO>(`/api/v1/admin/ingest`);
}

// ---- 企微微盘扫描（R6 Path A）。响应只含安全运营元数据，前端不构造/展示任何内部 id。 ----
// 读 configs/records：admin / boss / 咨询总监；启停 + 触发：admin。前端不复制后端权限逻辑，403 由 UI 提示。
export async function fetchWecomScanConfigs(): Promise<WecomScanConfigsResponseDTO> {
  return apiGet<WecomScanConfigsResponseDTO>(`/api/v1/admin/wecom-scan/configs`);
}

// 目标项目候选（active 项目 id + 名称）。读权限同配置读（admin / boss / 咨询总监）。
export async function fetchWecomScanProjectOptions(): Promise<WecomProjectOptionsResponseDTO> {
  return apiGet<WecomProjectOptionsResponseDTO>(`/api/v1/admin/wecom-scan/project-options`);
}

// 业务归属人候选（active 业务用户，排除纯 admin）。读权限同配置读。
export async function fetchWecomScanOwnerOptions(): Promise<WecomOwnerOptionsResponseDTO> {
  return apiGet<WecomOwnerOptionsResponseDTO>(`/api/v1/admin/wecom-scan/owner-options`);
}

// 创建扫描配置（仅 admin，配置操作人 = 审计 actor）。created_by = 业务归属人
// （task_owner_user_id，后端校验合法性写入），扫描产物任务归属该业务归属人。
export async function createWecomScanConfig(
  body: WecomScanConfigCreateBody
): Promise<WecomScanConfigDTO> {
  return apiPost<WecomScanConfigDTO>(`/api/v1/admin/wecom-scan/configs`, body);
}

// 编辑配置（仅 admin）：局部更新 name / directory_path / target_scope / target_project_id / enabled。
export async function updateWecomScanConfig(
  configId: string,
  body: WecomScanConfigUpdateBody
): Promise<WecomScanConfigDTO> {
  return apiPatch<WecomScanConfigDTO>(`/api/v1/admin/wecom-scan/configs/${configId}`, body);
}

// 仅作客户端幂等用途的 key（非密钥、不含任何用户/业务数据，不打日志）。
// 优先 randomUUID；退而用 getRandomValues；都不可用时用 timestamp + 单调计数器兜底（非伪随机）。
let idempotencyCounter = 0;
function createIdempotencyKey(): string {
  const c = typeof crypto !== "undefined" ? crypto : undefined;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID();
  }
  if (c && typeof c.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    c.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  idempotencyCounter += 1;
  return `${Date.now()}-${idempotencyCounter}`;
}

export async function triggerWecomScan(configId: string): Promise<WecomScanRecordDTO> {
  // 浏览器侧生成幂等 key（非敏感），并发同 key 由后端去重；不发送任何业务负载。
  return apiPostNoBody<WecomScanRecordDTO>(
    `/api/v1/admin/wecom-scan/configs/${configId}/scan`,
    { "Idempotency-Key": createIdempotencyKey() }
  );
}

export async function fetchWecomScanRecords(configId: string): Promise<WecomScanRecordsResponseDTO> {
  return apiGet<WecomScanRecordsResponseDTO>(`/api/v1/admin/wecom-scan/configs/${configId}/records`);
}

// ---- 企微 OAuth 启动（R6）。后端生成 state 写短时 httpOnly cookie；前端只拿 authorize_url 跳转。
// 前端绝不接触/存储 code / state / token；会话由后端 httpOnly cookie 控制。
export async function startWecomOAuth(): Promise<WecomAuthorizeDTO> {
  return apiGet<WecomAuthorizeDTO>(`/api/v1/auth/wecom/start`);
}

// ---- 人员 / 公司角色 / 项目成员关系治理（PBC-02） ----
// 读：admin / boss / 咨询总监；管理写动作：见后端权限。响应只含安全身份/治理元数据。
export async function fetchPeople(params: {
  role?: string;
  status?: string;
  q?: string;
  projectId?: string;
} = {}): Promise<PeopleListResponseDTO> {
  const qs = new URLSearchParams();
  if (params.role) qs.set("role", params.role);
  if (params.status) qs.set("status", params.status);
  if (params.q) qs.set("q", params.q);
  if (params.projectId) qs.set("project_id", params.projectId);
  return apiGet<PeopleListResponseDTO>(`/api/v1/admin/people?${qs.toString()}`);
}

export async function fetchPerson(userId: string): Promise<PersonDTO> {
  return apiGet<PersonDTO>(`/api/v1/admin/people/${userId}`);
}

export async function setCompanyRole(
  userId: string,
  body: { company_role: string; status: string }
): Promise<PersonDTO> {
  return apiPost<PersonDTO>(`/api/v1/admin/people/${userId}/company-roles`, body);
}

export async function upsertProjectMembership(
  userId: string,
  body: { project_id: string; project_role: string; status: string }
): Promise<PersonProjectMembershipDTO> {
  return apiPost<PersonProjectMembershipDTO>(
    `/api/v1/admin/people/${userId}/project-memberships`,
    body
  );
}

export async function patchProjectMembership(
  userId: string,
  membershipId: string,
  body: { project_role?: string; status?: string }
): Promise<PersonProjectMembershipDTO> {
  return apiPatch<PersonProjectMembershipDTO>(
    `/api/v1/admin/people/${userId}/project-memberships/${membershipId}`,
    body
  );
}

// ---- 权限规则配置中心（PBC-03） ----
// 读：admin / boss / 咨询总监；写：仅 boss / 咨询总监（admin 只读，consultant 无权）。
// 响应只含安全治理元数据；前端不构造、不展示任何 secret / 内部标识（后端本就不返回）。
export async function fetchPermissionRules(): Promise<PermissionRulesResponseDTO> {
  return apiGet<PermissionRulesResponseDTO>(`/api/v1/admin/permissions/rules`);
}

export async function updatePermissionRule(
  ruleId: string,
  patch: PermissionRuleUpdateDTO
): Promise<PermissionRuleDTO> {
  return apiPatch<PermissionRuleDTO>(`/api/v1/admin/permissions/rules/${ruleId}`, patch);
}

// ---- 外部 Agent 接入注册（Agent Registry，provider 中立后端兼容接口；admin 管理） ----
// 后端为 /admin/permissions/agent-whitelist（历史兼容路径）。响应绝不含 token / provider 内部标识。
export async function fetchAgentRegistry(): Promise<AgentRegistryListResponseDTO> {
  return apiGet<AgentRegistryListResponseDTO>(`/api/v1/admin/permissions/agent-whitelist`);
}

export async function setAgentRegistryEnabled(
  ruleId: string,
  enabled: boolean
): Promise<AgentRegistryRuleDTO> {
  const resp = await apiPatch<AgentRegistryUpdateResponseDTO>(
    `/api/v1/admin/permissions/agent-whitelist/${ruleId}`,
    { enabled }
  );
  return resp.rule;
}

// ---- 项目设置 / 项目成员（PBC-04） ----
// 读：admin / 治理角色 / 本项目成员；写：project_manager·coach / 治理角色。
// 响应只含安全治理元数据；企微群只回 bound + 脱敏 label（不回全文）；前端不展示任何内部标识。
export async function fetchProjectSettings(projectId: string): Promise<ProjectSettingsDTO> {
  return apiGet<ProjectSettingsDTO>(`/api/v1/projects/${projectId}/settings`);
}

export async function updateProjectSettings(
  projectId: string,
  body: ProjectSettingsUpdateDTO
): Promise<ProjectSettingsDTO> {
  return apiPatch<ProjectSettingsDTO>(`/api/v1/projects/${projectId}/settings`, body);
}

export async function fetchProjectMembers(projectId: string): Promise<ProjectMembersResponseDTO> {
  return apiGet<ProjectMembersResponseDTO>(`/api/v1/projects/${projectId}/members`);
}

export async function patchProjectMember(
  projectId: string,
  memberId: string,
  body: ProjectMemberPatchDTO
): Promise<ProjectMemberDTO> {
  return apiPatch<ProjectMemberDTO>(
    `/api/v1/projects/${projectId}/members/${memberId}`,
    body
  );
}

// ---- 个人知识写动作（PBC-05） ----
// 仅 owner 本人可操作；提交/候选支持 Idempotency-Key 防重复。响应只含安全治理元数据；
// 提交=待审核，候选=用户登记证据线索（系统不自动证明分享/客户验证真实发生）。
export async function confirmPersonalAsset(assetId: string): Promise<ConfirmAssetResponseDTO> {
  return apiPost<ConfirmAssetResponseDTO>(`/api/v1/my/knowledge/${assetId}/confirm-asset`, {});
}

export async function submitPersonalKnowledge(
  assetId: string,
  body: SubmitToProjectRequestDTO
): Promise<PersonalKnowledgeSubmissionDTO> {
  return apiPost<PersonalKnowledgeSubmissionDTO>(
    `/api/v1/my/knowledge/${assetId}/submit-to-project`,
    body,
    { "Idempotency-Key": createIdempotencyKey() }
  );
}

export async function registerPersonalKnowledgeEvidence(
  assetId: string,
  body: ValidationCandidateRequestDTO
): Promise<PersonalKnowledgeSubmissionDTO> {
  return apiPost<PersonalKnowledgeSubmissionDTO>(
    `/api/v1/my/knowledge/${assetId}/validation-evidence`,
    body,
    { "Idempotency-Key": createIdempotencyKey() }
  );
}

// ---- 原文访问申请与授权（PBC-06） ----
// 申请=业务用户且可发现该资产；审批/拒绝/撤销=项目 PM·coach / 治理角色。响应只含安全元数据。
export async function requestOriginalAccess(
  assetId: string,
  reason?: string
): Promise<CreateRequestResponseDTO> {
  return apiPost<CreateRequestResponseDTO>(
    `/api/v1/knowledge/${assetId}/original-access/request`,
    { reason: reason ?? null }
  );
}

export async function fetchOriginalAccessRequests(
  box: "mine" | "inbox" = "mine"
): Promise<RequestsListResponseDTO> {
  return apiGet<RequestsListResponseDTO>(`/api/v1/original-access/requests?box=${box}`);
}

export async function approveOriginalAccess(
  requestId: string,
  note?: string
): Promise<CreateRequestResponseDTO> {
  return apiPost<CreateRequestResponseDTO>(
    `/api/v1/original-access/requests/${requestId}/approve`,
    { note: note ?? null }
  );
}

export async function rejectOriginalAccess(
  requestId: string,
  note?: string
): Promise<CreateRequestResponseDTO> {
  return apiPost<CreateRequestResponseDTO>(
    `/api/v1/original-access/requests/${requestId}/reject`,
    { note: note ?? null }
  );
}

export async function revokeOriginalAccessGrant(
  grantId: string,
  reason?: string
): Promise<AccessGrantDTO> {
  return apiPost<AccessGrantDTO>(
    `/api/v1/original-access/grants/${grantId}/revoke`,
    { reason: reason ?? null }
  );
}
