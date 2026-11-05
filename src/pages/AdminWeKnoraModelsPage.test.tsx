import { fetchRegistry, fetchProviderCatalog } from "../api/modelRegistry";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWeknoraModel,
  deleteWeknoraModel,
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  fetchWeknoraProviders,
  migrateWeknoraKb,
  updateWeknoraDefaultModels,
  updateWeknoraKbInit,
  updateWeknoraModel,
} from "../api/admin";
import {
  createModelConnection,
  deleteModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  testModelConnection,
  updateModelConnection,
  updateModelUsageAssignments,
} from "../api/modelConnections";
import type { ModelConnectionDTO } from "../types/modelConnections";
import type { KbConfigDTO, ModelDTO } from "../types/weknoraAdmin";
import AdminWeKnoraModelsPage from "./AdminWeKnoraModelsPage";

const auth = vi.hoisted(() => ({
  capabilities: { isAdmin: true, isGovernance: false, isProjectManager: false },
}));

vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../api/modelRegistry", () => ({
  fetchRegistry: vi.fn(),
  fetchProviderCatalog: vi.fn(),
  createProviderConnection: vi.fn(),
  updateProviderConnection: vi.fn(),
  createRegisteredModel: vi.fn(),
  updateRegisteredModel: vi.fn(),
  verifyRegisteredModel: vi.fn(),
  syncRegisteredModel: vi.fn(),
}));
vi.mock("../api/admin", () => ({
  checkWeknoraModel: vi.fn(),
  createWeknoraModel: vi.fn(),
  deleteWeknoraModel: vi.fn(),
  fetchWeknoraDefaultModels: vi.fn(),
  fetchWeknoraKbConfigs: vi.fn(),
  fetchWeknoraModels: vi.fn(),
  fetchWeknoraProviders: vi.fn(),
  migrateWeknoraKb: vi.fn(),
  updateWeknoraDefaultModels: vi.fn(),
  updateWeknoraKbInit: vi.fn(),
  updateWeknoraModel: vi.fn(),
}));
vi.mock("../api/modelConnections", () => ({
  createModelConnection: vi.fn(),
  deleteModelConnection: vi.fn(),
  fetchModelConnections: vi.fn(),
  fetchModelUsageAssignments: vi.fn(),
  testModelConnection: vi.fn(),
  updateModelConnection: vi.fn(),
  updateModelUsageAssignments: vi.fn(),
}));

const models: ModelDTO[] = [
  {
    model_ref: "chat-ref",
    name: "qwen-plus",
    type: "chat",
    source: "remote",
    provider: "aliyun",
    enabled: true,
    is_builtin: false,
    description: null,
    credential_status: "configured",
  },
  {
    model_ref: "embedding-ref",
    name: "text-embedding-v3",
    type: "embedding",
    source: "remote",
    provider: "aliyun",
    enabled: true,
    is_builtin: false,
    description: null,
    credential_status: "configured",
  },
];

const connection: ModelConnectionDTO = {
  model_ref: "external-ref",
  display_name: "DeepSeek 对话",
  capability_type: "chat",
  provider: "deepseek",
  model_name: "deepseek-chat",
  enabled: true,
  health_status: "healthy",
  last_test_succeeded_at: null,
  last_test_failed_at: null,
  last_error_category: null,
  available_usages: ["content_generation", "project_qa"],
  legacy_adapter: false,
};

const kb: KbConfigDTO = {
  mapping_id: "internal-mapping-id",
  scope: "project",
  kb_name: "交付方法库",
  project_name: "Alpha 项目",
  owner_name: null,
  mapping_status: "active",
  chat: { model_ref: "chat-ref", name: "qwen-plus", type: "chat", provider: "aliyun" },
  embedding: {
    model_ref: "embedding-ref",
    name: "text-embedding-v3",
    type: "embedding",
    provider: "aliyun",
  },
  rerank: null,
  multimodal: null,
  config_error: null,
  migration: {
    job_id: "internal-job-id",
    job_status: "completed_with_errors",
    total_count: 8,
    success_count: 6,
    completed_count: 5,
    verified_duplicate_count: 1,
    processing_count: 0,
    duplicate_pending_count: 0,
    pending_count: 0,
    failed_count: 2,
    finished_at: "2026-08-11T08:00:00Z",
  },
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminWeKnoraModelsPage />
    </MemoryRouter>,
  );
}

