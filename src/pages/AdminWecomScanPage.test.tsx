import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWecomScanConfig,
  fetchWecomDriveDirectories,
  fetchWecomDriveSpaces,
  fetchWecomScanConfigs,
  fetchWecomScanOwnerOptions,
  fetchWecomScanProjectOptions,
  fetchWecomScanRecords,
  triggerWecomScan,
  updateWecomScanConfig,
} from "../api/admin";
import { ApiError } from "../api/http";
import type { WecomScanConfigDTO, WecomScanRecordDTO } from "../types/wecom";
import AdminWecomScanPage from "./AdminWecomScanPage";

const auth = { capabilities: { isAdmin: true } };
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../api/admin", () => ({
  createWecomScanConfig: vi.fn(),
  fetchWecomDriveDirectories: vi.fn(),
  fetchWecomDriveSpaces: vi.fn(),
  fetchWecomScanConfigs: vi.fn(),
  fetchWecomScanOwnerOptions: vi.fn(),
  fetchWecomScanProjectOptions: vi.fn(),
  fetchWecomScanRecords: vi.fn(),
  triggerWecomScan: vi.fn(),
  updateWecomScanConfig: vi.fn(),
}));

const config: WecomScanConfigDTO = {
  id: "cfg-secret-1",
  name: "项目交付目录",
  directory_path: "spaceid:space-secret;fatherid:folder-secret",
  scope_type: "project",
  related_project_id: "project-1",
  related_project_name: "Alpha 项目",
  enabled: true,
  created_by: "owner-secret-id",
  task_owner_name: "张经理",
  task_owner_role_label: "项目经理",
  scan_frequency: null,
  last_scan_at: "2026-07-20T01:00:00Z",
  created_at: "2026-07-19T01:00:00Z",
  updated_at: "2026-07-20T01:00:00Z",
};
const record: WecomScanRecordDTO = {
  id: "record-secret-id",
  config_id: config.id,
  trace_id: "trace-secret-id",
  scan_started_at: "2026-07-20T01:00:00Z",
  scan_completed_at: "2026-07-20T01:01:00Z",
  discovered_count: 8,
  new_count: 3,
  duplicate_count: 4,
  failed_count: 1,
  scan_status: "partial",
  error_type: "upstream_auth_token_secret",
  error_message: "raw upstream body token=do-not-render",
  created_at: "2026-07-20T01:00:00Z",
};
const secondConfig: WecomScanConfigDTO = {
  ...config,
  id: "cfg-secret-2",
  name: "Beta 交付目录",
  related_project_name: "Beta 项目",
};

