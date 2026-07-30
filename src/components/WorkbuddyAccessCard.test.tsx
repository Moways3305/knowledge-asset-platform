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

const manifest = {
  version: "1.2.3",
  artifacts: [
    {
      platform: "windows",
      architecture: "x64",
      version: "1.2.3",
      filename: "kap-workbuddy-connector-1.2.3-windows-x64-setup.exe",
      sha256: "a".repeat(64),
      downloadUrl: "/windows-download",
      releaseStatus: "production",
      signed: true,
      notarized: false,
    },
    {
      platform: "macos",
      architecture: "arm64",
      version: "1.2.3",
      filename: "kap-workbuddy-connector-1.2.3-macos-arm64.pkg",
      sha256: "b".repeat(64),
      downloadUrl: "/mac-arm-download",
      releaseStatus: "production",
      signed: true,
      notarized: true,
    },
    {
      platform: "macos",
      architecture: "x64",
      version: "1.2.3",
      filename: "kap-workbuddy-connector-1.2.3-macos-x64.pkg",
      sha256: "c".repeat(64),
      downloadUrl: "/mac-x64-download",
      releaseStatus: "production",
      signed: true,
      notarized: true,
    },
  ],
};

const disabledStatus = {
  enabled: false,
  boundUserName: "张三",
  lastRotatedAt: null,
  lastConnectedAt: null,
};