describe("AdminWeKnoraModelsPage modal workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchRegistry).mockResolvedValue({ connections: [], models: [] });
    vi.mocked(fetchProviderCatalog).mockResolvedValue({ providers: [] });
    Object.assign(auth.capabilities, {
      isAdmin: true,
      isGovernance: false,
      isProjectManager: false,
    });
    vi.mocked(fetchWeknoraModels).mockResolvedValue(models);
    vi.mocked(fetchWeknoraProviders).mockResolvedValue([]);
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([kb]);
    vi.mocked(fetchWeknoraDefaultModels).mockResolvedValue({
      embedding: kb.embedding,
      rerank: null,
      chat: kb.chat,
      multimodal: null,
      updated_at: "2026-08-11T08:00:00Z",
    });
    vi.mocked(fetchModelConnections).mockResolvedValue({
      items: [connection],
      total: 1,
      warning: null,
    });
    vi.mocked(fetchModelUsageAssignments).mockResolvedValue({
      external_llm_default: {
        model_ref: connection.model_ref,
        display_name: connection.display_name,
        capability_type: "chat",
      },
      dependency_status: "configured",
      dependency_message: "已配置",
      remediation_hint: "无需处理",
    });
    vi.mocked(updateModelUsageAssignments).mockResolvedValue({
      external_llm_default: null,
      dependency_status: "missing",
      dependency_message: "未配置",
      remediation_hint: "请选择连接",
    });
    vi.mocked(updateWeknoraDefaultModels).mockResolvedValue({
      embedding: kb.embedding,
      rerank: null,
      chat: kb.chat,
      multimodal: null,
      updated_at: "2026-08-11T08:00:00Z",
    });
    vi.mocked(updateWeknoraKbInit).mockResolvedValue({
      mapping_id: kb.mapping_id,
      mapping_status: "active",
      updated: true,
    });
    vi.mocked(migrateWeknoraKb).mockResolvedValue({
      job_id: "safe-job-ref",
      job_status: "queued",
      mapping_id: kb.mapping_id,
    });
    vi.mocked(createModelConnection).mockResolvedValue(connection);
    vi.mocked(updateModelConnection).mockResolvedValue(connection);
    vi.mocked(deleteModelConnection).mockResolvedValue();
    vi.mocked(testModelConnection).mockResolvedValue({
      success: true,
      error_category: null,
      message: "连接正常",
      remediation_hint: "无需处理",
      retryable: false,
      duration_ms: 12,
    });
    vi.mocked(createWeknoraModel).mockResolvedValue({
      model_ref: "new-ref",
      name: "new-model",
      type: "chat",
      provider: "aliyun",
      status: "ok",
      credential_status: "configured",
    });
    vi.mocked(updateWeknoraModel).mockResolvedValue({
      model_ref: "chat-ref",
      name: "qwen-plus",
      type: "chat",
      provider: "aliyun",
      status: "ok",
      credential_status: "configured",
    });
    vi.mocked(deleteWeknoraModel).mockResolvedValue({ deleted: true });
    Element.prototype.scrollIntoView = vi.fn();
  });

  async function openEntry(kind: "接入模型" | "模型设置", choice: string) {
    await waitFor(() => expect(screen.getByRole("button", { name: kind })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: kind }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: kind })).getByRole("button", {
        name: new RegExp(choice),
      }),
    );
  }

  it("shows both model sources in one inventory without exposing internal identifiers", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "模型管理" })).toBeInTheDocument();
    expect(await screen.findByText("DeepSeek 对话")).toBeInTheDocument();
    expect(screen.getByText("qwen-plus")).toBeInTheDocument();
    expect(screen.getByText("text-embedding-v3")).toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "管理外部 LLM" })).not.toBeInTheDocument();
    expect(screen.queryByText("交付方法库")).not.toBeInTheDocument();
    expect(screen.queryByText("internal-mapping-id")).not.toBeInTheDocument();
    expect(screen.queryByText("internal-job-id")).not.toBeInTheDocument();
  });

  it("searches across model sources and opens the correct conversation editor", async () => {
    renderPage();
    await screen.findByText("DeepSeek 对话");
    fireEvent.change(screen.getByLabelText("搜索模型"), { target: { value: "DeepSeek" } });
    expect(screen.getByText("DeepSeek 对话")).toBeInTheDocument();
    expect(screen.queryByText("qwen-plus")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "接入模型" }));
    expect(screen.getByRole("dialog", { name: "接入模型" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("filters by model capability and keeps knowledge-model creation separate", async () => {
    renderPage();
    await screen.findByText("qwen-plus");
    fireEvent.change(screen.getByLabelText("模型能力"), { target: { value: "embedding" } });
    expect(screen.getByText("text-embedding-v3")).toBeInTheDocument();
    expect(screen.queryByText("qwen-plus")).not.toBeInTheDocument();
    expect(screen.queryByText("DeepSeek 对话")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "接入模型" }));
    expect(screen.getByRole("dialog", { name: "接入模型" })).toBeInTheDocument();
  });

  it("keeps test results separate when model sources have the same reference", async () => {
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      { ...models[0], model_ref: connection.model_ref },
    ]);
    renderPage();
    const external = await screen.findByRole("row", {
      name: "DeepSeek 对话（内容生成 · 项目问答）",
    });
    const knowledge = screen.getByRole("row", { name: "qwen-plus（知识库检索与解析）" });
    expect(within(knowledge).getByText("待测试")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(external).getByRole("button", { name: "测试" })).toBeEnabled(),
    );
    fireEvent.click(within(external).getByRole("button", { name: "测试" }));
    expect(await within(external).findByText("本次测试通过")).toBeInTheDocument();
    expect(within(knowledge).getByText("待测试")).toBeInTheDocument();
    expect(within(knowledge).queryByText("本次测试通过")).not.toBeInTheDocument();
  });

  it("preserves a manually entered workspace endpoint when changing providers", async () => {
    vi.mocked(fetchWeknoraProviders).mockResolvedValue([
      {
        value: "aliyun",
        label: "阿里云百炼",
        description: null,
        model_types: ["chat"],
        default_urls: { chat: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
      },
      {
        value: "deepseek",
        label: "DeepSeek",
        description: null,
        model_types: ["chat"],
        default_urls: { chat: "https://api.deepseek.com/v1" },
      },
    ]);
    renderPage();
    const row = await screen.findByRole("row", { name: "qwen-plus（知识库检索与解析）" });
    await waitFor(() => expect(within(row).getByRole("button", { name: "编辑" })).toBeEnabled());
    fireEvent.click(within(row).getByRole("button", { name: "编辑" }));
    fireEvent.keyDown(screen.getByRole("button", { name: "模型供应商" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: /阿里云百炼/ }));
    expect(screen.getByLabelText("API 地址")).toHaveValue(
      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    );
    const workspaceUrl = "https://workspace.example.invalid/compatible-mode/v1";
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: workspaceUrl } });
    fireEvent.keyDown(screen.getByRole("button", { name: "模型供应商" }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("option", { name: /DeepSeek/ }));
    expect(screen.getByLabelText("API 地址")).toHaveValue(workspaceUrl);
  });

  it("preserves each default assignment endpoint through model settings", async () => {
    renderPage();
    await openEntry("模型设置", "内容生成与项目问答");
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "默认对话模型" })).getByRole("button", {
        name: "保存默认用途",
      }),
    );
    await waitFor(() => expect(updateModelUsageAssignments).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await openEntry("模型设置", "新建知识库的默认模型");
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "知识库默认模型" })).getByRole("button", {
        name: "保存默认底座",
      }),
    );
    await waitFor(() => expect(updateWeknoraDefaultModels).toHaveBeenCalledTimes(1));
  });

  it("filters KBs in their workspace and opens configuration as the only overlay", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理知识库配置" }));
    const drawer = screen.getByRole("region", { name: "管理知识库配置" });
    fireEvent.change(within(drawer).getByLabelText("搜索知识库"), {
      target: { value: "不存在" },
    });
    expect(within(drawer).getByText("没有匹配的知识库")).toBeInTheDocument();
    fireEvent.change(within(drawer).getByLabelText("搜索知识库"), {
      target: { value: "交付" },
    });
    fireEvent.click(within(drawer).getByRole("button", { name: "配置" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "配置“交付方法库”" })).toBeInTheDocument();
  });

  it("submits migration only from the wizard completion step", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理知识库配置" }));
    fireEvent.click(screen.getByRole("button", { name: "更多知识库操作" }));
    fireEvent.click(screen.getByRole("button", { name: "迁移到新嵌入模型" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(migrateWeknoraKb).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "提交迁移作业" }));
    await waitFor(() => expect(migrateWeknoraKb).toHaveBeenCalledTimes(1));
  });

  it("keeps migration counts out of the list and shows them in a result drawer", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理知识库配置" }));
    const kbDrawer = screen.getByRole("region", { name: "管理知识库配置" });
    expect(within(kbDrawer).queryByText("直接完成")).not.toBeInTheDocument();
    fireEvent.click(within(kbDrawer).getByRole("button", { name: "查看迁移结果" }));
    const result = screen.getByRole("dialog", { name: "迁移结果 · 交付方法库" });
    expect(within(result).getByText("直接完成")).toBeInTheDocument();
    expect(within(result).getByText("2")).toBeInTheDocument();
    expect(within(result).queryByText("internal-job-id")).not.toBeInTheDocument();
  });

  it("refreshes an open migration result drawer when polling reaches a terminal state", async () => {
    vi.useFakeTimers();
    const runningKb: KbConfigDTO = {
      ...kb,
      mapping_status: "migrating",
      migration: {
        ...kb.migration!,
        job_status: "running",
        completed_count: 1,
        processing_count: 7,
        failed_count: 0,
      },
    };
    const completedKb: KbConfigDTO = {
      ...kb,
      mapping_status: "active",
      migration: {
        ...kb.migration!,
        job_status: "completed",
        completed_count: 8,
        processing_count: 0,
        failed_count: 0,
      },
    };
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValueOnce([runningKb]);

    try {
      renderPage();
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      fireEvent.click(screen.getByRole("button", { name: "管理知识库配置" }));
      fireEvent.click(screen.getByRole("button", { name: "查看迁移结果" }));
      expect(screen.getByText("迁移核验状态")).toBeInTheDocument();

      vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([completedKb]);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(screen.getByText("迁移已完成")).toBeInTheDocument();
      expect(screen.queryByText("请求已提交，系统仍在处理文档。")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes parent anomaly counts after testing a connection", async () => {
    let current = { ...connection };
    vi.mocked(fetchModelConnections).mockImplementation(async () => ({
      items: [current],
      total: 1,
      warning: null,
    }));
    vi.mocked(testModelConnection).mockImplementation(async () => {
      current = { ...current, health_status: "unhealthy" };
      return {
        success: false,
        message: "连接测试未通过",
        error_category: null,
        retryable: true,
        remediation_hint: "检查配置",
        duration_ms: 1,
      };
    });
    renderPage();
    const row = await screen.findByRole("row", { name: /DeepSeek 对话/ });
    await waitFor(() => expect(within(row).getByRole("button", { name: "测试" })).toBeEnabled());
    fireEvent.click(within(row).getByRole("button", { name: "测试" }));
    await waitFor(() => expect(testModelConnection).toHaveBeenCalledWith("external-ref"));
    expect(await within(row).findByText("本次测试失败")).toBeInTheDocument();
    expect(within(row).getByText(/连接测试未通过/)).toBeInTheDocument();
    expect(updateModelConnection).not.toHaveBeenCalled();
  });

  it("refreshes the parent default selector after disabling an external connection", async () => {
    let current = { ...connection };
    vi.mocked(fetchModelConnections).mockImplementation(async () => ({
      items: [current],
      total: 1,
      warning: null,
    }));
    vi.mocked(updateModelConnection).mockImplementation(async () => {
      current = { ...current, enabled: false };
      return current;
    });
    renderPage();
    const row = await screen.findByRole("row", { name: /DeepSeek 对话/ });
    const more = within(row).getByRole("button", { name: /更多操作/ });
    await waitFor(() => expect(more).toBeEnabled());
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("button", { name: "停用" }));
    await within(row).findByText("已停用");
    await openEntry("模型设置", "内容生成与项目问答");
    expect(
      within(screen.getByRole("dialog", { name: "默认对话模型" })).queryByRole("option", {
        name: /DeepSeek 对话/,
      }),
    ).not.toBeInTheDocument();
  });

  it("opens reusable provider connections from the model page", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "供应商连接" }));
    expect(screen.getByRole("dialog", { name: "供应商连接" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建供应商连接" })).toBeInTheDocument();
  });

  it("keeps read-only overview access while hiding mutating actions", async () => {
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isGovernance: false,
      isProjectManager: false,
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "管理知识库配置" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "默认对话模型" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "管理知识库配置" }));
    expect(screen.queryByRole("button", { name: "配置" })).not.toBeInTheDocument();
  });

  it("routes project managers to their actionable knowledge-base workspace", async () => {
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isGovernance: false,
      isProjectManager: true,
    });
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      { ...models[0], credential_status: "missing" },
    ]);
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([
      {
        ...kb,
        migration: {
          ...kb.migration!,
          job_status: "completed",
          completed_count: 8,
          failed_count: 0,
        },
      },
    ]);
    renderPage();

    const heading = await screen.findByRole("heading", { name: "模型管理" });
    const header = heading.closest("header");
    expect(header).not.toBeNull();
    expect(screen.getByRole("button", { name: "管理知识库配置" })).toBeInTheDocument();
    expect(screen.queryByLabelText("连接运行状态")).not.toBeInTheDocument();
    expect(fetchModelConnections).not.toHaveBeenCalled();
    expect(fetchWeknoraDefaultModels).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "管理知识库配置" }));
    expect(screen.getByRole("region", { name: "管理知识库配置" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "接入知识库模型" })).not.toBeInTheDocument();
  });
});