describe("AdminWecomScanPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.capabilities.isAdmin = true;
    vi.mocked(fetchWecomScanConfigs).mockResolvedValue({ items: [config] });
    vi.mocked(fetchWecomScanRecords).mockResolvedValue({ items: [record] });
    vi.mocked(fetchWecomScanProjectOptions).mockResolvedValue({
      items: [{ id: "project-1", name: "Alpha 项目" }],
    });
    vi.mocked(fetchWecomScanOwnerOptions).mockResolvedValue({
      items: [
        {
          user_id: "owner-1",
          name: "张经理",
          role_label: "项目经理",
          project_ids: ["project-1"],
          is_governance: false,
        },
      ],
    });
    vi.mocked(fetchWecomDriveSpaces).mockResolvedValue({
      items: [{ space_ref: "space-secret", name: "项目空间" }],
    });
    vi.mocked(fetchWecomDriveDirectories).mockResolvedValue({
      space_ref: "space-secret",
      items: [],
    });
    vi.mocked(createWecomScanConfig).mockResolvedValue(config);
    vi.mocked(updateWecomScanConfig).mockResolvedValue(config);
    vi.mocked(triggerWecomScan).mockResolvedValue(record);
  });

  it("renders the operations console without internal references or raw upstream errors", async () => {
    const { container } = render(<AdminWecomScanPage />);
    expect(await screen.findByText("项目交付目录")).toBeInTheDocument();
    expect(screen.getByText("扫描文件会进入待确认队列，不会直接入库。")).toBeInTheDocument();
    expect(await screen.findByText("企业微信授权失效")).toBeInTheDocument();
    const html = container.innerHTML;
    expect(html).not.toContain("space-secret");
    expect(html).not.toContain("folder-secret");
    expect(html).not.toContain("cfg-secret-1");
    expect(html).not.toContain("record-secret-id");
    expect(html).not.toContain("trace-secret-id");
    expect(html).not.toContain("raw upstream body");
    expect(html).not.toContain("upstream_auth_token_secret");
  });

  it("makes governance access read-only", async () => {
    auth.capabilities.isAdmin = false;
    render(<AdminWecomScanPage />);
    expect(
      await screen.findByText("当前身份为只读模式，可查看扫描配置与运行记录。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增扫描配置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "扫描" })).not.toBeInTheDocument();
    expect(fetchWecomScanProjectOptions).not.toHaveBeenCalled();
  });

  it("selects a real directory and saves valid project ownership", async () => {
    render(<AdminWecomScanPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新增扫描配置" }));
    fireEvent.change(screen.getByLabelText("配置名称"), { target: { value: "新增目录" } });
    fireEvent.click(screen.getByRole("button", { name: "选择微盘目录" }));
    fireEvent.click(await screen.findByRole("button", { name: "项目空间" }));
    fireEvent.click(await screen.findByRole("button", { name: "使用当前目录" }));
    fireEvent.change(screen.getByLabelText("目标项目"), { target: { value: "project-1" } });
    fireEvent.change(screen.getByLabelText(/待确认任务业务归属人/), {
      target: { value: "owner-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建配置" }));
    await waitFor(() => expect(createWecomScanConfig).toHaveBeenCalled());
    expect(createWecomScanConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        target_scope: "project",
        target_project_id: "project-1",
        task_owner_user_id: "owner-1",
      }),
    );
    expect(screen.queryByText(/高级|fatherid|spaceid/)).not.toBeInTheDocument();
  });

  it("runs only the selected row and refreshes its records", async () => {
    render(<AdminWecomScanPage />);
    fireEvent.click(await screen.findByRole("button", { name: "扫描" }));
    await waitFor(() => expect(triggerWecomScan).toHaveBeenCalledWith(config.id));
    expect(await screen.findByText(/扫描已结束：发现 8/)).toBeInTheDocument();
    expect(fetchWecomScanRecords).toHaveBeenCalledWith(config.id);
  });

  it("ignores a late records response after switching configurations", async () => {
    vi.mocked(fetchWecomScanConfigs).mockResolvedValue({ items: [config, secondConfig] });
    render(<AdminWecomScanPage />);
    expect(await screen.findByText("Beta 交付目录")).toBeInTheDocument();
    await waitFor(() => expect(fetchWecomScanRecords).toHaveBeenCalled());

    let resolveLate: ((value: { items: WecomScanRecordDTO[] }) => void) | undefined;
    const lateResponse = new Promise<{ items: WecomScanRecordDTO[] }>((resolve) => {
      resolveLate = resolve;
    });
    vi.mocked(fetchWecomScanRecords).mockImplementation((configId) => {
      if (configId === secondConfig.id) return lateResponse;
      return Promise.resolve({ items: [{ ...record, discovered_count: 17 }] });
    });

    fireEvent.click(screen.getAllByRole("button", { name: "查看记录" })[1]);
    expect(
      await screen.findByRole("heading", { name: "Beta 交付目录 · 记录" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "查看记录" })[0]);
    expect(await screen.findByRole("heading", { name: "项目交付目录 · 记录" })).toBeInTheDocument();
    expect(await screen.findByText("17")).toBeInTheDocument();

    resolveLate?.({ items: [{ ...record, discovered_count: 99 }] });
    await Promise.resolve();
    expect(screen.queryByText("99")).not.toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
  });

  it("updates only the requested configuration state", async () => {
    render(<AdminWecomScanPage />);
    fireEvent.click(await screen.findByRole("button", { name: "停用" }));
    await waitFor(() =>
      expect(updateWecomScanConfig).toHaveBeenCalledWith(config.id, { enabled: false }),
    );
    expect(await screen.findByText("扫描配置已停用。")).toBeInTheDocument();
  });

  it("limits company ownership to governance candidates", async () => {
    vi.mocked(fetchWecomScanOwnerOptions).mockResolvedValue({
      items: [
        {
          user_id: "owner-1",
          name: "项目经理",
          role_label: null,
          project_ids: ["project-1"],
          is_governance: false,
        },
        {
          user_id: "governance-1",
          name: "咨询总监",
          role_label: "咨询总监",
          project_ids: [],
          is_governance: true,
        },
      ],
    });
    render(<AdminWecomScanPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新增扫描配置" }));
    fireEvent.change(screen.getByLabelText("目标知识库"), { target: { value: "company" } });
    const ownerSelect = screen.getByLabelText(/待确认任务业务归属人/);
    expect(ownerSelect).toHaveTextContent("咨询总监");
    expect(ownerSelect).not.toHaveTextContent("项目经理");
  });

  it("blocks saving when linkage options fail to load", async () => {
    vi.mocked(fetchWecomScanProjectOptions).mockRejectedValueOnce(new Error("raw secret"));
    render(<AdminWecomScanPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新增扫描配置" }));
    expect(
      await screen.findByText("项目与业务归属选项加载失败，请刷新页面后再配置。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建配置" })).toBeDisabled();
    expect(screen.queryByText("raw secret")).not.toBeInTheDocument();
  });

  it("maps 403 and 503 without exposing API messages", async () => {
    vi.mocked(fetchWecomScanConfigs).mockRejectedValueOnce(
      new ApiError(403, "secret forbidden", "raw_reason"),
    );
    const { unmount } = render(<AdminWecomScanPage />);
    expect(
      await screen.findByText("当前身份没有微盘扫描管理权限，此区域保持只读。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/secret forbidden|raw_reason/)).not.toBeInTheDocument();
    unmount();
    vi.mocked(fetchWecomScanConfigs).mockRejectedValueOnce(new ApiError(503, "token leaked"));
    render(<AdminWecomScanPage />);
    expect(
      await screen.findByText("企业微信微盘尚未配置或暂不可用，请联系系统管理员检查连接。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("token leaked")).not.toBeInTheDocument();
  });

  it("enters read-only mode when records return 403", async () => {
    vi.mocked(fetchWecomScanRecords).mockRejectedValue(
      new ApiError(403, "raw records secret", "raw_records_reason"),
    );
    render(<AdminWecomScanPage />);
    expect(
      await screen.findByText("当前身份为只读模式，可查看扫描配置与运行记录。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增扫描配置" })).not.toBeInTheDocument();
    expect(screen.queryByText(/raw records secret|raw_records_reason/)).not.toBeInTheDocument();
  });

  it("enters read-only mode when directory browsing returns 403", async () => {
    vi.mocked(fetchWecomDriveSpaces).mockRejectedValue(
      new ApiError(403, "raw drive secret", "raw_drive_reason"),
    );
    render(<AdminWecomScanPage />);
    fireEvent.click(await screen.findByRole("button", { name: "新增扫描配置" }));
    fireEvent.click(screen.getByRole("button", { name: "选择微盘目录" }));
    expect(
      await screen.findByText("当前身份为只读模式，可查看扫描配置与运行记录。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增扫描配置" })).not.toBeInTheDocument();
    expect(screen.queryByText(/raw drive secret|raw_drive_reason/)).not.toBeInTheDocument();
  });

  it("keeps a disabled configuration from scanning", async () => {
    vi.mocked(fetchWecomScanConfigs).mockResolvedValue({ items: [{ ...config, enabled: false }] });
    render(<AdminWecomScanPage />);
    expect(await screen.findByRole("button", { name: "扫描" })).toBeDisabled();
    expect(triggerWecomScan).not.toHaveBeenCalled();
  });
});
