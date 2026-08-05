import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  fetchWeknoraProviders,
  createWeknoraModel,
  updateWeknoraDefaultModels,
  updateWeknoraKbInit,
} from "../api/admin";
import { ApiError } from "../api/http";
import {
  createModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  testModelConnection,
  updateModelConnection,
  updateModelUsageAssignments,
} from "../api/modelConnections";
import AdminWeKnoraModelsPage from "./AdminWeKnoraModelsPage";
import type { ModelConnectionDTO } from "../types/modelConnections";

const auth = vi.hoisted(() => ({
  capabilities: { isAdmin: true, isGovernance: false, isProjectManager: false },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => auth,
}));

vi.mock("../api/admin", () => ({
  fetchWeknoraKbConfigs: vi.fn(),
  fetchWeknoraDefaultModels: vi.fn(),
  fetchWeknoraModels: vi.fn(),
  fetchWeknoraProviders: vi.fn(),
  createWeknoraModel: vi.fn(),
  updateWeknoraDefaultModels: vi.fn(),
  updateWeknoraKbInit: vi.fn(),
}));

vi.mock("../api/modelConnections", () => ({
  createModelConnection: vi.fn(),
  fetchModelConnections: vi.fn(),
  fetchModelUsageAssignments: vi.fn(),
  testModelConnection: vi.fn(),
  updateModelConnection: vi.fn(),
  updateModelUsageAssignments: vi.fn(),
}));

const connection: ModelConnectionDTO = {
  model_ref: "safe-chat-ref",
  display_name: "DeepSeek 对话",
  capability_type: "chat" as const,
  provider: "deepseek",
  model_name: "deepseek-chat",
  enabled: true,
  health_status: "untested",
  last_test_succeeded_at: null,
  last_test_failed_at: null,
  last_error_category: null,
  available_usages: ["content_generation", "project_qa"],
  legacy_adapter: false,
};
const emptyUsages = {
  external_llm_default: null,
  dependency_status: "missing" as const,
  dependency_message: "未设置外部 LLM 默认连接，内容生成和默认项目问答将不可用。",
  remediation_hint: "选择一个已启用且测试通过的外部 LLM 连接并保存。",
};

function renderPage() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AdminWeKnoraModelsPage />
    </MemoryRouter>,
  );
}

