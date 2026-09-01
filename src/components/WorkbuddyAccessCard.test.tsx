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
    expect(screen.getAllByText("WorkBuddy 5.4.5", { exact: false })).toHaveLength(2);
    expect(screen.getByText(/https:\/\/<KAP_HOST>\/mcp/)).toBeInTheDocument();
    expect(api.fetchWorkbuddyConnectors).not.toHaveBeenCalled();
  });

  it("生成一次性 Bearer 配置并明确要求合并、完整重启和手动信任", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("button", { name: "生成远程配置" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("remote");
    const editor = await screen.findByLabelText("WorkBuddy MCP JSON 配置");
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
    await waitFor(() => expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("remote"));
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
