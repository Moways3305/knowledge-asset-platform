import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
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
});
