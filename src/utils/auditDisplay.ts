// 审计展示中文化。
//
// 后端审计事实保持机器可读（action / target_type / log_type / snapshot 原始英文枚举不变，
// 用于筛选、接口稳定、排障）。此处只把高频枚举翻译为中文供展示；未映射的值一律回退原值，
// 绝不丢弃、绝不臆造错误中文。原始 action / trace_id 仍由页面以小字 / tooltip 保留可排障。

import type { AuditEventDTO } from "../types/audit";

const ACTION_LABELS: Record<string, string> = {
  // 入库
  "ingest.task_created": "创建入库任务",
  "ingest.ai_extracted": "完成文本抽取与内容建议",
  "ingest.confirmed": "确认入库",
  "ingest.weknora_indexed": "写入知识底座",
  "ingest.failed": "入库失败",
  // 预览
  "preview.issued": "签发预览凭证",
  "preview.used": "使用预览凭证",
  "preview.denied": "预览被拒",
  // 知识 / 检索
  "knowledge.searched": "语义检索",
  "knowledge.asset_deleted": "删除知识资产",
  // 生命周期
  "lifecycle.archive_warning": "归档预警",
  "lifecycle.archive_candidate": "生成归档候选",
  "lifecycle.archived": "归档资产",
  "lifecycle.reenable_requested": "发起重新启用",
  "lifecycle.reenabled": "重新启用资产",
  "asset.status_changed": "资产状态变更",
  // 项目
  "project.created": "创建项目知识库",
  "project.settings_updated": "更新项目设置",
  "project.member_updated": "更新项目成员",
  // 原文访问
  "access.original_requested": "申请原文访问",
  "access.original_approved": "批准原文访问",
  "access.original_rejected": "拒绝原文访问",
  "access.original_grant_revoked": "撤销原文授权",
  // 个人知识 / 审核
  "personal.asset_confirmed": "确认个人知识资产",
  "personal.submitted_to_project": "提交到项目",
  "review.candidate_created": "创建资产候选",
  "review.approved": "审核通过",
  "review.rejected": "审核驳回",
  // 微盘扫描
  "wecom_scan.config_created": "创建微盘扫描配置",
  "wecom_scan.config_updated": "更新微盘扫描配置",
  "wecom_scan.triggered": "触发微盘扫描",
  "wecom_scan.started": "微盘扫描开始",
  "wecom_scan.completed": "微盘扫描完成",
  "wecom_scan.failed": "微盘扫描失败",
  // Agent 网关
  "agent.called": "调用外部 Agent",
  "agent.allowed": "Agent 调用放行",
  "agent.denied": "Agent 调用被拒",
  "agent.a4_original_denied": "A4 原文调用被拒",
  // 配置治理
  "config.permission_rule_updated": "更新权限规则",
  "config.alert_rule_updated": "更新告警规则",
  "config.agent_registry_updated": "更新 Agent 注册",
  "config.people_company_role_updated": "更新公司角色",
  "config.people_project_membership_updated": "更新项目成员关系",
  // admin 边界 / 通知
  "admin.business_denied": "系统身份业务操作被拒",
  "notification.sent": "下发通知",
  // 登录
  "login.success": "登录成功",
  "login.failed": "登录失败",
  "login.logout": "登出",
  "login.locked": "登录暂时锁定",
  "login.rate_limited": "登录限流",
  // 审计处理
  "audit.exception_processed": "标记异常已处理",
};

const TARGET_TYPE_LABELS: Record<string, string> = {
  ingest_task: "入库任务",
  knowledge_asset: "知识资产",
  knowledge_search: "知识检索",
  preview_credential: "预览凭证",
  project: "项目",
  project_member: "项目成员",
  wecom_scan_config: "微盘扫描配置",
  wecom_scan_record: "微盘扫描记录",
  original_access_request: "原文访问申请",
  access_grant: "原文授权",
  agent_call: "Agent 调用",
  permission_rule: "权限规则",
  alert_rule: "告警规则",
  review_task: "审核任务",
  user: "用户",
};

const LOG_TYPE_LABELS: Record<string, string> = {
  operation: "操作",
  exception: "异常",
  login: "登录",
};

