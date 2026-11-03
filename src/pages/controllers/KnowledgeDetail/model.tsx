import { ApiError } from "../../../api/http";
import type {
  AiAccessLevel,
  AssetStatus,
  ConfidentialityLevel,
  FrontVisibility,
} from "../../../types/knowledge";
export const visibilityLabel: Record<FrontVisibility, string> = {
  public: "公开",
  "project-only": "项目内",
  confidential: "机密",
};

export const confidentialityLabelMap: Record<ConfidentialityLevel, string> = {
  L1: "L1 公开级",
  L2: "L2 内部参考级",
  L3: "L3 受限级",
  L4: "L4 商业秘密级",
  L5: "L5 严格商业秘密级",
};

export const aiAccessLabelMap: Record<AiAccessLevel, string> = {
  A1: "可用于问答",
  A2: "保护后用于问答",
  A3: "仅摘要可用",
  A4: "不用于问答",
};

export const assetStatusLabel: Record<AssetStatus, string> = {
  active: "已入库",
  needs_update: "需要处理",
  deprecated: "已停用",
  archived: "已归档",
};

export const assetStatusCls: Record<AssetStatus, string> = {
  active: "asset-status-active",
  needs_update: "asset-status-needs-update",
  deprecated: "asset-status-deprecated",
  archived: "asset-status-archived",
};

export const indexStatusLabel: Record<string, string> = {
  indexed: "索引完成，可检索",
  indexing: "索引处理中",
  index_failed: "索引未完成，可恢复",
  skipped: "此前未进入索引",
  not_indexed: "已入库，等待索引",
};

export const scopeLabel: Record<string, string> = {
  personal: "个人范围",
  project: "项目范围",
  company: "公司范围",
};

export const lifecycleEventLabel: Record<string, string> = {
  archive_warning: "归档预警",
  archive_candidate: "归档候选",
  archived: "资产已归档",
  reenable_requested: "申请重新启用",
  reenabled: "资产已重新启用",
  status_changed: "资产状态已变更",
};

export const hasText = (value: string | null | undefined) => Boolean(value && value.trim());

export function safeActionError(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}
