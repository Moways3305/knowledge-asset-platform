import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WorkbuddyAccessCard from "./WorkbuddyAccessCard";

const authState: { authMe: { isBusinessUser: boolean } | null } = {
  authMe: { isBusinessUser: true },
};
vi.mock("../auth/AuthContext", () => ({ useAuth: () => authState }));
const api = vi.hoisted(() => ({
  fetchWorkbuddyConnectors: vi.fn(),
  fetchWorkbuddyToken: vi.fn(),
  downloadWorkbuddyConnector: vi.fn(),
  regenerateWorkbuddyToken: vi.fn(),
  revokeWorkbuddyToken: vi.fn(),
}));
vi.mock("../api/workbuddy", () => api);

const disabledStatus = {
  enabled: false,
  boundUserName: "张三",
  lastRotatedAt: null,
  lastConnectedAt: null,
  expiresAt: null,
  connectionMode: "remote",
};
const remoteConfig = {
  platform: "windows",
  mode: "remote",
  command: "",
  expiresAt: "2026-09-08T08:00:00Z",
  mcpConfigJson: JSON.stringify(
    {
      mcpServers: {
        kap: {
          type: "http",
          url: "https://knowledge.example.test/mcp",
          headers: { Authorization: "Bearer kgw_once" },
        },
      },
    },
    null,
    2,
  ),
};

describe("WorkbuddyAccessCard remote-first", () => {
  beforeEach(() => {
    authState.authMe = { isBusinessUser: true };
    api.fetchWorkbuddyToken.mockReset().mockResolvedValue(disabledStatus);
    api.fetchWorkbuddyConnectors.mockReset().mockResolvedValue({ version: "1.0", artifacts: [] });
    api.regenerateWorkbuddyToken.mockReset().mockResolvedValue(remoteConfig);
    api.revokeWorkbuddyToken.mockReset().mockResolvedValue(undefined);
  });

  it("非业务用户不显示入口或请求接口", () => {
    authState.authMe = { isBusinessUser: false };
    const { container } = render(<WorkbuddyAccessCard />);
    expect(container).toBeEmptyDOMElement();
    expect(api.fetchWorkbuddyToken).not.toHaveBeenCalled();
  });

  it("默认展示远程 HTTPS MCP，不预加载本地连接器", async () => {
    render(<WorkbuddyAccessCard />);
    expect(await screen.findByText(/无需安装连接器/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "MCP 接入" })).toBeInTheDocument();
    expect(screen.getByText(/https:\/\/<KAP_HOST>\/mcp/)).toBeInTheDocument();
    expect(api.fetchWorkbuddyConnectors).not.toHaveBeenCalled();
  });

  it("生成一次性 Bearer 配置并明确要求合并、完整重启和手动信任", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("button", { name: "生成远程配置" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith(
      "remote",
      "windows",
      undefined,
      false,
    );
    const editor = await screen.findByLabelText("MCP JSON 配置");
    expect(editor).toHaveValue(remoteConfig.mcpConfigJson);
    expect(screen.getByText(/只合并/)).toHaveTextContent("mcpServers.kap");
    expect(screen.getByText(/完全退出 WorkBuddy/)).toHaveTextContent("手动确认");
  });

  it("已有配置时先确认轮换，且旧 token 明确立即失效", async () => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      ...disabledStatus,
      enabled: true,
      expiresAt: "2026-09-08T08:00:00Z",
    });
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("button", { name: "重新生成远程配置" }));
    expect(screen.getByRole("alert")).toHaveTextContent("旧 token 和旧配置会立即失效");
    expect(api.regenerateWorkbuddyToken).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "确认重新生成" }));
    await waitFor(() =>
      expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith(
        "remote",
        "windows",
        undefined,
        false,
      ),
    );
  });

  it("操作权限必须显式勾选并随远程配置生成提交", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    const optIn = screen.getByRole("checkbox", { name: /允许智能体上传/ });
    await waitFor(() => expect(optIn).toBeEnabled());
    expect(optIn).not.toBeChecked();
    await user.click(optIn);
    await user.click(await screen.findByRole("button", { name: "生成远程配置" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("remote", "windows", undefined, true);
  });

  it("已有操作凭证重新生成时默认保留权限", async () => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      ...disabledStatus,
      enabled: true,
      operationsEnabled: true,
    });
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /允许智能体上传/ })).toBeChecked(),
    );
    await user.click(screen.getByRole("button", { name: "重新生成远程配置" }));
    expect(screen.getByRole("alert")).toHaveTextContent("权限保持不变");
    await user.click(screen.getByRole("button", { name: "确认重新生成" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("remote", "windows", undefined, true);
  });

  it.each([true, false])("权限从 %s 切换时明确显示变更并提交用户选择", async (existing) => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      ...disabledStatus,
      enabled: true,
      operationsEnabled: existing,
    });
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    const checkbox = screen.getByRole("checkbox", { name: /允许智能体上传/ });
    await waitFor(() => expect(checkbox).toBeEnabled());
    expect(checkbox).toHaveProperty("checked", existing);
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "重新生成远程配置" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      existing ? "将撤销操作权限" : "将新增操作权限",
    );
    expect(api.regenerateWorkbuddyToken).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "确认重新生成" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith(
      "remote",
      "windows",
      undefined,
      !existing,
    );
  });

  it("状态尚未加载时禁止生成凭证", () => {
    api.fetchWorkbuddyToken.mockReturnValue(new Promise(() => {}));
    render(<WorkbuddyAccessCard />);
    expect(screen.getByRole("checkbox", { name: /允许智能体上传/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成远程配置" })).toBeDisabled();
    expect(api.regenerateWorkbuddyToken).not.toHaveBeenCalled();
  });

  it("只有展开兼容区才读取本地 Connector 清单", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await screen.findByText(/无需安装连接器/);
    expect(api.fetchWorkbuddyConnectors).not.toHaveBeenCalled();
    await user.click(screen.getByText("兼容模式：使用本地 Connector"));
    await waitFor(() => expect(api.fetchWorkbuddyConnectors).toHaveBeenCalledTimes(1));
  });

  it("兼容模式仍可提交本地 Connector 自定义路径", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByText("兼容模式：使用本地 Connector"));
    const path = String.raw`D:\Custom Apps\kap-workbuddy-connector.exe`;
    await user.type(screen.getByLabelText("本地连接器自定义路径"), path);
    await user.click(screen.getByRole("button", { name: "生成本地配置" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("local_connector", "windows", path);
  });

  it("只根据服务端真实活动时间显示已连接", async () => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      ...disabledStatus,
      enabled: true,
      expiresAt: "2026-09-08T08:00:00Z",
      lastConnectedAt: "2026-09-01T08:00:00Z",
    });
    render(<WorkbuddyAccessCard />);
    expect(await screen.findByText("已连接")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新连接状态" })).not.toBeInTheDocument();
  });
});
