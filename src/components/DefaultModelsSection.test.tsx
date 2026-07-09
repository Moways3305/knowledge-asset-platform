import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DefaultModelsSection from "./DefaultModelsSection";
import type { ModelDTO } from "../types/weknoraAdmin";

const api = vi.hoisted(() => ({
  fetchDefaultModels: vi.fn(),
  fetchGenerationModelOptions: vi.fn(),
  updateDefaultModels: vi.fn(),
  updateGenerationDefaultModel: vi.fn(),
}));
vi.mock("../api/weknoraModels", () => api);

const models: ModelDTO[] = [
  {
    model_ref: "ref_emb_a",
    name: "BGE 嵌入",
    type: "embedding",
    source: "remote",
    provider: "siliconflow",
    enabled: true,
    is_builtin: false,
    description: null,
  },
  {
    model_ref: "ref_rer_a",
    name: "BGE 重排",
    type: "rerank",
    source: "remote",
    provider: "siliconflow",
    enabled: true,
    is_builtin: false,
    description: null,
  },
  {
    model_ref: "ref_chat_a",
    name: "DeepSeek 问答",
    type: "chat",
    source: "remote",
    provider: "deepseek",
    enabled: true,
    is_builtin: false,
    description: null,
  },
];

const currentDefaults = {
  embedding: {
    model_ref: "ref_emb_a",
    name: "BGE 嵌入",
    type: "embedding",
    provider: "siliconflow",
  },
  rerank: null,
  chat: {
    model_ref: "ref_chat_a",
    name: "DeepSeek 问答",
    type: "chat",
    provider: "deepseek",
  },
  multimodal: null,
  updated_at: "2026-06-26T00:00:00Z",
};

describe("DefaultModelsSection", () => {
  beforeEach(() => {
    api.fetchDefaultModels.mockReset().mockResolvedValue(currentDefaults);
    api.fetchGenerationModelOptions.mockReset().mockResolvedValue({
      items: [
        {
          model_ref: "ref_gen_a",
          name: "DeepSeek 内容生成",
          provider: "deepseek",
          enabled: true,
          is_default: true,
        },
      ],
      default_missing: false,
    });
    api.updateDefaultModels.mockReset().mockResolvedValue(currentDefaults);
    api.updateGenerationDefaultModel.mockReset().mockResolvedValue({
      current_default: null,
      configured: true,
    });
  });

  it("加载当前默认并以 model_ref 选中（不展示真实 model_id）", async () => {
    render(<DefaultModelsSection models={models} canEdit={true} />);
    await waitFor(() => {
      const sel = screen.getByLabelText("默认嵌入 embedding") as HTMLSelectElement;
      expect(sel.value).toBe("ref_emb_a");
    });
    // option 值是安全 model_ref；展示文案是模型名。
    expect(screen.getByText(/BGE 嵌入/)).toBeInTheDocument();
    expect(screen.getByLabelText("KAP 内容生成模型")).toHaveValue("ref_gen_a");
  });

  it("admin 保存调用 PUT（updateDefaultModels），只提交 model_ref", async () => {
    render(<DefaultModelsSection models={models} canEdit={true} />);
    await waitFor(() => expect(api.fetchDefaultModels).toHaveBeenCalled());
    await userEvent.selectOptions(screen.getByLabelText("默认重排 rerank（可选）"), "ref_rer_a");
    await userEvent.click(screen.getByRole("button", { name: /保存平台默认模型/ }));
    await waitFor(() => expect(api.updateDefaultModels).toHaveBeenCalledTimes(1));
    const body = api.updateDefaultModels.mock.calls[0][0];
    expect(body.embedding_model_ref).toBe("ref_emb_a");
    expect(body.rerank_model_ref).toBe("ref_rer_a");
    expect(body).not.toHaveProperty("embedding_model_id");
    expect(api.updateGenerationDefaultModel).toHaveBeenCalledWith({ model_ref: "ref_gen_a" });
  });

  it("治理角色只读：无保存按钮且选择框禁用", async () => {
    render(<DefaultModelsSection models={models} canEdit={false} />);
    await waitFor(() => expect(api.fetchDefaultModels).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /保存平台默认模型/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("默认嵌入 embedding")).toBeDisabled();
    expect(screen.getByLabelText("KAP 内容生成模型")).toBeDisabled();
  });

  it("默认嵌入模型未配置时显示安全提示", async () => {
    api.fetchDefaultModels.mockResolvedValue({ ...currentDefaults, embedding: null });
    render(<DefaultModelsSection models={models} canEdit={true} />);
    await waitFor(() => expect(screen.getByText(/尚未配置默认嵌入模型/)).toBeInTheDocument());
  });

  it("内容生成模型缺失时用独立文案提示，不混入 WeKnora 知识库模型", async () => {
    api.fetchGenerationModelOptions.mockResolvedValue({ items: [], default_missing: true });
    render(<DefaultModelsSection models={models} canEdit={true} />);
    await waitFor(() => expect(screen.getByText(/尚未配置 KAP 内容生成模型/)).toBeInTheDocument());
    expect(screen.getByText(/不参与 WeKnora/)).toBeInTheDocument();
  });
});
