// 管理与运营领域：索引运维 / 登录风控 / 会话运维 / 企微身份对账 / WeKnora 模型配置 /
// 审计 / 告警 / 人员与角色 / 权限规则 / 外部 Agent 注册 / 企微微盘扫描 / 企微 OAuth 启动。
// 所有响应只含安全运营/治理元数据；前端不构造、不展示任何内部标识（后端本就不返回）。
import { apiGet, apiPost, apiPatch, apiPut, apiPostNoBody, createIdempotencyKey } from "./http";
import type {
  IndexingJobListResponseDTO,
  IndexingJobSummaryDTO,
  IndexingReparseRequestDTO,
  IndexingRetryRequestDTO,
  OpsIndexingDTO,
} from "../types/ops";
import type { AuthSecurityOverviewDTO, AuthUnlockResponseDTO } from "../types/authSecurity";
import type { SessionRevokeResponseDTO } from "../types/sessionOps";
import type { WecomReconcileResponseDTO } from "../types/wecomIdentity";
import type { KbConfigDTO, KbInitUpdateRequestDTO, ModelDTO } from "../types/weknoraAdmin";
import type { AuditListResponseDTO, MarkProcessedResponseDTO } from "../types/audit";
import type {
  AlertRuleDTO,
  AlertRulesResponseDTO,
  AlertRuleUpdateDTO,
  NotificationsResponseDTO,
} from "../types/alert";
import type { PeopleListResponseDTO, PersonDTO, PersonProjectMembershipDTO } from "../types/people";
import type {
  AgentRegistryListResponseDTO,
  AgentRegistryRuleDTO,
  AgentRegistryUpdateResponseDTO,
  PermissionRuleDTO,
  PermissionRulesResponseDTO,
  PermissionRuleUpdateDTO,
} from "../types/permission";
import type {
  WecomAuthorizeDTO,
  WecomDriveDirectoriesResponseDTO,
  WecomDriveSpacesResponseDTO,
  WecomOwnerOptionsResponseDTO,
  WecomProjectOptionsResponseDTO,
  WecomScanConfigCreateBody,
  WecomScanConfigDTO,
  WecomScanConfigsResponseDTO,
  WecomScanConfigUpdateBody,
  WecomScanRecordDTO,
  WecomScanRecordsResponseDTO,
} from "../types/wecom";

// ---- 索引运维 ----
// 注：ops 路由不带 /api/v1 前缀（与 /admin/ops/summary 一致）。
// 索引运维面板。admin 或业务治理角色可看安全计数 + 最近失败列表。
export async function fetchOpsIndexing(): Promise<OpsIndexingDTO> {
  return apiGet<OpsIndexingDTO>(`/admin/ops/indexing`);
}

// 批量 retry-index。仅 admin / 业务治理角色；返回入队后的安全 job 摘要。
export async function triggerIndexingRetry(
  body: IndexingRetryRequestDTO,
): Promise<IndexingJobSummaryDTO> {
  return apiPost<IndexingJobSummaryDTO>(`/admin/ops/indexing/retry`, body);
}

// 显式 reparse。对已进底座但解析异常的资产入队重新解析。
export async function triggerIndexingReparse(
  body: IndexingReparseRequestDTO,
): Promise<IndexingJobSummaryDTO> {
  return apiPost<IndexingJobSummaryDTO>(`/admin/ops/indexing/reparse`, body);
}

// 最近索引运维作业列表。仅安全统计与安全错误文案。
export async function fetchIndexingJobs(): Promise<IndexingJobListResponseDTO> {
  return apiGet<IndexingJobListResponseDTO>(`/admin/ops/indexing/jobs`);
}

// ---- 登录风控运维 ----
// admin-only：近期登录风控聚合 + 手动解除 identifier 短时锁定。
// 仅安全字段（不可逆 hash 前缀 / 计数 / 安全用户元数据）；解锁 POST 受 CSRF 保护。
export async function fetchAuthSecurityOverview(params?: {
  windowMinutes?: number;
  limit?: number;
  result?: string;
}): Promise<AuthSecurityOverviewDTO> {
  const q = new URLSearchParams();
  if (params?.windowMinutes != null) q.set("window_minutes", String(params.windowMinutes));
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.result) q.set("result", params.result);
  const qs = q.toString();
  return apiGet<AuthSecurityOverviewDTO>(`/admin/ops/auth-security${qs ? `?${qs}` : ""}`);
}

export async function unlockAuthLockout(body: {
  user_id?: string;
  identifier_hash_prefix?: string;
  reason?: string;
}): Promise<AuthUnlockResponseDTO> {
  return apiPost<AuthUnlockResponseDTO>(`/admin/ops/auth-security/unlock`, body);
}

