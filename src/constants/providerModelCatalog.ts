// 前端模型目录：用于修正 WeKnora 供应商描述中的过时模型名，并在新增
// WeKnora 模型时为"模型名称"提供自动补全建议（仍可手动输入任意模型）。
//
// 仅覆盖本项目主要使用的厂商（DeepSeek / Moonshot-Kimi / 阿里云 Qwen / 智谱 GLM）；
// 其余厂商继续沿用 WeKnora 自带描述。
//
// 数据核验日期：2026-08-05（各厂商官方文档）
// - DeepSeek：https://api-docs.deepseek.com/（deepseek-chat/deepseek-reasoner 已于 2026-07-24 弃用，
//   当前仅 deepseek-v4-flash / deepseek-v4-pro）
// - Kimi：https://platform.kimi.com/docs/overview（kimi-k3 / kimi-k2.7-code / kimi-k2.6 等）
// - 阿里云百炼：https://help.aliyun.com/zh/model-studio/models
// - 智谱：https://docs.bigmodel.cn/cn/guide/start/model-overview、/api-reference/模型-api/文本重排序
import type { ModelTypeAlias } from "../types/weknoraAdmin";

export const PROVIDER_MODEL_CATALOG: Record<string, Partial<Record<ModelTypeAlias, string[]>>> = {
  deepseek: {
    chat: ["deepseek-v4-flash", "deepseek-v4-pro"],
  },
  moonshot: {
    chat: ["kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6", "kimi-k2.5"],
    vllm: ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6"],
  },
  aliyun: {
    chat: ["qwen3.8-max", "qwen3.7-plus", "qwen3.7-flash"],
    embedding: ["text-embedding-v4", "text-embedding-v3"],
    rerank: ["qwen3-rerank", "gte-rerank-v2"],
    vllm: ["qwen3.5-omni-plus", "qwen3.8-max"],
  },
  zhipu: {
    chat: [
      "glm-5.2",
      "glm-5-turbo",
      "glm-4.7",
      "glm-4.7-flash",
      "glm-4.6",
      "glm-4.5-air",
      "glm-4-long",
    ],
    embedding: ["embedding-3", "embedding-3-pro"],
    rerank: ["rerank"],
    vllm: ["glm-5v-turbo", "glm-4.6v", "glm-4.6v-flash", "glm-4v-flash"],
  },
};

/** 返回某供应商某模型类型的当前官方模型名；目录外返回空数组。 */
export function getProviderCatalogModels(provider: string, type: string): string[] {
  return PROVIDER_MODEL_CATALOG[provider]?.[type as ModelTypeAlias] ?? [];
}

/** 返回可直接展示在选项描述里的当前官方模型文案；目录外返回 null。 */
export function getProviderCatalogDescription(provider: string, type: string): string | null {
  const models = getProviderCatalogModels(provider, type);
  return models.length > 0 ? `当前官方模型：${models.join("、")}` : null;
}
