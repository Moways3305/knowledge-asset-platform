import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WorkbuddyAccessCard from "./WorkbuddyAccessCard";

// 可变 mock 身份：驱动"业务用户可见 / 非业务用户不可见"分支。
const authState: { authMe: { isBusinessUser: boolean } | null } = {
  authMe: { isBusinessUser: true },
};
vi.mock("../auth/AuthContext", () => ({ useAuth: () => authState }));

const api = vi.hoisted(() => ({
  fetchWorkbuddyToken: vi.fn(),
  regenerateWorkbuddyToken: vi.fn(),
  revokeWorkbuddyToken: vi.fn(),
}));
vi.mock("../api/workbuddy", () => api);

describe("WorkbuddyAccessCard", () => {
  beforeEach(() => {
    authState.authMe = { isBusinessUser: true };
    api.fetchWorkbuddyToken.mockReset();
    api.regenerateWorkbuddyToken.mockReset();
    api.revokeWorkbuddyToken.mockReset();
    api.fetchWorkbuddyToken.mockResolvedValue({
      enabled: false,
      boundUserName: "张三",
      lastRotatedAt: null,
    });
  });

  it("不对非业务用户显示入口", () => {
    authState.authMe = { isBusinessUser: false };
    const { container } = render(<WorkbuddyAccessCard />);
    expect(container).toBeEmptyDOMElement();
  });

  it("业务用户未生成时显示生成入口", async () => {
    render(<WorkbuddyAccessCard />);
    expect(await screen.findByRole("button", { name: "生成配置" })).toBeInTheDocument();
  });

  it("生成成功后一次性展示 token/配置与只显示一次警告", async () => {
    api.regenerateWorkbuddyToken.mockResolvedValue({
      token: "kgw_secret_once",
      mcpConfigJson: '{\n  "mcpServers": { "kap": {} }\n}',
    });
    render(<WorkbuddyAccessCard />);
    await userEvent.click(await screen.findByRole("button", { name: "生成配置" }));
    expect(await screen.findByText(/只显示一次/)).toBeInTheDocument();
    expect(screen.getByLabelText("mcp.json 配置")).toHaveValue(
      '{\n  "mcpServers": { "kap": {} }\n}',
    );
  });

  it("生成失败显示安全文案（无后端路径 / HTTP code）", async () => {
    api.regenerateWorkbuddyToken.mockRejectedValue(new Error("boom"));
    render(<WorkbuddyAccessCard />);
    await userEvent.click(await screen.findByRole("button", { name: "生成配置" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("操作未成功，请稍后重试");
    expect(alert.textContent).not.toMatch(/\/api\/|workbuddy-token|40\d/);
  });

  it("复制按钮调用剪贴板 API", async () => {
    api.regenerateWorkbuddyToken.mockResolvedValue({
      token: "kgw_x",
      mcpConfigJson: "{}",
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<WorkbuddyAccessCard />);
    await userEvent.click(await screen.findByRole("button", { name: "生成配置" }));
    await userEvent.click(await screen.findByRole("button", { name: "复制配置" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("{}"));
    expect(screen.getByText("已复制")).toBeInTheDocument();
  });

  it("已启用时可重置并撤销配置", async () => {
    api.fetchWorkbuddyToken.mockResolvedValue({
      enabled: true,
      boundUserName: "张三",
      lastRotatedAt: "2026-07-22T08:00:00Z",
    });
    api.regenerateWorkbuddyToken.mockResolvedValue({ token: "kgw_new", mcpConfigJson: "{}" });
    api.revokeWorkbuddyToken.mockResolvedValue(undefined);
    render(<WorkbuddyAccessCard />);
    await userEvent.click(await screen.findByRole("button", { name: "重置配置" }));
    expect(await screen.findByLabelText("mcp.json 配置")).toBeInTheDocument();
    expect(api.regenerateWorkbuddyToken).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "撤销配置" }));
    await waitFor(() => expect(api.revokeWorkbuddyToken).toHaveBeenCalledTimes(1));
    expect(screen.queryByLabelText("mcp.json 配置")).not.toBeInTheDocument();
  });
});