// ---- 平台会话运维 ----
// admin-only：强制撤销某用户会话；仅返回安全计数和状态。
export async function revokeUserSessions(
  userId: string,
  body?: { reason?: string; preserve_current_session?: boolean },
): Promise<SessionRevokeResponseDTO> {
  return apiPost<SessionRevokeResponseDTO>(
    `/admin/ops/sessions/users/${userId}/revoke`,
    body ?? {},
  );
}

// ---- 企微身份对账 ----
// admin-only：失效企微成员 → 停用平台用户 + 撤销会话。仅安全计数 + 安全状态；CSRF 自动附带。
export async function reconcileWecomIdentity(body: {
  user_id?: string;
  dry_run?: boolean;
}): Promise<WecomReconcileResponseDTO> {
  return apiPost<WecomReconcileResponseDTO>(`/admin/ops/wecom-identity/reconcile`, body);
}

// ---- WeKnora 模型配置中心 ----
// admin-only；不传/收 api_key/base_url 真实值，model 选择用 model_ref。
const WK = "/api/v1/admin/weknora";

export async function fetchWeknoraModels(type?: string): Promise<ModelDTO[]> {
  const qs = type ? `?type=${encodeURIComponent(type)}` : "";
  return (await apiGet<{ items: ModelDTO[] }>(`${WK}/models${qs}`)).items;
}

export async function fetchWeknoraKbConfigs(): Promise<KbConfigDTO[]> {
  return (await apiGet<{ items: KbConfigDTO[] }>(`${WK}/kb-configs`)).items;
}

export async function updateWeknoraKbInit(
  mappingId: string,
  body: KbInitUpdateRequestDTO,
): Promise<{ mapping_id: string; mapping_status: string; updated: boolean }> {
  return apiPut(`${WK}/kb-configs/${mappingId}/initialization`, body);
}

// ---- 审计日志查询 / trace / 标记处理 ----
// 权限：admin 或 boss / 咨询总监；普通业务用户 403。响应按角色脱敏。
export async function fetchAudit(
  params: {
    logType?: string;
    action?: string;
    severity?: string;
    isProcessed?: boolean;
    traceId?: string;
    pageSize?: number;
  } = {},
): Promise<AuditListResponseDTO> {
  const qs = new URLSearchParams();
  if (params.logType) qs.set("log_type", params.logType);
  if (params.action) qs.set("action", params.action);
  if (params.severity) qs.set("severity", params.severity);
  if (params.isProcessed !== undefined) qs.set("is_processed", String(params.isProcessed));
  if (params.traceId) qs.set("trace_id", params.traceId);
  qs.set("page_size", String(params.pageSize ?? 200));
  return apiGet<AuditListResponseDTO>(`/api/v1/admin/audit?${qs.toString()}`);
}

export async function markAuditProcessed(eventId: string): Promise<MarkProcessedResponseDTO> {
  return apiPostNoBody<MarkProcessedResponseDTO>(`/api/v1/admin/audit/${eventId}/mark-processed`);
}

// ---- 告警规则 / 本地通知 ----
// 权限：admin。响应只含安全元数据。
export async function fetchAlertRules(): Promise<AlertRulesResponseDTO> {
  return apiGet<AlertRulesResponseDTO>(`/api/v1/admin/alerts/rules`);
}

export async function updateAlertRule(
  ruleId: string,
  patch: AlertRuleUpdateDTO,
): Promise<AlertRuleDTO> {
  return apiPatch<AlertRuleDTO>(`/api/v1/admin/alerts/rules/${ruleId}`, patch);
}

export async function fetchAlertNotifications(): Promise<NotificationsResponseDTO> {
  return apiGet<NotificationsResponseDTO>(`/api/v1/admin/alerts/notifications`);
}

// ---- 人员 / 公司角色 / 项目成员关系治理 ----
// 读：admin / boss / 咨询总监；管理写动作：见后端权限。响应只含安全身份/治理元数据。
export async function fetchPeople(
  params: {
    role?: string;
    status?: string;
    q?: string;
    projectId?: string;
  } = {},
): Promise<PeopleListResponseDTO> {
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
  body: { company_role: string; status: string },
): Promise<PersonDTO> {
  return apiPost<PersonDTO>(`/api/v1/admin/people/${userId}/company-roles`, body);
}

// admin 设置 / 重置用户密码。password 仅上送，响应不回显。
export async function setUserPassword(
  userId: string,
  password: string,
): Promise<{
  ok: boolean;
  user_id: string;
  password_set: boolean;
  password_set_at: string | null;
}> {
  return apiPost(`/api/v1/admin/people/${userId}/password`, { password });
}

// 启用 / 停用用户。停用联动撤销其平台会话。
export async function setUserStatus(
  userId: string,
  status: "active" | "inactive",
  reason?: string,
): Promise<PersonDTO> {
  return apiPost<PersonDTO>(`/api/v1/admin/people/${userId}/status`, { status, reason });
}

