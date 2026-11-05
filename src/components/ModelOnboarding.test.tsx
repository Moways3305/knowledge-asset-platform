import { createRef } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ModelOnboarding, { type ModelOnboardingHandle } from "./ModelOnboarding";
import * as api from "../api/modelRegistry";
import { ApiError } from "../api/http";
import type { ProviderConnection, RegistryModel } from "../types/modelRegistry";
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
const connection: ProviderConnection = {
  id: "connection-1",
  name: "硅基流动共用连接",
  provider: "siliconflow",
  config_version: 1,
  credential_version: 1,
  capabilities: ["chat", "embedding", "rerank"],
  protocols: { chat: "openai", embedding: "openai", rerank: "rerank" },
  model_count: 2,
  affected_models: ["嵌入模型", "重排模型"],
};
const draft: RegistryModel = {
  id: "model-1",
  request_id: "request-1",
  connection_id: connection.id,
  connection_name: connection.name,
  provider: "siliconflow",
  display_name: "项目问答",
  model_name: "test-chat",
  capability: "chat",
  dimension: null,
  usages: ["business"],
  version: 1,
  signature: "1:1:1",
  test_status: "untested",
  test_code: null,
  test_message: "当前配置尚未验证。",
  tested_at: null,
  test_duration_ms: null,
  observed_dimension: null,
  bindings: {
    business: { status: "pending", current: false, error_code: null, message: "尚未接入" },
  },
  external_ref: null,
  knowledge_ref: null,
  busy: false,
};
const verified: RegistryModel = {
  ...draft,
  test_status: "verified",
  test_message: "当前配置验证通过。",
  tested_at: "2026-11-05T00:00:00Z",
};
const ready: RegistryModel = {
  ...verified,
  external_ref: "external-ref",
  bindings: {
    business: { status: "ready", current: true, error_code: null, message: "已接入当前版本" },
  },
};
const inventoryChanged = vi.fn();
const runtimeChanged = vi.fn();
async function setup() {
  const ref = createRef<ModelOnboardingHandle>();
  render(
    <ModelOnboarding
      managementRef={ref}
      onInventory={inventoryChanged}
      onChanged={runtimeChanged}
      refreshSignal={0}
      canEdit={true}
    />,
  );
  await waitFor(() => expect(inventoryChanged).toHaveBeenCalled());
  return ref;
}
async function fillModel(ref: React.RefObject<ModelOnboardingHandle>) {
  act(() => ref.current?.create());
  fireEvent.change(screen.getByLabelText("已有供应商连接"), { target: { value: connection.id } });
  fireEvent.change(screen.getByLabelText("展示名称"), { target: { value: draft.display_name } });
  fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: draft.model_name } });
}
describe("ModelOnboarding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.fetchRegistry).mockResolvedValue({ connections: [connection], models: [] });
    vi.mocked(api.fetchProviderCatalog).mockResolvedValue({
      providers: [
        {
          id: "deepseek",
          name: "DeepSeek",
          base: "https://api.deepseek.com/v1",
          capabilities: ["chat"],
        },
        {
          id: "siliconflow",
          name: "硅基流动",
          base: "https://api.siliconflow.cn/v1",
          capabilities: ["chat", "embedding", "rerank"],
        },
        {
          id: "custom",
          name: "自定义兼容服务",
          base: "",
          capabilities: ["chat", "embedding", "rerank"],
        },
      ],
    });
    vi.mocked(api.createRegisteredModel).mockResolvedValue(draft);
    vi.mocked(api.updateRegisteredModel).mockResolvedValue(draft);
    vi.mocked(api.verifyRegisteredModel).mockResolvedValue(verified);
    vi.mocked(api.syncRegisteredModel).mockResolvedValue(ready);
    vi.mocked(api.updateProviderConnection).mockResolvedValue({
      ...connection,
      config_version: 2,
      credential_version: 2,
    });
  });
  it("saves a draft without testing or binding it", async () => {
    const ref = await setup();
    await fillModel(ref);
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(api.createRegisteredModel).toHaveBeenCalledTimes(1));
    expect(api.verifyRegisteredModel).not.toHaveBeenCalled();
    expect(api.syncRegisteredModel).not.toHaveBeenCalled();
    expect(await screen.findByText(/草稿已保存/)).toBeInTheDocument();
    expect(vi.mocked(api.createRegisteredModel).mock.calls[0][0]).not.toHaveProperty("api_key");
  });
  it("verifies the persisted version before binding and refreshes runtime options", async () => {
    const ref = await setup();
    await fillModel(ref);
    fireEvent.click(screen.getByRole("button", { name: "验证并接入" }));
    expect(await screen.findByText(/模型已接入。/)).toBeInTheDocument();
    expect(api.verifyRegisteredModel).toHaveBeenCalledWith(draft);
    expect(api.syncRegisteredModel).toHaveBeenCalledWith(verified);
    expect(runtimeChanged).toHaveBeenCalled();
    expect(api.createRegisteredModel).toHaveBeenCalledTimes(1);
  });
  it("keeps a failed validation as a draft without provisioning a runtime", async () => {
    vi.mocked(api.verifyRegisteredModel).mockResolvedValue({
      ...draft,
      test_status: "failed",
      test_code: "access_denied",
      test_message: "服务商拒绝访问",
    });
    const ref = await setup();
    await fillModel(ref);
    fireEvent.click(screen.getByRole("button", { name: "验证并接入" }));
    expect(await screen.findByText("服务商拒绝访问")).toBeInTheDocument();
    expect(api.syncRegisteredModel).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "管理模型接入" })).toBeInTheDocument();
  });
  it("retries a verified partial binding without recreating or revalidating the model", async () => {
    const ref = await setup();
    act(() =>
      ref.current?.retry({
        ...verified,
        bindings: {
          business: {
            status: "failed",
            current: false,
            error_code: "sync_failed",
            message: "可重试",
          },
        },
      }),
    );
    expect(await screen.findByText(/模型已接入。/)).toBeInTheDocument();
    expect(api.syncRegisteredModel).toHaveBeenCalledTimes(1);
    expect(api.createRegisteredModel).not.toHaveBeenCalled();
    expect(api.verifyRegisteredModel).not.toHaveBeenCalled();
  });
  it("rechecks an already connected model and does not present a failed probe as success", async () => {
    vi.mocked(api.verifyRegisteredModel).mockResolvedValue({
      ...ready,
      test_status: "failed",
      test_code: "credentials",
      test_message: "凭据已失效",
    });
    const ref = await setup();
    act(() => ref.current?.retry(ready));
    expect(await screen.findByText(/验证未通过。/)).toBeInTheDocument();
    expect(api.verifyRegisteredModel).toHaveBeenCalledWith(ready);
    expect(api.syncRegisteredModel).not.toHaveBeenCalled();
    expect(screen.queryByText(/模型已接入。/)).not.toBeInTheDocument();
  });
  it("shows affected models when rotating a shared connection and preserves blank secrets", async () => {
    const ref = await setup();
    act(() => ref.current?.connections());
    fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
    expect(screen.getByText(/影响 2 个模型：嵌入模型、重排模型/)).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "保存连接" }));
    await waitFor(() => expect(api.updateProviderConnection).toHaveBeenCalled());
    expect(vi.mocked(api.updateProviderConnection).mock.calls[0][1]).not.toHaveProperty("api_key");
    expect(vi.mocked(api.updateProviderConnection).mock.calls[0][1]).not.toHaveProperty(
      "endpoints",
    );
  });
  it("retains the same request token after a failed draft response", async () => {
    vi.mocked(api.createRegisteredModel).mockRejectedValueOnce(new ApiError(503, "暂时不可用"));
    const ref = await setup();
    await fillModel(ref);
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByText("暂时不可用")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "保存草稿" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(api.createRegisteredModel).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.createRegisteredModel).mock.calls[0][0].request_id).toBe(
      vi.mocked(api.createRegisteredModel).mock.calls[1][0].request_id,
    );
  });
  it("limits capability and usage selection to the selected connection", async () => {
    vi.mocked(api.fetchRegistry).mockResolvedValue({
      connections: [{ ...connection, capabilities: ["embedding"] }],
      models: [],
    });
    const ref = await setup();
    await fillModel(ref);
    expect(screen.getByLabelText("接入模型能力")).toHaveValue("embedding");
    expect(screen.getByRole("checkbox", { name: /内容生成与项目问答/ })).toBeDisabled();
    expect(
      within(screen.getByLabelText("接入模型能力")).queryByRole("option", { name: "重排" }),
    ).not.toBeInTheDocument();
  });
});
