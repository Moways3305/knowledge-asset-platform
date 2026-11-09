// 知识资产列表与工作台共用的展示标签，不参与业务权限判定。
import type { AssetStatus, KnowledgeScope } from "../types/knowledge";

export const scopeLabels: Record<KnowledgeScope, string> = {
  personal: "个人知识",
  project: "项目知识",
  company: "公司知识",
};

export const assetStatusLabel: Record<AssetStatus, string> = {
  active: "活跃",
  needs_update: "待更新",
  deprecated: "已废弃",
  archived: "已归档",
};
