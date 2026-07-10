import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AdminWeKnoraModelsPage from "./AdminWeKnoraModelsPage";
import {
  checkWeknoraModel,
  createWeknoraModel,
  deleteWeknoraModel,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  fetchWeknoraProviders,
  updateWeknoraKbInit,
  updateWeknoraModel,
} from "../api/admin";
import {
  fetchDefaultModels,
  fetchGenerationModels,
  updateDefaultModels,
} from "../api/weknoraModels";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities: { isAdmin: true } }),
}));

vi.mock("../api/admin", () => ({
  checkWeknoraModel: vi.fn(),
  createWeknoraModel: vi.fn(),
  deleteWeknoraModel: vi.fn(),
  fetchWeknoraKbConfigs: vi.fn(),
  fetchWeknoraModels: vi.fn(),
  fetchWeknoraProviders: vi.fn(),
  updateWeknoraKbInit: vi.fn(),
  updateWeknoraModel: vi.fn(),
}));

vi.mock("../api/weknoraModels", () => ({
  fetchDefaultModels: vi.fn(),
  fetchGenerationModels: vi.fn(),
  createGenerationModel: vi.fn(),
  updateGenerationModel: vi.fn(),
  deleteGenerationModel: vi.fn(),
  testGenerationModel: vi.fn(),
  updateGenerationDefaultModel: vi.fn(),
  updateDefaultModels: vi.fn(),
}));

const models = [
  {
    model_ref: "ref-chat",
    name: "qwen-plus",
    type: "chat",
    source: "remote",
    provider: "aliyun",
    enabled: true,
    is_builtin: false,
    description: null,
  },
];

const defaultModels = {
  embedding: null,
  rerank: null,
  chat: null,
  multimodal: null,
  updated_at: null,
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
    vi.mocked(fetchWeknoraModels).mockResolvedValue(models);
    vi.mocked(fetchWeknoraProviders).mockResolvedValue([
      { value: "aliyun", label: "阿里云", description: null, model_types: ["chat"] },
    ]);
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([]);
    vi.mocked(fetchDefaultModels).mockResolvedValue(defaultModels);
    vi.mocked(fetchGenerationModels).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(updateDefaultModels).mockResolvedValue(defaultModels);
    vi.mocked(createWeknoraModel).mockResolvedValue({
      model_ref: "new-ref",
      name: "x",
      type: "chat",
      provider: "aliyun",
      status: "ok",
    });
    vi.mocked(updateWeknoraModel).mockResolvedValue({
      model_ref: "ref-chat",
      name: "qwen-plus",
      type: "chat",
      provider: "aliyun",
      status: "ok",
    });
    vi.mocked(checkWeknoraModel).mockResolvedValue({
      success: true,
      message: "后端连通性校验通过",
    });
    vi.mocked(deleteWeknoraModel).mockResolvedValue({ deleted: true });
    vi.mocked(updateWeknoraKbInit).mockResolvedValue({
      mapping_id: "m1",
      mapping_status: "active",
      updated: true,
    });
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("uses production status copy instead of claiming connectivity", async () => {
    renderPage();
    expect(await screen.findByText("已启用")).toBeInTheDocument();
    expect(screen.queryByText("可用")).not.toBeInTheDocument();
  });

  it("adds anti-autofill attributes to model secret fields", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("新增模型"));

    const apiUrl = screen.getByLabelText("API 地址");
    const apiKey = screen.getByLabelText("访问密钥");

    expect(apiUrl).toHaveAttribute("name", "kap_model_endpoint");
    expect(apiUrl).toHaveAttribute("autocomplete", "off");
    expect(apiUrl).toHaveAttribute("data-lpignore", "true");
    expect(apiUrl).toHaveAttribute("data-1p-ignore", "true");
    expect(apiKey).toHaveAttribute("name", "kap_model_secret");
    expect(apiKey).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByRole("textbox", { name: "模型名称" }).closest("form")).toHaveAttribute(
      "autocomplete",
      "off",
    );
  });

  it("blocks an email-shaped API URL before saving", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("新增模型"));

    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "qwen" } });
    fireEvent.change(screen.getByLabelText("API 地址"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("访问密钥"), { target: { value: "sk-secret" } });
    fireEvent.click(screen.getByText("创建模型"));

    expect(await screen.findByText("API 地址必须以 http:// 或 https:// 开头")).toBeInTheDocument();
    expect(createWeknoraModel).not.toHaveBeenCalled();
  });

  it("omits blank API URL and key while editing so existing values are kept", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("编辑"));
    fireEvent.click(screen.getByText("保存修改"));

    await waitFor(() => expect(updateWeknoraModel).toHaveBeenCalled());
    expect(updateWeknoraModel).toHaveBeenCalledWith(
      "ref-chat",
      expect.not.objectContaining({
        base_url: expect.anything(),
        api_key: expect.anything(),
      }),
    );
  });

  it("disables connectivity test in edit mode until URL and key are re-entered", async () => {
    renderPage();
    fireEvent.click(await screen.findByText("编辑"));

    expect(
      screen.getByText("编辑已有模型时，需重新输入 API 地址和访问密钥后才能测试。"),
    ).toBeInTheDocument();
    expect(screen.getByText("连通性测试")).toBeDisabled();
  });

  it("shows busy state and duration for connectivity checks", async () => {
    vi.mocked(checkWeknoraModel).mockImplementation(
      () =>
        new Promise((resolve) => {
          window.setTimeout(() => resolve({ success: true, message: "后端连通性校验通过" }), 10);
        }),
    );
    renderPage();
    fireEvent.click(await screen.findByText("新增模型"));

    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "qwen" } });
    fireEvent.change(screen.getByLabelText("API 地址"), {
      target: { value: "https://api.example.com/v1" },
    });
    fireEvent.change(screen.getByLabelText("访问密钥"), { target: { value: "sk-secret" } });
    fireEvent.click(screen.getByText("连通性测试"));

    expect(screen.getAllByText("测试中...").length).toBeGreaterThan(0);
    expect(await screen.findByText(/耗时 \d+ms/)).toBeInTheDocument();
    expect(checkWeknoraModel).toHaveBeenCalledWith(
      expect.objectContaining({
        api_url: "https://api.example.com/v1",
        api_key: "sk-secret",
        model: "qwen",
      }),
    );
  });
});
