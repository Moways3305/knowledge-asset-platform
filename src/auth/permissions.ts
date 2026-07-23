// 前端权限派生：把 /auth/me 身份上下文归一为一组能力位（Capabilities），
// 供左侧导航过滤与页面级守卫复用。后端始终是权威鉴权方——这里只做体验收口
// （隐藏无意义入口、避免无权页面先发请求再报「加载失败」），不替代后端校验。
//
// 能力位与后端各端点的真实放行条件对齐（见 backend/app/services 与 api 的角色守卫），
// 而非按「所有管理后台都给登录用户看」的粗口径。
import type { AuthMeVM } from "../api/auth";

// 公司角色 / 项目角色技术 key（与后端 enums 一致）。
const ADMIN_ROLE = "admin";
const BOSS_ROLE = "boss";
const CONSULTING_DIRECTOR_ROLE = "consulting_director";
const PROJECT_MANAGER_ROLE = "project_manager";

export interface Capabilities {
  // 系统管理员（公司角色含 admin）。admin 是系统身份，不因此拥有业务原文权限。
  isAdmin: boolean;
  isBoss: boolean;
  isConsultingDirector: boolean;
  // 业务用户（active 业务公司角色：boss / consulting_director / consultant）。
  isBusinessUser: boolean;
  // 业务治理角色（boss / consulting_director），等价于后端 can_discover_l5。
  isGovernance: boolean;
  // 至少属于一个 active 项目。
  hasProject: boolean;
  // 在某个 active 项目中担任项目经理。
  isProjectManager: boolean;
}

export function deriveCapabilities(me: AuthMeVM | null): Capabilities {
  if (!me) {
    return {
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: false,
      isGovernance: false,
      hasProject: false,
      isProjectManager: false,
    };
  }
  return {
    isAdmin: me.activeCompanyRole === ADMIN_ROLE,
    isBoss: me.activeCompanyRole === BOSS_ROLE,
    isConsultingDirector: me.activeCompanyRole === CONSULTING_DIRECTOR_ROLE,
    isBusinessUser: me.isBusinessUser,
    isGovernance: me.canDiscoverL5,
    hasProject: me.projects.length > 0,
    isProjectManager: me.projects.some((p) => p.projectRole === PROJECT_MANAGER_ROLE),
  };
}

export type Capability = (c: Capabilities) => boolean;

const always: Capability = () => true;
const adminOnly: Capability = (c) => c.isAdmin;
// 治理运营类入口：系统 admin（系统运维）或业务治理角色（boss / 咨询总监）可读。
const adminOrGovernance: Capability = (c) => c.isAdmin || c.isGovernance;
const businessOnly: Capability = (c) => c.isBusinessUser;

// 各导航 / 路由入口的可见性谓词。命名按业务入口，集中在此以便导航与守卫共用同一判定。
export const can = {
  viewHome: always,
  viewHelp: always,

  // 业务功能：业务用户可见；纯 admin / 匿名不显示业务知识入口。
  viewKnowledge: businessOnly,
  // 公司知识库入口：仅治理角色（boss / 咨询总监）可见。
  viewCompanyKnowledge: (c: Capabilities) => c.isBoss || c.isConsultingDirector,
  viewMyKnowledge: businessOnly,
  viewUpload: businessOnly,
  viewReview: businessOnly,
  viewOriginalAccess: businessOnly,
  // 项目看板 / 设置：项目成员可访问；治理角色（总经理/咨询总监）具有跨项目监管及创建权限。
  viewProject: (c: Capabilities) => c.hasProject || c.isGovernance,

  // 管理后台（与后端各端点真实放行条件对齐）：
  // 入库管理：list_admin_ingest → admin 或治理角色。
  viewIngestAdmin: adminOrGovernance,
  // 微盘扫描：读配置/记录 → admin 或治理角色（启停/触发仍需 admin，由页面内部区分）。
  viewWecomScan: adminOrGovernance,
  // 模型配置：纯系统 admin。
  viewModels: adminOnly,
  // 审计日志：admin 或 boss / 咨询总监（按角色脱敏，页面内部区分视图档位）。
  viewAudit: adminOrGovernance,
  // 登录风控：admin-only 运维面板。
  viewAuthSecurity: adminOnly,
  // 告警设置：三个告警 API 均要求 admin。
  viewAlerts: adminOnly,
  // 权限规则：admin / 治理角色可读（写入仅治理角色，由页面内部区分）。
  viewPermissions: adminOrGovernance,
  // 人员治理：admin 不可见；仅总经理 / 咨询总监。
  viewPeople: (c: Capabilities) => c.isGovernance,
} as const;
