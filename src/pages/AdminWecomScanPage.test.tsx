import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWecomScanConfig,
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

const auth = {
  capabilities: {
    isAdmin: false,
    isGovernance: false,
    isProjectManager: true,
  },
};
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../api/admin", () => ({
  createWecomScanConfig: vi.fn(),
  fetchWecomScanConfigs: vi.fn(),
  fetchWecomScanOwnerOptions: vi.fn(),
  fetchWecomScanProjectOptions: vi.fn(),
  fetchWecomScanRecords: vi.fn(),
  triggerWecomScan: vi.fn(),
  updateWecomScanConfig: vi.fn(),
}));

const config: WecomScanConfigDTO = {
  id: "cfg-internal",
  name: "Alpha 项目资料",
  scope_type: "project",
  related_project_id: "project-1",
  related_project_name: "Alpha 项目",
  scan_space_status: "ready",
  manager_access_status: "identity_link_required",
  enabled: true,
  created_by: "owner-1",
  task_owner_name: "张经理",
  task_owner_role_label: "项目经理",
  scan_frequency: null,
  last_scan_at: null,
  created_at: "2026-07-19T01:00:00Z",
  updated_at: "2026-07-20T01:00:00Z",
};
const record: WecomScanRecordDTO = {
  id: "record-internal",
  config_id: config.id,
  trace_id: "trace-internal",
  scan_started_at: "2026-07-20T01:00:00Z",
  scan_completed_at: "2026-07-20T01:01:00Z",
  discovered_count: 2,
  new_count: 1,
  duplicate_count: 1,
  failed_count: 0,
  scan_status: "completed",
  error_type: null,
  error_message: null,
  created_at: "2026-07-20T01:00:00Z",
};

describe("AdminWecomScanPage project scan spaces", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.capabilities.isProjectManager = true;
    vi.mocked(fetchWecomScanConfigs).mockResolvedValue({ items: [config] });
    vi.mocked(fetchWecomScanRecords).mockResolvedValue({ items: [record] });
    vi.mocked(fetchWecomScanProjectOptions).mockResolvedValue({
      items: [
        {
          id: "project-1",
          name: "Alpha 项目",
          scan_space_status: "ready",
          manager_access_status: "identity_link_required",
        },
      ],
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
    vi.mocked(createWecomScanConfig).mockResolvedValue(config);
    vi.mocked(updateWecomScanConfig).mockResolvedValue(config);
    vi.mocked(triggerWecomScan).mockResolvedValue(record);
  });

  it("lets a project manager operate only the project-space workflow", async () => {
    render(<AdminWecomScanPage />);
    expect(await screen.findByText("Alpha 项目资料")).toBeInTheDocument();
    expect(screen.getByText("项目经理需绑定企微身份")).toBeInTheDocument();
    expect(screen.queryByText(/选择微盘目录|企业空间/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "新增扫描配置" })).toBeEnabled());
  });

  it("creates with project and owner only and explains identity-link fallback", async () => {
    render(<AdminWecomScanPage />);
    const createButton = await screen.findByRole("button", { name: "新增扫描配置" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    fireEvent.change(screen.getByLabelText("配置名称"), { target: { value: "新配置" } });
    fireEvent.change(screen.getByRole("combobox", { name: /目标项目/ }), {
      target: { value: "project-1" },
    });
    expect(
      screen.getByText(/空间仍会创建，但需完成身份绑定后才能在企业微信中管理空间/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /待确认任务业务归属人/ }), {
      target: { value: "owner-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建配置" }));
    await waitFor(() =>
      expect(createWecomScanConfig).toHaveBeenCalledWith({
        name: "新配置",
        target_project_id: "project-1",
        task_owner_user_id: "owner-1",
        enabled: true,
      }),
    );
  });

  it("shows an actionable safe application-permission error", async () => {
    vi.mocked(createWecomScanConfig).mockRejectedValue(
      new ApiError(502, "raw upstream", "wecom_drive_permission_denied"),
    );
    render(<AdminWecomScanPage />);
    const createButton = await screen.findByRole("button", { name: "新增扫描配置" });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    fireEvent.change(screen.getByLabelText("配置名称"), { target: { value: "新配置" } });
    fireEvent.change(screen.getByRole("combobox", { name: /目标项目/ }), {
      target: { value: "project-1" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /待确认任务业务归属人/ }), {
      target: { value: "owner-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建配置" }));
    expect(await screen.findByText(/启用“协作-微盘-API”后重试/)).toBeInTheDocument();
    expect(screen.queryByText("raw upstream")).not.toBeInTheDocument();
  });

  it("keeps an ordinary non-manager read-only", async () => {
    auth.capabilities.isProjectManager = false;
    render(<AdminWecomScanPage />);
    expect(await screen.findByText("Alpha 项目资料")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增扫描配置" })).not.toBeInTheDocument();
  });
  it("does not label an empty or failed configuration list as connected", async () => {
    vi.mocked(fetchWecomScanConfigs).mockResolvedValueOnce({ items: [] });
    render(<AdminWecomScanPage />);
    await screen.findByText("尚未配置微盘扫描");
    expect(screen.getByRole("link", { name: "扫描记录" })).toHaveAttribute("href", "#scan-records");
    expect(screen.getByText("尚无扫描配置，暂时没有可查看的记录。")).toBeInTheDocument();
    expect(screen.getByText("尚未配置")).toBeInTheDocument();
    expect(screen.queryByText("连接可用")).not.toBeInTheDocument();
    vi.mocked(fetchWecomScanConfigs).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await screen.findByText("配置读取失败");
    expect(screen.getByRole("link", { name: "扫描记录" })).toHaveAttribute("href", "#scan-records");
    expect(screen.getByText("扫描配置加载失败，请在扫描配置中重试。")).toBeInTheDocument();
    expect(screen.queryByText("当前连接均可用")).not.toBeInTheDocument();
  });

  it("refreshes selected configuration history without requiring selection to change", async () => {
    render(<AdminWecomScanPage />);
    await screen.findByText(/最近扫描记录/);
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新" })).toBeEnabled());
    vi.mocked(fetchWecomScanRecords).mockResolvedValue({ items: [] });
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    expect(await screen.findByText("尚未运行")).toBeInTheDocument();
  });
});
