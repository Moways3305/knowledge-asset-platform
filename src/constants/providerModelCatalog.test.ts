import { describe, expect, it } from "vitest";
import {
  getProviderCatalogDescription,
  getProviderCatalogModels,
  PROVIDER_MODEL_CATALOG,
} from "./providerModelCatalog";

describe("providerModelCatalog", () => {
  it("covers the four primary providers", () => {
    expect(Object.keys(PROVIDER_MODEL_CATALOG).sort()).toEqual([
      "aliyun",
      "deepseek",
      "moonshot",
      "zhipu",
    ]);
  });

  it("uses current DeepSeek names and never suggests deprecated aliases", () => {
    expect(getProviderCatalogModels("deepseek", "chat")).toEqual([
      "deepseek-v4-flash",
      "deepseek-v4-pro",
    ]);
    const joined = getProviderCatalogModels("deepseek", "chat").join(",");
    expect(joined).not.toMatch(/deepseek-chat|deepseek-reasoner/);
  });

  it("lists current Kimi models with multimodal support", () => {
    expect(getProviderCatalogModels("moonshot", "chat")).toContain("kimi-k3");
    expect(getProviderCatalogModels("moonshot", "chat")).toContain("kimi-k2.6");
    expect(getProviderCatalogModels("moonshot", "vllm")).toContain("kimi-k3");
  });

  it("lists current Qwen models per type", () => {
    expect(getProviderCatalogModels("aliyun", "chat")).toContain("qwen3.8-max");
    expect(getProviderCatalogModels("aliyun", "embedding")).toContain("text-embedding-v4");
    expect(getProviderCatalogModels("aliyun", "rerank")).toContain("qwen3-rerank");
  });

  it("lists current GLM models per type", () => {
    expect(getProviderCatalogModels("zhipu", "chat")).toContain("glm-5.2");
    expect(getProviderCatalogModels("zhipu", "embedding")).toContain("embedding-3");
    expect(getProviderCatalogModels("zhipu", "rerank")).toEqual(["rerank"]);
  });

  it("returns empty suggestions for unknown providers or unsupported types", () => {
    expect(getProviderCatalogModels("generic", "chat")).toEqual([]);
    expect(getProviderCatalogModels("deepseek", "embedding")).toEqual([]);
    expect(getProviderCatalogModels("", "chat")).toEqual([]);
  });

  it("builds a description only when the provider and type have models", () => {
    expect(getProviderCatalogDescription("deepseek", "chat")).toBe(
      "当前官方模型：deepseek-v4-flash、deepseek-v4-pro",
    );
    expect(getProviderCatalogDescription("deepseek", "embedding")).toBeNull();
    expect(getProviderCatalogDescription("generic", "chat")).toBeNull();
  });
});
