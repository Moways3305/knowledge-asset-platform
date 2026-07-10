import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GenerationModelsSection from "./GenerationModelsSection";

const api = vi.hoisted(() => ({
  fetchGenerationModels: vi.fn(),
  createGenerationModel: vi.fn(),
  updateGenerationModel: vi.fn(),
  deleteGenerationModel: vi.fn(),
  testGenerationModel: vi.fn(),
  updateGenerationDefaultModel: vi.fn(),
}));
vi.mock("../api/weknoraModels", () => api);

const model = {
  model_ref: "safe_ref_a",
  display_name: "DeepSeek 内容生成",
  provider: "deepseek",
  model_name: "deepseek-chat",
  enabled: true,
  is_default: true,
};

describe("GenerationModelsSection", () => {
  beforeEach(() => {
    api.fetchGenerationModels.mockReset().mockResolvedValue({ items: [model], total: 1 });
    api.createGenerationModel.mockReset().mockResolvedValue(model);
    api.updateGenerationModel.mockReset().mockResolvedValue(model);
    api.deleteGenerationModel.mockReset().mockResolvedValue({ deleted: true });
    api.testGenerationModel.mockReset().mockResolvedValue({
      success: true,
      message: "连接测试成功",
      duration_ms: 18,
    });
    api.updateGenerationDefaultModel.mockReset().mockResolvedValue({
      current_default: model,
      configured: true,
    });
  });

  it("空状态提供可用的新增内容生成模型入口", async () => {
    api.fetchGenerationModels.mockResolvedValue({ items: [], total: 0 });
    render(<GenerationModelsSection canEdit={true} />);
    await waitFor(() => expect(screen.getByText("尚未配置内容生成模型")).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: "新增内容生成模型" }).length).toBeGreaterThan(0);
  });

  it("新增时单向提交敏感字段，保存后列表只显示安全字段", async () => {
    api.fetchGenerationModels.mockResolvedValue({ items: [], total: 0 });
    render(<GenerationModelsSection canEdit={true} />);
    await waitFor(() => screen.getByText("尚未配置内容生成模型"));
    await userEvent.click(screen.getAllByRole("button", { name: "新增内容生成模型" })[0]);
    const fields = screen.getAllByRole("textbox");
    await userEvent.type(
      fields.find((f) => f.parentElement?.textContent?.includes("显示名称"))!,
      "测试模型",
    );
    await userEvent.type(
      fields.find((f) => f.parentElement?.textContent?.includes("模型名称"))!,
      "model-x",
    );
    await userEvent.type(
      fields.find((f) => f.parentElement?.textContent?.includes("API 地址"))!,
      "https://api.example.com/v1",
    );
    await userEvent.type(screen.getByLabelText("API key"), "SECRET-LIKE");
    await userEvent.click(screen.getByRole("button", { name: "保存内容生成模型" }));
    await waitFor(() => expect(api.createGenerationModel).toHaveBeenCalledTimes(1));
    expect(api.createGenerationModel.mock.calls[0][0].api_key).toBe("SECRET-LIKE");
  });

  it("编辑时不回显 API 地址或 API key，并可安全测试连接", async () => {
    render(<GenerationModelsSection canEdit={true} />);
    await waitFor(() => expect(screen.getAllByText("DeepSeek 内容生成").length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(screen.getByLabelText("API key")).toHaveValue("");
    expect(screen.getByPlaceholderText("留空表示保持原地址")).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "关闭" }));
    await userEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(screen.getByText("连接测试成功（18 ms）")).toBeInTheDocument());
  });

  it("只读角色没有新增、编辑、删除或默认保存控件", async () => {
    render(<GenerationModelsSection canEdit={false} />);
    await waitFor(() => expect(screen.getAllByText("DeepSeek 内容生成").length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: "新增内容生成模型" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("平台默认内容生成模型")).toBeDisabled();
  });
});
