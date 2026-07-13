import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWeknoraKbConfigs, fetchWeknoraModels, updateWeknoraKbInit } from "../api/admin";
import { ApiError } from "../api/http";
import {
  createModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  testModelConnection,
  updateModelConnection,
  updateModelUsageAssignments,
} from "../api/weknoraModels";
import AdminWeKnoraModelsPage from "./AdminWeKnoraModelsPage";
import type { ModelConnectionDTO } from "../types/weknoraAdmin";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities: { isAdmin: true } }),
}));

vi.mock("../api/admin", () => ({
  fetchWeknoraKbConfigs: vi.fn(),
  fetchWeknoraModels: vi.fn(),
  updateWeknoraKbInit: vi.fn(),
}));

vi.mock("../api/weknoraModels", () => ({
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
  health_status: "registered",
  available_usages: ["content_generation", "knowledge_chat"],
  legacy_adapter: false,
};
const emptyUsages = {
  content_generation: null,
  knowledge_embedding: null,
  knowledge_chat: null,
  knowledge_rerank: null,
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
    vi.mocked(fetchWeknoraModels).mockResolvedValue([]);
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([]);
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
      message: "连接测试成功",
      duration_ms: 18,
    });
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("shows one unified connection entry and production status copy", async () => {
    renderPage();
    expect(await screen.findByText("DeepSeek 对话")).toBeInTheDocument();
    expect(screen.getByText("已启用")).toBeInTheDocument();
    expect(screen.getAllByText("新增模型连接")).toHaveLength(1);
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
    fireEvent.click((await screen.findAllByText("新增模型连接"))[0]);
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Qwen" } });
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "qwen-plus" } });
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "secret" } });
    fireEvent.click(screen.getByText("保存模型连接"));
    expect(await screen.findByText("API 地址必须以 http:// 或 https:// 开头")).toBeInTheDocument();
    expect(createModelConnection).not.toHaveBeenCalled();
  });

  it("omits blank endpoint and key while editing", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("编辑"));
    fireEvent.click(screen.getByText("保存模型连接"));
    await waitFor(() => expect(updateModelConnection).toHaveBeenCalled());
    expect(updateModelConnection).toHaveBeenCalledWith(
      connection.model_ref,
      expect.not.objectContaining({ base_url: expect.anything(), api_key: expect.anything() }),
    );
  });

  it("tests a saved connection and renders safe duration", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("测试连接"));
    expect(await screen.findByText("连接正常 · 18 ms")).toBeInTheDocument();
    expect(testModelConnection).toHaveBeenCalledWith(connection.model_ref);
  });

  it("turns list failures into an actionable message without raw HTTP status", async () => {
    vi.mocked(fetchModelConnections).mockRejectedValue(new Error("500 SECRET-LIKE"));
    renderPage();
    expect(await screen.findByText("模型列表加载失败，请刷新或检查模型连接")).toBeInTheDocument();
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
});