describe("WorkbuddyAccessCard", () => {
  beforeEach(() => {
    authState.authMe = { isBusinessUser: true };
    api.fetchWorkbuddyConnectors.mockReset().mockResolvedValue(manifest);
    api.fetchWorkbuddyToken.mockReset().mockResolvedValue(disabledStatus);
    api.downloadWorkbuddyConnector.mockReset().mockResolvedValue(new Blob(["connector"]));
    api.regenerateWorkbuddyToken.mockReset();
    api.revokeWorkbuddyToken.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:connector"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  it("不向非业务用户显示入口或请求接口", () => {
    authState.authMe = { isBusinessUser: false };
    const { container } = render(<WorkbuddyAccessCard />);
    expect(container).toBeEmptyDOMElement();
    expect(api.fetchWorkbuddyConnectors).not.toHaveBeenCalled();
    expect(api.fetchWorkbuddyToken).not.toHaveBeenCalled();
  });

  it("让用户明确确认 Windows 平台、安装包和默认命令", async () => {
    render(<WorkbuddyAccessCard />);
    expect(
      await screen.findByRole("button", {
        name: "下载 kap-workbuddy-connector-1.2.3-windows-x64-setup.exe",
      }),
    ).toBeEnabled();
    expect(screen.getByText("Windows · x64 · 版本 1.2.3")).toBeInTheDocument();
    expect(screen.getByText("将生成 Windows 配置")).toBeInTheDocument();
    expect(
      screen.getByText(
        String.raw`C:\Program Files\KAP WorkBuddy Connector\kap-workbuddy-connector.exe`,
      ),
    ).toBeInTheDocument();
  });

  it("下载开始、失败与重试反馈都不误报安装或连接", async () => {
    const user = userEvent.setup();
    api.downloadWorkbuddyConnector.mockRejectedValueOnce(new Error("network"));
    render(<WorkbuddyAccessCard />);

    await user.click(
      await screen.findByRole("button", {
        name: "下载 kap-workbuddy-connector-1.2.3-windows-x64-setup.exe",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("下载未完成");
    expect(screen.getByRole("alert")).toHaveTextContent("重试");
    expect(screen.getAllByText("未生成").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "重试下载" }));
    expect(await screen.findByRole("status")).toHaveTextContent("下载已开始");
    expect(screen.getByRole("status")).toHaveTextContent("无法确认文件是否已保存或安装");
    expect(api.downloadWorkbuddyConnector).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("已安装")).not.toBeInTheDocument();
  });

  it("切换 macOS 架构只改变匹配的下载包，不轮换 token", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("radio", { name: "macOS" }));
    expect(
      screen.getByRole("button", {
        name: "下载 kap-workbuddy-connector-1.2.3-macos-arm64.pkg",
      }),
    ).toBeEnabled();
    expect(screen.getByText("将生成 macOS 配置")).toBeInTheDocument();
    expect(screen.queryByText(/\.exe$/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Mac 芯片架构"), "x64");
    expect(
      screen.getByRole("button", {
        name: "下载 kap-workbuddy-connector-1.2.3-macos-x64.pkg",
      }),
    ).toBeEnabled();
    expect(api.regenerateWorkbuddyToken).not.toHaveBeenCalled();
  });

  it("将自定义 Windows 路径仅在明确生成时提交并保留 JSON 转义", async () => {
    const user = userEvent.setup();
    const custom = String.raw`D:\Custom Apps\KAP Team\kap-workbuddy-connector.exe`;
    const json = JSON.stringify({
      mcpServers: { kap: { command: custom, env: { KAP_AGENT_TOKEN: "one-time" } } },
    });
    api.regenerateWorkbuddyToken.mockResolvedValue({
      platform: "windows",
      command: custom,
      mcpConfigJson: json,
    });
    render(<WorkbuddyAccessCard />);

    await user.click(await screen.findByRole("radio", { name: "使用自定义连接器路径" }));
    await user.type(screen.getByLabelText("连接器可执行文件完整路径"), custom);
    expect(api.regenerateWorkbuddyToken).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "生成个人配置" }));

    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("windows", custom);
    expect(await screen.findByLabelText("Windows mcp.json 配置")).toHaveValue(json);
    expect(JSON.parse(json).mcpServers.kap.command).toBe(custom);
  });

  it("已有一次性配置时切换平台不会改写配置，确认后才重新生成", async () => {
    const user = userEvent.setup();
    const windowsCommand = String.raw`C:\Program Files\KAP WorkBuddy Connector\kap-workbuddy-connector.exe`;
    const macCommand =
      "/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector";
    api.regenerateWorkbuddyToken
      .mockResolvedValueOnce({
        platform: "windows",
        command: windowsCommand,
        mcpConfigJson: JSON.stringify({ command: windowsCommand }),
      })
      .mockResolvedValueOnce({
        platform: "macos",
        command: macCommand,
        mcpConfigJson: JSON.stringify({ command: macCommand }),
      });
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("button", { name: "生成个人配置" }));
    await screen.findByLabelText("Windows mcp.json 配置");

    await user.click(screen.getByRole("radio", { name: "macOS" }));
    expect(screen.getByLabelText("Windows mcp.json 配置")).toHaveValue(
      JSON.stringify({ command: windowsCommand }),
    );
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "重新生成配置" }));
    expect(screen.getByText(/旧 token 和旧配置失效/)).toBeInTheDocument();
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "确认重新生成配置" }));
    await waitFor(() =>
      expect(api.regenerateWorkbuddyToken).toHaveBeenLastCalledWith("macos", undefined),
    );
  });

  it("显示已验证的 v5.3.5 入口并提醒只合并 kap 节点", async () => {
    render(<WorkbuddyAccessCard />);
    await screen.findByRole("button", {
      name: "下载 kap-workbuddy-connector-1.2.3-windows-x64-setup.exe",
    });
    expect(screen.getByText(/已验证于 WorkBuddy v5\.3\.5/)).toBeInTheDocument();
    expect(screen.getByText("专家·技能·连接器")).toBeInTheDocument();
    expect(screen.getByText("自定义连接器")).toBeInTheDocument();
    expect(screen.getByText("配置 MCP")).toBeInTheDocument();
    expect(screen.getByText(/只替换或合并/)).toHaveTextContent("mcpServers.kap");
    expect(screen.getByText(/请保留其他已有 MCP 节点/)).toBeInTheDocument();
    expect(screen.queryByText(/设置 → MCP 服务 → 导入配置/)).not.toBeInTheDocument();
  });

  it("只根据服务端真实活动时间显示已连接", async () => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      enabled: true,
      boundUserName: "张三",
      lastRotatedAt: "2026-07-22T08:00:00Z",
      lastConnectedAt: "2026-07-28T08:00:00Z",
    });
    render(<WorkbuddyAccessCard />);
    expect((await screen.findAllByText("已连接")).length).toBeGreaterThan(0);
    expect(screen.getByText(/最近连接/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新连接状态" })).not.toBeInTheDocument();
  });
});