// snapshot / extra 的 key 中文标签。
const KEY_LABELS: Record<string, string> = {
  status: "状态",
  source: "来源",
  target_scope: "目标知识库",
  scope: "范围",
  zone: "分区",
  confidentiality_level: "保密级别",
  ai_access_level: "AI 调用级别",
  ingest_task_id: "入库任务",
  asset_id: "资产",
  project_id: "项目",
  target_project_id: "目标项目",
  task_owner_user_id: "业务归属人",
  error_code: "错误码",
  denied_reason: "拒绝原因",
  preview_type: "预览类型",
  credential_fingerprint: "凭证指纹",
  submission_type: "提交类型",
  review_task_id: "审核任务",
  name: "名称",
  enabled: "启用",
  scope_type: "范围类型",
  parse_status: "解析状态",
  is_duplicate: "是否重复",
  card_count: "结果数",
  intent: "意图",
  answered: "已生成答案",
  channel: "渠道",
  scan_record_id: "扫描记录",
  stage: "阶段",
  reason: "原因",
  revoked_grants: "撤销授权数",
  cancelled_requests: "取消申请数",
  weknora_delete_attempted: "已尝试索引删除",
  weknora_delete_succeeded: "索引删除成功",
  directory_path_set: "已设置目录",
  directory_path_changed: "目录已变更",
};

// 常见枚举 value 的中文标签（跨 key 通用）。
const VALUE_LABELS: Record<string, string> = {
  // 状态
  processing: "处理中",
  pending: "待处理",
  pending_confirmation: "待确认",
  waiting_review: "待审核",
  completed: "已完成",
  failed: "失败",
  running: "进行中",
  active: "活跃",
  archived: "已归档",
  deprecated: "已废弃",
  deleted: "已删除",
  revoked: "已撤销",
  cancelled: "已取消",
  approved: "已批准",
  rejected: "已拒绝",
  // scope
  personal: "个人知识库",
  project: "项目知识库",
  company: "公司知识库",
  all: "全部",
  // zone
  material: "资料区",
  asset: "资产区",
  // 来源
  path_b_upload: "本地上传",
  path_a_wecom: "企微微盘",
  manual: "手动",
  // 常见 denied_reason
  admin_business_permission_denied: "系统身份无业务权",
  project_membership_required: "需项目成员身份",
  original_requires_request: "原文需申请",
  knowledge_delete_forbidden: "无删除权限",
  wecom_scan_owner_invalid: "扫描归属人失效",
  // 布尔
  true: "是",
  false: "否",
};

export function auditActionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export function auditTargetTypeLabel(targetType?: string | null): string {
  if (!targetType) return "—";
  return TARGET_TYPE_LABELS[targetType] ?? targetType;
}

export function auditLogTypeLabel(logType: string): string {
  return LOG_TYPE_LABELS[logType] ?? logType;
}

function _keyLabel(key: string): string {
  return KEY_LABELS[key] ?? key;
}

// 单个 value 的中文化：枚举命中→中文；布尔→是/否；对象→JSON；否则原值。
export function auditValueLabel(_key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") return JSON.stringify(value);
  const s = String(value);
  return VALUE_LABELS[s] ?? s;
}

// 把 after_snapshot（无则 denied_reason）压成一行中文摘要，未映射回退原值。
export function auditSnapshotSummary(event: AuditEventDTO): string {
  const snap = event.after_snapshot ?? event.extra;
  if (snap && Object.keys(snap).length > 0) {
    return Object.entries(snap)
      .map(([k, v]) => `${_keyLabel(k)}：${auditValueLabel(k, v)}`)
      .join(" · ");
  }
  if (event.denied_reason)
    return `拒绝原因：${auditValueLabel("denied_reason", event.denied_reason)}`;
  return "—";
}

// 登录结果 / 原因中文摘要（登录 tab 用）。
export function auditLoginSummary(event: AuditEventDTO): string {
  if (event.denied_reason) return `原因：${auditValueLabel("denied_reason", event.denied_reason)}`;
  return auditSnapshotSummary(event);
}
