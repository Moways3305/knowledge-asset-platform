import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  fetchWeknoraProviders,
  migrateWeknoraKb,
  createWeknoraModel,
  checkWeknoraModel,
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
import type { ModelDTO } from "../types/weknoraAdmin";

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
  migrateWeknoraKb: vi.fn(),
  createWeknoraModel: vi.fn(),
  checkWeknoraModel: vi.fn(),
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
      credential_status: "configured",
    });
    vi.mocked(checkWeknoraModel).mockResolvedValue({
      success: true,
      message: "凭据已确认保存，连通性已验证",
      error_code: null,
      credential_status: "configured",
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

  it("shows credential truth and never treats available=false as connected", async () => {
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      {
        model_ref: "safe-embedding-ref",
        name: "text-embedding-v3",
        type: "embedding",
        source: "remote",
        provider: "aliyun",
        enabled: true,
        is_builtin: false,
        description: null,
        credential_status: "configured",
      },
    ]);
    vi.mocked(checkWeknoraModel).mockResolvedValue({
      success: false,
      message: "连通性测试失败，请检查凭据、网络或模型协议后重试",
      error_code: "model_unavailable",
      credential_status: "configured",
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /展开模型列表/ }));
    expect(screen.getByText("凭据已确认保存，等待连通性测试")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "测试连通性" }));
    expect(
      await screen.findByText("连通性测试失败，请检查凭据、网络或模型协议后重试"),
    ).toBeInTheDocument();
    expect(screen.getByText("连通性测试失败，可查看安全错误说明后重试")).toBeInTheDocument();
    expect(screen.queryByText("模型连通性正常")).not.toBeInTheDocument();
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
        credential_status: "configured",
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
        migration: null,
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
    const availableModels: ModelDTO[] = [
      {
        model_ref: "foundation-chat-ref",
        name: "底座兼容模型",
        type: "chat",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
        credential_status: "configured",
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
        credential_status: "configured",
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
      migration: null,
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
        credential_status: "configured",
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
        credential_status: "configured",
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

  it("shows curated current model names in provider options and name suggestions", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "新增 WeKnora 模型" }));

    fireEvent.click(screen.getByRole("button", { name: "模型供应商" }));
    expect(screen.getByRole("option", { name: /阿里云 DashScope/ })).toHaveTextContent(
      "当前官方模型：qwen3.8-max、qwen3.7-plus、qwen3.7-flash",
    );
    fireEvent.click(screen.getByRole("option", { name: /阿里云 DashScope/ }));

    const nameInput = screen.getByLabelText(/模型名称/);
    expect(nameInput).toHaveAttribute("list");
    expect(
      screen.getByText("可选：qwen3.8-max、qwen3.7-plus、qwen3.7-flash（也可手动输入）"),
    ).toBeInTheDocument();
  });

  it("shows final reconciliation truth and only offers verification when nothing failed", async () => {
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([
      {
        mapping_id: "safe-mapping-id",
        scope: "company",
        kb_name: "公司知识库",
        project_name: null,
        owner_name: null,
        mapping_status: "migrating",
        chat: null,
        embedding: null,
        rerank: null,
        multimodal: null,
        config_error: null,
        migration: {
          job_id: "safe-job-id",
          job_status: "completed_with_errors",
          total_count: 8,
          success_count: 5,
          completed_count: 3,
          verified_duplicate_count: 2,
          processing_count: 1,
          duplicate_pending_count: 2,
          pending_count: 3,
          failed_count: 0,
          finished_at: "2026-08-10T00:00:00Z",
        },
      },
    ]);

    renderPage();

    expect(await screen.findByText(/3 完成/)).toHaveTextContent(
      "3 完成 · 2 重复项已核验 · 1 处理中 · 2 重复项待核验 · 0 失败。 请等待后再次核验。",
    );
    expect(screen.getByRole("button", { name: "再次核验" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试失败项" })).not.toBeInTheDocument();
  });

  it("submits a KB migration with the chosen models", async () => {
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      {
        model_ref: "emb-new",
        name: "新嵌入模型",
        type: "embedding",
        source: "remote",
        provider: "aliyun",
        enabled: true,
        is_builtin: false,
        description: null,
        credential_status: "configured",
      },
      {
        model_ref: "chat-new",
        name: "新问答模型",
        type: "chat",
        source: "remote",
        provider: "aliyun",
        enabled: true,
        is_builtin: false,
        description: null,
        credential_status: "configured",
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
        chat: { model_ref: "chat-old", name: "旧问答", type: "chat", provider: "provider" },
        embedding: {
          model_ref: "emb-old",
          name: "旧嵌入",
          type: "embedding",
          provider: "provider",
        },
        rerank: null,
        multimodal: null,
        config_error: null,
        migration: null,
      },
    ]);
    vi.mocked(migrateWeknoraKb).mockResolvedValue({
      job_id: "migrate-job-1",
      job_status: "queued",
      mapping_id: "safe-mapping-id",
    });

    renderPage();
    const row = (await screen.findByText("公司知识库")).closest("tr");
    fireEvent.click(within(row!).getByRole("button", { name: "迁移库" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("迁移知识库“公司知识库”");
    fireEvent.change(within(screen.getByRole("dialog")).getByLabelText("嵌入模型（必选）"), {
      target: { value: "emb-new" },
    });
    fireEvent.change(within(screen.getByRole("dialog")).getByLabelText("问答模型（必选）"), {
      target: { value: "chat-new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始迁移" }));

    await waitFor(() =>
      expect(migrateWeknoraKb).toHaveBeenCalledWith("safe-mapping-id", {
        embedding_model_ref: "emb-new",
        chat_model_ref: "chat-new",
        multimodal_model_ref: null,
      }),
    );
  });
});
