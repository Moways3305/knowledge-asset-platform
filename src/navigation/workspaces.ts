import { can, type Capabilities, type Capability } from "../auth/permissions";

export type WorkspaceKey = "work" | "knowledge" | "project" | "approval" | "admin" | "account";
export interface WorkspaceEntry {
  to: string;
  label: string;
  cap: Capability;
  section?: string;
}

// Presentation grouping only. Each entry retains its existing route capability.
export const knowledgeEntries: WorkspaceEntry[] = [
  { to: "/knowledge", label: "知识资产库", cap: can.viewKnowledge },
  { to: "/my/knowledge", label: "我的知识", cap: can.viewMyKnowledge },
  { to: "/knowledge-maintenance", label: "知识维护", cap: can.viewKnowledge },
  { to: "/upload", label: "上传资料", cap: can.viewUpload },
];

export const approvalEntries: WorkspaceEntry[] = [
  { to: "/review", label: "升级审核", cap: can.viewReview },
  { to: "/review/completed", label: "已处理审核", cap: can.viewReview },
  { to: "/original-access", label: "原文访问审批", cap: can.viewOriginalAccess },
  { to: "/original-access?box=mine", label: "我的原文申请", cap: can.viewOriginalAccess },
  { to: "/original-access/grants", label: "原文授权记录", cap: can.viewOriginalAccess },
];

export const managementEntries: WorkspaceEntry[] = [
  {
    to: "/company-governance",
    label: "公司库治理",
    cap: can.viewCompanyKnowledge,
    section: "组织与知识",
  },
  { to: "/admin/people", label: "人员权限", cap: can.viewPeople, section: "组织与知识" },
  { to: "/admin/naming-rules", label: "目录治理", cap: can.viewNamingRules, section: "组织与知识" },
  { to: "/admin/ingest", label: "入库管理", cap: can.viewIngestAdmin, section: "运行与接入" },
  { to: "/admin/wecom-scan", label: "微盘扫描", cap: can.viewWecomScan, section: "运行与接入" },
  { to: "/admin/weknora-models", label: "模型配置", cap: can.viewModels, section: "运行与接入" },
  { to: "/admin/audit", label: "审计日志", cap: can.viewAudit, section: "安全与规则" },
  {
    to: "/admin/auth-security",
    label: "登录安全",
    cap: can.viewAuthSecurity,
    section: "安全与规则",
  },
  { to: "/admin/alert-settings", label: "告警设置", cap: can.viewAlerts, section: "安全与规则" },
  { to: "/admin/permissions", label: "权限规则", cap: can.viewPermissions, section: "安全与规则" },
  {
    to: "/admin/release-notes",
    label: "版本日志管理",
    cap: can.manageReleaseNotes,
    section: "系统内容",
  },
];

export function permittedEntries(entries: WorkspaceEntry[], capabilities: Capabilities) {
  return entries.filter((entry) => entry.cap(capabilities));
}

export function workspaceForPath(pathname: string): WorkspaceKey {
  if (pathname.startsWith("/admin") || pathname === "/company-governance") return "admin";
  if (pathname === "/projects" || pathname.startsWith("/project/")) return "project";
  if (pathname.startsWith("/review") || pathname.startsWith("/original-access")) return "approval";
  if (pathname.startsWith("/knowledge") || pathname === "/my/knowledge" || pathname === "/upload")
    return "knowledge";
  return pathname === "/" ? "work" : "account";
}

export const workspaceLabels: Record<WorkspaceKey, string> = {
  work: "工作台",
  knowledge: "知识库",
  project: "项目空间",
  approval: "审批中心",
  admin: "管理中心",
  account: "帮助与账号",
};

const utilityTitles: Record<string, string> = {
  "/": "我的工作",
  "/help": "帮助中心",
  "/release-notes": "更新日志",
  "/my/workbuddy": "个人工具接入",
  "/mcp-authorize": "工具授权",
};

export function pageTitle(pathname: string) {
  if (/^\/project\/[^/]+\/settings(?:\/|$)/.test(pathname)) return "项目设置";
  if (/^\/project\/[^/]+\/knowledge(?:\/|$)/.test(pathname)) return "项目资料";
  if (pathname === "/projects") return "我的项目";
  if (pathname.startsWith("/project/")) return "项目概览";
  if (/^\/knowledge\/[^/]+/.test(pathname)) return "资料详情";
  return (
    [...managementEntries, ...knowledgeEntries, ...approvalEntries].find(
      (entry) => entry.to === pathname,
    )?.label ??
    utilityTitles[pathname] ??
    "知识资产平台"
  );
}