export async function upsertProjectMembership(
  userId: string,
  body: { project_id: string; project_role: string; status: string },
): Promise<PersonProjectMembershipDTO> {
  return apiPost<PersonProjectMembershipDTO>(
    `/api/v1/admin/people/${userId}/project-memberships`,
    body,
  );
}

export async function patchProjectMembership(
  userId: string,
  membershipId: string,
  body: { project_role?: string; status?: string },
): Promise<PersonProjectMembershipDTO> {
  return apiPatch<PersonProjectMembershipDTO>(
    `/api/v1/admin/people/${userId}/project-memberships/${membershipId}`,
    body,
  );
}

// ---- 权限规则配置中心 ----
// 读：admin / boss / 咨询总监；写：仅 boss / 咨询总监（admin 只读，consultant 无权）。
// 响应只含安全治理元数据；前端不构造、不展示任何 secret / 内部标识（后端本就不返回）。
export async function fetchPermissionRules(): Promise<PermissionRulesResponseDTO> {
  return apiGet<PermissionRulesResponseDTO>(`/api/v1/admin/permissions/rules`);
}

export async function updatePermissionRule(
  ruleId: string,
  patch: PermissionRuleUpdateDTO,
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
  enabled: boolean,
): Promise<AgentRegistryRuleDTO> {
  const resp = await apiPatch<AgentRegistryUpdateResponseDTO>(
    `/api/v1/admin/permissions/agent-whitelist/${ruleId}`,
    { enabled },
  );
  return resp.rule;
}

// ---- 企微微盘扫描（Path A） ----
// 响应只含安全运营元数据，前端不构造/展示任何内部 id。
// 读 configs/records：admin / boss / 咨询总监；启停 + 触发：admin。前端不复制后端权限逻辑，403 由 UI 提示。
export async function fetchWecomScanConfigs(): Promise<WecomScanConfigsResponseDTO> {
  return apiGet<WecomScanConfigsResponseDTO>(`/api/v1/admin/wecom-scan/configs`);
}

// 微盘目录浏览（admin-only）。只回安全选择元数据，未配置 → 503。
export async function fetchWecomDriveSpaces(): Promise<WecomDriveSpacesResponseDTO> {
  return apiGet<WecomDriveSpacesResponseDTO>(`/api/v1/admin/wecom-scan/drive/spaces`);
}

export async function fetchWecomDriveDirectories(
  spaceRef: string,
  parentRef?: string,
): Promise<WecomDriveDirectoriesResponseDTO> {
  const qs = new URLSearchParams({ space_ref: spaceRef });
  if (parentRef) qs.set("parent_ref", parentRef);
  return apiGet<WecomDriveDirectoriesResponseDTO>(
    `/api/v1/admin/wecom-scan/drive/directories?${qs.toString()}`,
  );
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
  body: WecomScanConfigCreateBody,
): Promise<WecomScanConfigDTO> {
  return apiPost<WecomScanConfigDTO>(`/api/v1/admin/wecom-scan/configs`, body);
}

// 编辑配置（仅 admin）：局部更新 name / directory_path / target_scope / target_project_id / enabled。
export async function updateWecomScanConfig(
  configId: string,
  body: WecomScanConfigUpdateBody,
): Promise<WecomScanConfigDTO> {
  return apiPatch<WecomScanConfigDTO>(`/api/v1/admin/wecom-scan/configs/${configId}`, body);
}

export async function triggerWecomScan(configId: string): Promise<WecomScanRecordDTO> {
  // 浏览器侧生成幂等 key（非敏感），并发同 key 由后端去重；不发送任何业务负载。
  return apiPostNoBody<WecomScanRecordDTO>(`/api/v1/admin/wecom-scan/configs/${configId}/scan`, {
    "Idempotency-Key": createIdempotencyKey(),
  });
}

export async function fetchWecomScanRecords(
  configId: string,
): Promise<WecomScanRecordsResponseDTO> {
  return apiGet<WecomScanRecordsResponseDTO>(
    `/api/v1/admin/wecom-scan/configs/${configId}/records`,
  );
}

// ---- 企微 OAuth 启动 ----
// 后端生成 state 写短时 httpOnly cookie；前端只拿 authorize_url 跳转。
// 前端绝不接触/存储 code / state / token；会话由后端 httpOnly cookie 控制。
export type WecomOAuthMode = "client" | "web_qr";

export async function startWecomOAuth(mode: WecomOAuthMode = "client"): Promise<WecomAuthorizeDTO> {
  return apiGet<WecomAuthorizeDTO>(`/api/v1/auth/wecom/start?mode=${mode}`);
}
