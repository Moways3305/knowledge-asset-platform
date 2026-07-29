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
      filename: "kap-workbuddy-windows.exe",
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
      filename: "kap-workbuddy-arm64.pkg",
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
      filename: "kap-workbuddy-x64.pkg",
      sha256: "c".repeat(64),
      downloadUrl: "/mac-x64-download",
      releaseStatus: "production",
      signed: true,
      notarized: true,
    },
  ],
};

describe("WorkbuddyAccessCard", () => {
  beforeEach(() => {
    authState.authMe = { isBusinessUser: true };
    api.fetchWorkbuddyConnectors.mockReset();
    api.fetchWorkbuddyToken.mockReset();
    api.regenerateWorkbuddyToken.mockReset();
    api.revokeWorkbuddyToken.mockReset();
    api.fetchWorkbuddyConnectors.mockResolvedValue(manifest);
    api.fetchWorkbuddyToken.mockResolvedValue({
      enabled: false,
      boundUserName: "张三",
      lastRotatedAt: null,
      lastConnectedAt: null,
    });
  });

  it("不对非业务用户显示入口，也不请求下载或状态接口", () => {
    authState.authMe = { isBusinessUser: false };
    const { container } = render(<WorkbuddyAccessCard />);
    expect(container).toBeEmptyDOMElement();
    expect(api.fetchWorkbuddyConnectors).not.toHaveBeenCalled();
    expect(api.fetchWorkbuddyToken).not.toHaveBeenCalled();
  });

  it("展示 Windows 下载、版本、校验值和三步向导", async () => {
    render(<WorkbuddyAccessCard />);
    expect(await screen.findByRole("link", { name: "下载 Windows 连接器" })).toHaveAttribute(
      "href",
      "/windows-download",
    );
    expect(screen.getByText("版本 1.2.3")).toBeInTheDocument();
    expect(screen.getByText(/SHA-256 aaaaaaaaaaaa/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "安装 KAP 连接器" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "生成并导入个人配置" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "验证首次连接" })).toBeInTheDocument();
  });

  it("切换平台和 Mac 架构不会轮换 token", async () => {
    const user = userEvent.setup();
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("radio", { name: "macOS" }));
    expect(await screen.findByRole("link", { name: "下载 macOS 连接器" })).toHaveAttribute(
      "href",
      "/mac-arm-download",
    );
    await user.selectOptions(screen.getByLabelText("Mac 芯片"), "x64");
    expect(screen.getByRole("link", { name: "下载 macOS 连接器" })).toHaveAttribute(
      "href",
      "/mac-x64-download",
    );
    expect(api.regenerateWorkbuddyToken).not.toHaveBeenCalled();
  });

  it("分别生成所选平台配置且只展示对应配置", async () => {
    const user = userEvent.setup();
    api.regenerateWorkbuddyToken.mockResolvedValue({
      platform: "macos",
      mcpConfigJson:
        '{"mcpServers":{"kap":{"command":"/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector"}}}',
    });
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("radio", { name: "macOS" }));
    await user.click(screen.getByRole("button", { name: "生成个人配置" }));
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledWith("macos");
    const config = await screen.findByLabelText("macOS mcp.json 配置");
    expect((config as HTMLTextAreaElement).value).toContain(
      "/Applications/KAP WorkBuddy Connector.app",
    );
    expect(screen.queryByLabelText("Windows mcp.json 配置")).not.toBeInTheDocument();
    expect(screen.getAllByText("待导入").length).toBeGreaterThan(0);
  });

  it("只用服务端活动时间显示已连接", async () => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      enabled: true,
      boundUserName: "张三",
      lastRotatedAt: "2026-07-22T08:00:00Z",
      lastConnectedAt: "2026-07-28T08:00:00Z",
    });
    render(<WorkbuddyAccessCard />);
    expect((await screen.findAllByText("已连接")).length).toBeGreaterThan(0);
    expect(screen.getByText(/最近连接/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /检查连接|刷新连接状态/ })).not.toBeInTheDocument();
  });

  it("导入确认不会伪造连接，只重新读取服务端状态", async () => {
    const user = userEvent.setup();
    api.fetchWorkbuddyToken.mockResolvedValue({
      enabled: true,
      boundUserName: "张三",
      lastRotatedAt: "2026-07-22T08:00:00Z",
      lastConnectedAt: null,
    });
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("button", { name: "刷新连接状态" }));
    expect(api.fetchWorkbuddyToken).toHaveBeenCalledTimes(2);
    expect((await screen.findAllByText("等待首次连接")).length).toBeGreaterThan(0);
    expect(screen.queryByText("已连接")).not.toBeInTheDocument();
  });

  it("复制配置调用剪贴板且撤销清除一次性配置", async () => {
    const user = userEvent.setup();
    api.regenerateWorkbuddyToken.mockResolvedValue({
      platform: "windows",
      mcpConfigJson: '{"secret":"one-time"}',
    });
    api.revokeWorkbuddyToken.mockResolvedValue(undefined);
    api.fetchWorkbuddyToken
      .mockResolvedValueOnce({
        enabled: false,
        boundUserName: "张三",
        lastRotatedAt: null,
        lastConnectedAt: null,
      })
      .mockResolvedValue({
        enabled: true,
        boundUserName: "张三",
        lastRotatedAt: "2026-07-28T08:00:00Z",
        lastConnectedAt: null,
      });
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    render(<WorkbuddyAccessCard />);
    await user.click(await screen.findByRole("button", { name: "生成个人配置" }));
    await user.click(await screen.findByRole("button", { name: "复制配置" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('{"secret":"one-time"}'));
    await user.click(screen.getByRole("button", { name: "撤销配置" }));
    await waitFor(() => expect(api.revokeWorkbuddyToken).toHaveBeenCalledTimes(1));
    expect(screen.queryByLabelText("Windows mcp.json 配置")).not.toBeInTheDocument();
  });

  it("下载或生成失败展示安全恢复动作", async () => {
    api.fetchWorkbuddyConnectors.mockRejectedValue(new Error("private-url"));
    render(<WorkbuddyAccessCard />);
    const alerts = await screen.findAllByText("操作未成功，请稍后重试");
    expect(alerts.length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "重新获取" })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/private-url|\/api\/|workbuddy-token|40\d/);
  });
});
