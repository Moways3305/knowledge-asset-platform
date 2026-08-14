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
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AdminWeKnoraModelsPage />
    </MemoryRouter>,
  );
}

describe("AdminWeKnoraModelsPage modal workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("keeps the landing page as a fixed connection workspace without growing lists", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "模型配置" })).toBeInTheDocument();
    expect(
      screen.queryByText("先处理不可用连接，再维护模型与知识库底座。"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "外部 LLM" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "WeKnora 底座" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "知识库配置" })).toBeInTheDocument();
    expect(screen.queryByText("交付方法库")).not.toBeInTheDocument();
    expect(screen.queryByText("internal-mapping-id")).not.toBeInTheDocument();
    expect(screen.queryByText("internal-job-id")).not.toBeInTheDocument();
  });

  it("opens searchable model lists in drawers and model creation in a task modal", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理外部 LLM" }));
    const drawer = screen.getByRole("dialog", { name: "管理外部 LLM" });
    expect(within(drawer).getByLabelText("搜索外部 LLM")).toBeInTheDocument();
    expect(within(drawer).getByLabelText("外部 LLM 状态")).toBeInTheDocument();
    expect(await within(drawer).findByText("DeepSeek 对话")).toBeInTheDocument();
    expect(within(drawer).queryByRole("form")).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "新增外部 LLM" }));
    expect(screen.getByRole("dialog", { name: "新增外部 LLM" })).toBeInTheDocument();
  });

  it("puts the searchable WeKnora list in a drawer and its editor in a task modal", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理 WeKnora 模型" }));
    const drawer = screen.getByRole("dialog", { name: "管理 WeKnora 模型" });
    expect(within(drawer).getByLabelText("搜索 WeKnora 模型")).toBeInTheDocument();
    expect(within(drawer).getByLabelText("WeKnora 模型类型")).toBeInTheDocument();
    expect(await within(drawer).findByText("qwen-plus")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "新增 WeKnora 模型" }));
    expect(screen.getByRole("dialog", { name: "新增 WeKnora 模型" })).toBeInTheDocument();
  });

  it("edits defaults in task modals instead of inline controls", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理外部 LLM" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑默认用途" }));
    const externalModal = screen.getByRole("dialog", { name: "编辑默认用途" });
    fireEvent.click(within(externalModal).getByRole("button", { name: "保存默认用途" }));
    await waitFor(() => expect(updateModelUsageAssignments).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "管理 WeKnora 模型" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑默认底座" }));
    const foundationModal = screen.getByRole("dialog", { name: "编辑默认底座" });
    fireEvent.click(within(foundationModal).getByRole("button", { name: "保存默认底座" }));
    await waitFor(() => expect(updateWeknoraDefaultModels).toHaveBeenCalledTimes(1));
  });

  it("filters KBs in a drawer and opens configuration as the only overlay", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "管理知识库配置" }));
    const drawer = screen.getByRole("dialog", { name: "管理知识库配置" });
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
    fireEvent.click(screen.getByRole("button", { name: "配置" }));
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
    const kbDrawer = screen.getByRole("dialog", { name: "管理知识库配置" });
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

  it("keeps read-only overview access while hiding mutating actions", async () => {
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isGovernance: false,
      isProjectManager: false,
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "管理知识库配置" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑默认用途" })).not.toBeInTheDocument();
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

    const heading = await screen.findByRole("heading", { name: "模型配置" });
    const header = heading.closest("header");
    expect(header).not.toBeNull();
    expect(within(header!).getByRole("button", { name: "管理知识库配置" })).toBeInTheDocument();
    expect(screen.queryByLabelText("连接运行状态")).not.toBeInTheDocument();
    expect(fetchModelConnections).not.toHaveBeenCalled();
    expect(fetchWeknoraDefaultModels).not.toHaveBeenCalled();

    fireEvent.click(within(header!).getByRole("button", { name: "管理知识库配置" }));
    expect(screen.getByRole("dialog", { name: "管理知识库配置" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增 WeKnora 模型" })).not.toBeInTheDocument();
  });
});
