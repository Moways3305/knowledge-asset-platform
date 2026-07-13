import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  updateModelUsageAssignments,
} from "../api/weknoraModels";
import UnifiedModelConnectionsSection from "./UnifiedModelConnectionsSection";

vi.mock("../api/weknoraModels", () => ({
  createModelConnection: vi.fn(),
  fetchModelConnections: vi.fn(),
  fetchModelUsageAssignments: vi.fn(),
  testModelConnection: vi.fn(),
  updateModelConnection: vi.fn(),
  updateModelUsageAssignments: vi.fn(),
}));

const chat = {
  model_ref: "chat-safe-ref",
  display_name: "共享对话模型",
  capability_type: "chat" as const,
  provider: "deepseek",
  model_name: "deepseek-chat",
  enabled: true,
  health_status: "registered",
  available_usages: ["content_generation", "knowledge_chat"] as (
    | "content_generation"
    | "knowledge_chat"
  )[],
  legacy_adapter: false,
};

const emptyUsages = {
  content_generation: null,
  knowledge_embedding: null,
  knowledge_chat: null,
  knowledge_rerank: null,
};

describe("UnifiedModelConnectionsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
    vi.mocked(fetchModelConnections).mockResolvedValue({ items: [chat], total: 1, warning: null });
    vi.mocked(fetchModelUsageAssignments).mockResolvedValue(emptyUsages);
    vi.mocked(updateModelUsageAssignments).mockResolvedValue({
      ...emptyUsages,
      content_generation: {
        model_ref: chat.model_ref,
        display_name: chat.display_name,
        capability_type: "chat",
      },
      knowledge_chat: {
        model_ref: chat.model_ref,
        display_name: chat.display_name,
        capability_type: "chat",
      },
    });
  });

  it("assigns one chat connection to content generation and knowledge chat", async () => {
    render(<UnifiedModelConnectionsSection canEdit />);
    const content = await screen.findByLabelText("内容生成");
    const knowledgeChat = screen.getByLabelText("知识库默认问答");
    fireEvent.change(content, { target: { value: chat.model_ref } });
    fireEvent.change(knowledgeChat, { target: { value: chat.model_ref } });
    fireEvent.click(screen.getByText("保存模型用途"));
    await waitFor(() =>
      expect(updateModelUsageAssignments).toHaveBeenCalledWith(
        expect.objectContaining({
          content_generation_ref: chat.model_ref,
          knowledge_chat_ref: chat.model_ref,
        }),
      ),
    );
  });

  it("keeps governance controls read-only and hides management actions", async () => {
    render(<UnifiedModelConnectionsSection canEdit={false} />);
    expect(await screen.findByLabelText("内容生成")).toBeDisabled();
    expect(screen.queryByText("新增模型连接")).not.toBeInTheDocument();
    expect(screen.queryByText("编辑")).not.toBeInTheDocument();
    expect(screen.getAllByText("当前身份仅可查看，修改需系统管理员。").length).toBeGreaterThan(0);
  });

  it("shows exactly seven labelled business controls without autofill decoys", async () => {
    const { container } = render(<UnifiedModelConnectionsSection canEdit />);
    fireEvent.click(await screen.findByText("新增模型连接"));

    const labels = [
      "显示名称",
      "模型能力",
      "Provider",
      "模型名称",
      "API 地址",
      "API key",
      "启用状态",
    ];
    for (const label of labels) {
      expect(screen.getByLabelText(label)).toBeVisible();
    }

    const form = container.querySelector(".ws-form-grid");
    expect(form?.querySelectorAll(".ws-form-field")).toHaveLength(7);
    expect(form?.querySelectorAll(".form-decoy")).toHaveLength(0);
    expect(screen.queryByRole("textbox", { name: "" })).not.toBeInTheDocument();
  });

  it("restores controlled values when external autofill mutates the DOM without events", async () => {
    render(<UnifiedModelConnectionsSection canEdit />);
    fireEvent.click(await screen.findByText("新增模型连接"));

    const injected = [
      screen.getByLabelText<HTMLInputElement>("显示名称"),
      screen.getByLabelText<HTMLInputElement>("模型名称"),
      screen.getByLabelText<HTMLInputElement>("API 地址"),
      screen.getByLabelText<HTMLInputElement>("API key"),
    ];
    for (const control of injected) control.value = "externally-injected";

    await waitFor(() => expect(injected.every((control) => control.value === "")).toBe(true));
    expect(screen.getByRole("alert")).toHaveTextContent("检测到浏览器自动填充");
    fireEvent.click(screen.getByText("保存模型连接"));
    expect(createModelConnection).not.toHaveBeenCalled();
  });

  it("submits one reviewed payload after normal controlled input", async () => {
    vi.mocked(createModelConnection).mockResolvedValue(chat);
    render(<UnifiedModelConnectionsSection canEdit />);
    fireEvent.click(await screen.findByText("新增模型连接"));

    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "主对话模型" } });
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "deepseek-chat" } });
    fireEvent.change(screen.getByLabelText("API 地址"), {
      target: { value: "https://api.example.com/v1" },
    });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "reviewed-secret" } });
    fireEvent.click(screen.getByText("保存模型连接"));

    await waitFor(() => expect(createModelConnection).toHaveBeenCalledTimes(1));
    expect(createModelConnection).toHaveBeenCalledWith({
      display_name: "主对话模型",
      capability_type: "chat",
      provider: "deepseek",
      model_name: "deepseek-chat",
      base_url: "https://api.example.com/v1",
      api_key: "reviewed-secret",
      enabled: true,
    });
  });
});