describe("AdminWeKnoraModelsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(auth.capabilities, {
      isAdmin: true,
      isGovernance: false,
      isProjectManager: false,
    });
    vi.mocked(fetchWeknoraModels).mockResolvedValue([]);
    vi.mocked(fetchWeknoraProviders).mockResolvedValue([
      {
        value: "aliyun",
        label: "阿里云 DashScope",
        description: "qwen-plus, tongyi-embedding-vision-plus, etc.",
        model_types: ["chat", "embedding", "rerank", "vllm"],
        default_urls: {
          chat: "https://dashscope.aliyuncs.com/compatible-mode/v1",
          embedding: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
      },
      {
        value: "generic",
        label: "自定义 (OpenAI兼容接口)",
        description: null,
        model_types: ["chat", "embedding", "rerank", "vllm", "asr"],
        default_urls: {},
      },
    ]);
    vi.mocked(createWeknoraModel).mockResolvedValue({
      model_ref: "new-model-ref",
      name: "qwen-plus",
      type: "chat",
      provider: "aliyun",
      status: "ok",
    });
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([]);
    vi.mocked(fetchWeknoraDefaultModels).mockResolvedValue({
      embedding: null,
      rerank: null,
      chat: null,
      multimodal: null,
      updated_at: null,
    });
    vi.mocked(updateWeknoraDefaultModels).mockResolvedValue({
      embedding: null,
      rerank: null,
      chat: null,
      multimodal: null,
      updated_at: null,
    });
    vi.mocked(fetchModelConnections).mockResolvedValue({
      items: [connection],
      total: 1,
      warning: null,
    });
    vi.mocked(fetchModelUsageAssignments).mockResolvedValue(emptyUsages);
    vi.mocked(createModelConnection).mockResolvedValue(connection);
    vi.mocked(updateModelConnection).mockResolvedValue(connection);
    vi.mocked(updateModelUsageAssignments).mockResolvedValue(emptyUsages);
    vi.mocked(testModelConnection).mockResolvedValue({
      success: true,
      error_category: null,
      message: "外部 LLM 连接正常。",
      remediation_hint: "无需处理。",
      retryable: false,
      duration_ms: 18,
    });
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("gives project managers only their scoped KB initialization workspace", async () => {
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isGovernance: false,
      isProjectManager: true,
    });
    renderPage();

    expect(
      await screen.findByText("仅显示你担任项目经理的项目知识库，可在此修复初始化失败配置。"),
    ).toBeInTheDocument();
    expect(fetchWeknoraModels).toHaveBeenCalledTimes(1);
    expect(fetchWeknoraKbConfigs).toHaveBeenCalledTimes(1);
    expect(fetchWeknoraDefaultModels).not.toHaveBeenCalled();
    expect(screen.queryByText("WEKNORA BASE")).not.toBeInTheDocument();
  });

  it("shows external LLM separately from WeKnora foundation configuration", async () => {
    const { container } = renderPage();
    expect(await screen.findByText("DeepSeek 对话")).toBeInTheDocument();
    expect(screen.getByText("未测试")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "新增外部 LLM" })).toHaveLength(1);
    expect(screen.getByText("知识库底座")).toBeInTheDocument();
    expect(container.querySelector(".mf-workspace")).toBeInTheDocument();
    expect(container.querySelector(".mf-connection-card")).toBeInTheDocument();
    expect(container.querySelector(".mf-foundation-panel")).toBeInTheDocument();
    expect(container.querySelector(".mf-kb-section")).toBeInTheDocument();
    expect(screen.queryByText("新增内容生成模型")).not.toBeInTheDocument();
  });

  it("adds anti-autofill attributes and never pre-fills saved secrets", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("编辑"));
    const apiUrl = screen.getByLabelText("API 地址");
    const apiKey = screen.getByLabelText("API key");
    expect(apiUrl).toHaveAttribute("name", "model_connection_endpoint");
    expect(apiUrl).toHaveAttribute("autocomplete", "off");
    expect(apiUrl).toHaveAttribute("data-lpignore", "true");
    expect(apiKey).toHaveAttribute("name", "model_connection_secret");
    expect(apiKey).toHaveAttribute("autocomplete", "new-password");
    expect(apiUrl).toHaveValue("");
    expect(apiKey).toHaveValue("");
  });

  it("blocks an invalid API URL before saving", async () => {
    vi.mocked(fetchModelConnections).mockResolvedValue({ items: [], total: 0, warning: null });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "新增外部 LLM" }));
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Qwen" } });
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "qwen-plus" } });
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "secret" } });
    fireEvent.click(screen.getByText("保存外部 LLM"));
    expect(
      await screen.findByText("API 地址必须以 http:// 或 https:// 开头。"),
    ).toBeInTheDocument();
    expect(createModelConnection).not.toHaveBeenCalled();
  });

  it("omits blank endpoint and key while editing", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("编辑"));
    fireEvent.click(screen.getByText("保存外部 LLM"));
    await waitFor(() => expect(updateModelConnection).toHaveBeenCalled());
    expect(updateModelConnection).toHaveBeenCalledWith(
      connection.model_ref,
      expect.not.objectContaining({ base_url: expect.anything(), api_key: expect.anything() }),
    );
  });

  it("tests a saved connection and renders safe duration", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("测试连接"));
    expect(await screen.findByText("外部 LLM 连接正常。 无需处理。 · 18 ms")).toBeInTheDocument();
    expect(testModelConnection).toHaveBeenCalledWith(connection.model_ref);
  });

  it("turns list failures into an actionable message without raw HTTP status", async () => {
    vi.mocked(fetchModelConnections).mockRejectedValue(new Error("500 SECRET-LIKE"));
    renderPage();
    expect(
      await screen.findByText("外部 LLM 列表加载失败，请刷新或检查连接服务。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/500|SECRET-LIKE/)).not.toBeInTheDocument();
  });

  it("distinguishes a rejected KB config without exposing the upstream error", async () => {
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      {
        model_ref: "safe-chat-ref",
        name: "问答模型",
        type: "chat",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
      },
    ]);
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([
      {
        mapping_id: "safe-mapping-id",
        scope: "company",
        kb_name: "公司知识库",
        project_name: null,
        owner_name: null,
        mapping_status: "active",
        chat: null,
        embedding: null,
        rerank: null,
        multimodal: null,
        config_error: null,
      },
    ]);
    vi.mocked(updateWeknoraKbInit).mockRejectedValue(
      new ApiError(502, "SECRET-LIKE upstream body", "weknora_kb_config_rejected"),
    );

    renderPage();
    const kbRow = (await screen.findByText("公司知识库")).closest("tr");
    expect(kbRow).not.toBeNull();
    fireEvent.change(within(kbRow!).getAllByRole("combobox")[0], {
      target: { value: "safe-chat-ref" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(
      await screen.findByText("知识库配置被底座拒绝，请检查所选模型是否兼容。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/SECRET-LIKE/)).not.toBeInTheDocument();
  });

  it("re-reads and renders the saved KB configuration from the server", async () => {
    const availableModels = [
      {
        model_ref: "foundation-chat-ref",
        name: "底座兼容模型",
        type: "chat",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
      },
      {
        model_ref: "embedding-ref",
        name: "底座嵌入模型",
        type: "embedding",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
      },
    ];
    const initial = {
      mapping_id: "safe-mapping-ref",
      scope: "project",
      kb_name: "交付知识库",
      project_name: "交付项目",
      owner_name: null,
      mapping_status: "init_failed",
      chat: null,
      embedding: {
        model_ref: "embedding-ref",
        name: "底座嵌入模型",
        type: "embedding",
        provider: "provider",
      },
      rerank: null,
      multimodal: null,
      config_error: "保存前状态",
    };
    const refreshed = {
      ...initial,
      mapping_status: "active",
      chat: {
        model_ref: "foundation-chat-ref",
        name: "底座兼容模型",
        type: "chat",
        provider: "provider",
      },
      config_error: null,
    };
    vi.mocked(fetchWeknoraModels).mockResolvedValue(availableModels);
    vi.mocked(fetchWeknoraKbConfigs)
      .mockResolvedValueOnce([initial])
      .mockResolvedValueOnce([refreshed]);
    vi.mocked(updateWeknoraKbInit).mockResolvedValue({
      mapping_id: initial.mapping_id,
      mapping_status: "active",
      updated: true,
    });

    renderPage();
    const row = (await screen.findByText("交付知识库")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row!).getByText("初始化失败")).toBeInTheDocument();
    fireEvent.change(within(row!).getByLabelText("交付知识库 底座兼容"), {
      target: { value: "foundation-chat-ref" },
    });
    fireEvent.click(within(row!).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(fetchWeknoraKbConfigs).toHaveBeenCalledTimes(2));
    expect(await within(row!).findByText("已初始化")).toBeInTheDocument();
    expect(within(row!).getByLabelText("交付知识库 底座兼容")).toHaveValue("foundation-chat-ref");
    expect(screen.queryByText("保存前状态")).not.toBeInTheDocument();
  });

  it("maintains WeKnora foundation defaults through the dedicated bottom-layer API", async () => {
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      {
        model_ref: "embedding-ref",
        name: "底座嵌入",
        type: "embedding",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
      },
      {
        model_ref: "foundation-chat-ref",
        name: "底座兼容 LLM",
        type: "chat",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
      },
    ]);
    renderPage();
    fireEvent.change(await screen.findByLabelText("默认嵌入模型"), {
      target: { value: "embedding-ref" },
    });
    fireEvent.change(screen.getByLabelText("底座兼容 LLM"), {
      target: { value: "foundation-chat-ref" },
    });
    fireEvent.click(screen.getByText("保存底座配置"));

    await waitFor(() =>
      expect(updateWeknoraDefaultModels).toHaveBeenCalledWith({
        embedding_model_ref: "embedding-ref",
        chat_model_ref: "foundation-chat-ref",
        rerank_model_ref: null,
        multimodal_ref: null,
      }),
    );
  });

  it("keeps external LLM management available when WeKnora is unavailable", async () => {
    vi.mocked(fetchWeknoraModels).mockRejectedValue(
      new ApiError(503, "WeKnora 未配置", "weknora_not_configured"),
    );
    renderPage();

    expect(await screen.findByText("DeepSeek 对话")).toBeInTheDocument();
    expect(screen.getByText("WeKnora 尚未配置")).toBeInTheDocument();
    expect(screen.getByText("这不会影响左侧外部 LLM 的创建、编辑和测试。")).toBeInTheDocument();
  });

  it("reuses WeKnora provider list and auto-fills default API URL on new model", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "新增 WeKnora 模型" }));
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "qwen-plus" } });

    fireEvent.click(screen.getByRole("button", { name: "模型供应商" }));
    fireEvent.click(screen.getByRole("option", { name: /阿里云 DashScope/ }));

    expect(screen.getByLabelText("API 地址")).toHaveValue(
      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    );
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 WeKnora 模型" }));

    await waitFor(() =>
      expect(createWeknoraModel).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "qwen-plus",
          provider: "aliyun",
          base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
          api_key: "sk-test",
        }),
      ),
    );
  });
});
