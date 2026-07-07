// 知识资产展示用的中文标签与小工具。原先散落在 KnowledgeListPage 内，提取到此
// 供 KnowledgeCard 等组件与页面共享，避免重复维护标签表。纯展示逻辑，不含业务判定。
import type { AssetStatus, FrontVisibility, KnowledgeScope } from "../types/knowledge";

export const scopeLabels: Record<KnowledgeScope, string> = {
  personal: "个人知识",
  project: "项目知识",
  company: "公司知识",
};

export const assetTypeLabel: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};

export const visibilityLabel: Record<FrontVisibility, string> = {
  public: "公开",
  "project-only": "项目内",
  confidential: "机密",
};

export const assetStatusLabel: Record<AssetStatus, string> = {
  active: "活跃",
  needs_update: "待更新",
  deprecated: "已废弃",
  archived: "已归档",
};

// 检索意图（后端分类结果）中文标签。
export const intentLabel: Record<string, string> = {
  search: "查找",
  qa: "问答",
  generate: "生成",
  recommend: "推荐",
  check: "检查",
  summarize: "总结",
};

// 三层访问模型标签（发现 / 摘要 / 原文）。
export const accessLayerLabel: Record<string, string> = {
  discovery: "发现层",
  summary: "摘要层",
  original: "原文层",
};

// 平台级检索索引状态（小角标）。indexed 为常态，不展示角标。
export const indexStatusLabel: Record<string, string> = {
  indexing: "索引中",
  index_failed: "索引失败",
  skipped: "未索引",
  not_indexed: "待索引",
};

export const zoneLabel = (zone: string) =>
  zone === "asset" ? "资产区" : zone === "material" ? "资料区" : zone;

// 档案脊颜色：搜索卡按真实保密级（L1–L5）；浏览卡按可见性近似（不虚构保密级）。
export const spineByLevel = (level: string) => `conf-${level}`;
export const spineByVisibility = (v: FrontVisibility) =>
  v === "public" ? "conf-L1" : v === "confidential" ? "conf-L4" : "conf-L2";

// 浏览卡检索索引状态 → 角标修饰类。
export const indexBadgeClass = (status: string | null) =>
  status === "indexing"
    ? "idx-indexing"
    : status === "index_failed"
      ? "idx-failed"
      : status === "skipped"
        ? "idx-skipped"
        : "idx-pending";

export const confidenceText = (c: number | null) => {
  if (c == null) return "—";
  const pct = Math.round(c * 100);
  const level = c >= 0.9 ? "高" : c >= 0.8 ? "中" : "低";
  return `${level}（${pct}%）`;
};
