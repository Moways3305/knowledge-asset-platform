import { ApiError } from "../../../api/http";
import type { ModelDTO, WeknoraDefaultModelsDTO } from "../../../types/weknoraAdmin";
export type DrawerKind = "external" | "weknora" | "knowledge" | "migration" | null;

export const scopeLabel: Record<string, string> = {
  company: "公司库",
  project: "项目库",
  personal: "个人库",
};

export const mappingStatusLabel: Record<string, string> = {
  active: "已初始化",
  init_failed: "初始化异常",
  migrating: "迁移中",
};

export const emptyDefaults: WeknoraDefaultModelsDTO = {
  embedding: null,
  rerank: null,
  chat: null,
  multimodal: null,
  updated_at: null,
};

export function kbUpdateErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    const messages: Record<string, string> = {
      weknora_kb_config_rejected: "知识库配置被底座拒绝，请检查所选模型是否兼容。",
      weknora_model_type_mismatch: "所选模型类型与配置项不匹配。",
      weknora_model_slot_unsupported: "当前底座不支持更新该模型。",
      weknora_kb_chat_model_missing: "请先选择底座兼容 LLM。",
    };
    if (caught.deniedReason && messages[caught.deniedReason]) return messages[caught.deniedReason];
  }
  return "知识库配置未保存，请检查模型状态后重试。";
}

export function slotName(slot: { name: string | null } | null): string {
  return slot?.name?.trim() || "未设置";
}

export function ModelSelect({
  label,
  value,
  type,
  models,
  onChange,
  optional = false,
}: {
  label: string;
  value: string;
  type: string;
  models: ModelDTO[];
  onChange: (value: string) => void;
  optional?: boolean;
}) {
  return (
    <label className="ws-form-field">
      <span className="ws-form-label">{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{optional ? "暂不设置" : "请选择模型"}</option>
        {models
          .filter((model) => model.type === type && model.enabled)
          .map((model) => (
            <option key={model.model_ref} value={model.model_ref}>
              {model.name}
            </option>
          ))}
      </select>
    </label>
  );
}
