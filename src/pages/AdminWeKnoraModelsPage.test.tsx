import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
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

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities: { isAdmin: true } }),
}));

vi.mock("../api/admin", () => ({
  fetchWeknoraKbConfigs: vi.fn(),
  fetchWeknoraDefaultModels: vi.fn(),
  fetchWeknoraModels: vi.fn(),
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
    <MemoryRouter>
      <AdminWeKnoraModelsPage />
    </MemoryRouter>,
  );
}

describe("AdminWeKnoraModelsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchWeknoraModels).mockResolvedValue([]);
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

  it("shows external LLM separately from WeKnora foundation configuration", async () => {
    renderPage();
    expect(await screen.findByText("DeepSeek 对话")).toBeInTheDocument();
    expect(screen.getByText("未测试")).toBeInTheDocument();
    expect(screen.getAllByText("新增外部 LLM 连接")).toHaveLength(1);
    expect(screen.getByText("WeKnora 底座默认模型")).toBeInTheDocument();
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
    fireEvent.click((await screen.findAllByText("新增外部 LLM 连接"))[0]);
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Qwen" } });
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "qwen-plus" } });
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "secret" } });
    fireEvent.click(screen.getByText("保存外部 LLM 连接"));
    expect(await screen.findByText("API 地址必须以 http:// 或 https:// 开头")).toBeInTheDocument();
    expect(createModelConnection).not.toHaveBeenCalled();
  });

  it("omits blank endpoint and key while editing", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("编辑"));
    fireEvent.click(screen.getByText("保存外部 LLM 连接"));
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
      await screen.findByText("外部 LLM 列表加载失败，请刷新或检查连接服务"),
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
      await screen.findByText("知识库配置被底座拒绝，请检查所选模型是否兼容"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/SECRET-LIKE/)).not.toBeInTheDocument();
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
    fireEvent.change(screen.getByLabelText("底座兼容配置（LLM 槽位）"), {
      target: { value: "foundation-chat-ref" },
    });
    fireEvent.click(screen.getByText("保存 WeKnora 底座默认模型"));

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
    expect(
      screen.getByText("此状态不影响上方外部 LLM 连接的创建、编辑和测试。"),
    ).toBeInTheDocument();
  });
});
