import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchIndexingJobs,
  fetchIndexingHealth,
  fetchOpsIndexing,
  triggerIndexingReparse,
  triggerIndexingRetry,
  triggerTargetedIndexingRetry,
} from "../api/admin";
import { ApiError } from "../api/http";
import { fetchAdminIngest } from "../api/ingest";
import type { IndexingHealthDTO, IndexingJobSummaryDTO, OpsIndexingDTO } from "../types/ops";
import AdminIngestPage from "./AdminIngestPage";

vi.mock("../api/admin", () => ({
  fetchIndexingJobs: vi.fn(),
  fetchIndexingHealth: vi.fn(),
  fetchOpsIndexing: vi.fn(),
  triggerIndexingReparse: vi.fn(),
  triggerIndexingRetry: vi.fn(),
  triggerTargetedIndexingRetry: vi.fn(),
}));
vi.mock("../api/ingest", () => ({ fetchAdminIngest: vi.fn() }));

const ops: OpsIndexingDTO = {
  counts: {
    index_failed: 3,
    indexing: 2,
    not_indexed: 4,
    skipped: 1,
    parse_pending: 2,
    parse_processing: 1,
    kb_init_failed: 0,
  },
  recent_failed: [
    {
      asset_id: "asset-secret-84",
      title: "绝不能显示的业务标题",
      scope: "project",
      project_name: "绝不能显示的项目名称",
      owner_name: "绝不能显示的人员名称",
      index_status: "index_failed",
      index_error_code: "UPSTREAM_SECRET_CODE",
      index_error_message: "索引服务暂时不可用",
      operator_error_message: "连接检查未通过，请确认平台配置。",
      remediation_hint: "SECRET-REMEDIATION",
      severity: "critical",
      diagnostic_category: "external_service",
      diagnostic_label: "外部服务",
      retry_eligible: true,
      updated_at: "2026-07-17T02:30:00Z",
    },
  ],
  diagnostic_counts: {
    configuration: 1,
    external_service: 2,
    source_content: 0,
    permission: 0,
    platform: 0,
    unknown: 0,
  },
  title_visible: true,
};

const health: IndexingHealthDTO = {
  generated_at: "2026-07-17T03:00:00Z",
  window_hours: 24,
  insufficient_data: true,
  message: "正在积累运维数据",
  queue: {
    status: "healthy",
    queued_count: 0,
    oldest_queued_seconds: null,
    message: "索引作业队列运行正常。",
  },
  worker: {
    status: "unknown",
    last_heartbeat_at: null,
    message: "本地同步模式不代表独立运行进程在线。",
  },
  beat: {
    status: "unknown",
    last_heartbeat_at: null,
    message: "本地同步模式不代表独立运行进程在线。",
  },
  trend_points: [
    {
      observed_at: "2026-07-17T02:00:00Z",
      ...ops.counts,
      completed_jobs: 2,
      failed_jobs: 1,
      queued_jobs: 0,
      oldest_queued_seconds: null,
    },
  ],
};

const completedJob: IndexingJobSummaryDTO = {
  job_id: "job-secret-84",
  operation_type: "retry_index",
  status: "completed",
  scope_filter: null,
  requested_by_name: "SECRET OPERATOR",
  requested_at: "2026-07-17T02:30:00Z",
  started_at: "2026-07-17T02:31:00Z",
  finished_at: "2026-07-17T02:32:00Z",
  total_count: 6,
  success_count: 5,
  failed_count: 1,
  skipped_count: 0,
  error_code: "SECRET_CODE",
  error_message: "SECRET MESSAGE",
  trace_id: "trace-secret-84",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminIngestPage />
    </MemoryRouter>,
  );
}

describe("AdminIngestPage operations reference", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchOpsIndexing).mockResolvedValue(ops);
    vi.mocked(fetchIndexingJobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(fetchIndexingHealth).mockResolvedValue(health);
    vi.mocked(fetchAdminIngest).mockResolvedValue({
      items: [
        {
          id: "ingest-secret-84",
          source: "path_b_upload",
          source_file_name: "绝不能显示的原始文件名.docx",
          status: "processing",
          target_scope: "project",
          confidentiality_level: "L4",
          ai_access_level: "A1",
          confidence: null,
          naming_compliant: null,
          extraction_status: "success",
          error_type: null,
          error_message: null,
          result_asset_id: null,
          created_at: "2026-07-17T02:20:00Z",
        },
      ],
      total: 1,
    });
    vi.mocked(triggerIndexingRetry).mockResolvedValue(completedJob);
    vi.mocked(triggerIndexingReparse).mockResolvedValue({
      ...completedJob,
      job_id: "reparse-job-secret-84",
      operation_type: "reparse",
    });
    vi.mocked(triggerTargetedIndexingRetry).mockResolvedValue({
      ...completedJob,
      total_count: 1,
      success_count: 1,
      failed_count: 0,
    });
  });

  it("renders the three operations tabs and only safe aggregate failure data", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "管理员运维" })).toBeInTheDocument();
    expect(screen.getByText("查看索引运行、扫描任务和安全审计状态。")).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "管理员运维页面" });
    expect(within(tabs).getByRole("link", { name: "索引维护" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(tabs).getByRole("link", { name: "微盘扫描" })).toHaveAttribute(
      "href",
      "/admin/wecom-scan",
    );
    expect(within(tabs).getByRole("link", { name: "安全日志" })).toHaveAttribute(
      "href",
      "/admin/audit",
    );

    expect(await screen.findByText("连接检查未通过，请确认平台配置。")).toBeInTheDocument();
    expect(screen.getByText("3 项索引失败")).toBeInTheDocument();
    expect(screen.getByText("共 1 项")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("绝不能显示的业务标题");
    expect(document.body).not.toHaveTextContent("绝不能显示的项目名称");
    expect(document.body).not.toHaveTextContent("绝不能显示的人员名称");
    expect(document.body).not.toHaveTextContent("绝不能显示的原始文件名.docx");
    expect(document.body).not.toHaveTextContent("asset-secret-84");
    expect(document.body).not.toHaveTextContent("UPSTREAM_SECRET_CODE");
    expect(document.body).not.toHaveTextContent("critical");
    expect(screen.getByText("正在积累运维数据")).toBeInTheDocument();
    expect(screen.getAllByText("待确认").length).toBeGreaterThan(0);
  });

  it("filters the current failure list by the server diagnostic category", async () => {
    vi.mocked(fetchOpsIndexing).mockResolvedValue({
      ...ops,
      recent_failed: [
        ops.recent_failed[0],
        {
          ...ops.recent_failed[0],
          asset_id: "configuration-target-secret",
          operator_error_message: "请完成平台默认模型配置。",
          diagnostic_category: "configuration",
          diagnostic_label: "配置问题",
          retry_eligible: false,
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("请完成平台默认模型配置。");
    await user.click(screen.getByRole("button", { name: "配置问题1" }));
    expect(screen.getByText("请完成平台默认模型配置。")).toBeInTheDocument();
    expect(screen.queryByText("连接检查未通过，请确认平台配置。")).not.toBeInTheDocument();
  });

  it("confirms and completes one safe targeted retry", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "重试索引" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "此操作仅重新尝试索引，不查看、不下载、不修改原文。",
    );
    await user.click(screen.getByRole("button", { name: "确认重试" }));
    await waitFor(() =>
      expect(triggerTargetedIndexingRetry).toHaveBeenCalledWith("asset-secret-84"),
    );
    expect(await screen.findByText(/单条索引重试已提交：共 1 项/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each([
    [409, "任务状态已变化或正在执行，请刷新后重试。"],
    [403, "当前身份无权执行此操作。"],
    [500, "单条重试未能发起，请稍后重试。"],
  ])("unlocks targeted retry after safe HTTP %s feedback", async (status, message) => {
    vi.mocked(triggerTargetedIndexingRetry).mockRejectedValue(
      new ApiError(status, "SECRET upstream response"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "重试索引" }));
    await user.click(screen.getByRole("button", { name: "确认重试" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认重试" })).toBeEnabled();
    expect(document.body).not.toHaveTextContent("SECRET upstream response");
  });

  it("shows real stale health and a trend only with enough snapshots", async () => {
    vi.mocked(fetchIndexingHealth).mockResolvedValue({
      ...health,
      insufficient_data: false,
      message: "最近运行趋势已更新",
      worker: {
        status: "stale",
        last_heartbeat_at: "2026-07-17T01:00:00Z",
        message: "最近心跳已过期，请检查运行服务。",
      },
      beat: {
        status: "healthy",
        last_heartbeat_at: "2026-07-17T02:59:00Z",
        message: "定时调度进程心跳正常。",
      },
      trend_points: [
        health.trend_points[0],
        { ...health.trend_points[0], observed_at: "2026-07-17T03:00:00Z" },
      ],
    });
    renderPage();

    expect(await screen.findByText("心跳过期")).toBeInTheDocument();
    expect(screen.getAllByText("正常").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("最近 24 小时索引作业趋势")).toBeInTheDocument();
    expect(screen.queryByText("正在积累运维数据")).not.toBeInTheDocument();
  });

  it("isolates a health endpoint failure from the indexing panels", async () => {
    vi.mocked(fetchIndexingHealth).mockRejectedValue(new Error("SECRET health payload"));
    renderPage();

    expect(await screen.findByText("运行健康暂时无法加载。")).toBeInTheDocument();
    expect(screen.getByText("3 项索引失败")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET health payload");
  });

  it("submits the selected bounded batch retry and prevents duplicate actions", async () => {
    let resolveJob!: (job: IndexingJobSummaryDTO) => void;
    vi.mocked(triggerIndexingRetry).mockImplementation(
      () => new Promise((resolve) => (resolveJob = resolve)),
    );
    const user = userEvent.setup();
    renderPage();

    const retry = await screen.findByRole("button", { name: "批量重试索引" });
    await user.click(screen.getByRole("checkbox", { name: "包含已跳过" }));
    await user.click(screen.getByRole("checkbox", { name: "包含未索引" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "处理上限" }), "100");
    await user.click(retry);

    expect(triggerIndexingRetry).toHaveBeenCalledWith({
      scope: "all",
      statuses: ["index_failed", "skipped", "not_indexed"],
      limit: 100,
    });
    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新解析" })).toBeDisabled();

    resolveJob({ ...completedJob, status: "running" });
    await waitFor(() => expect(screen.getByRole("button", { name: "作业执行中" })).toBeDisabled());
    expect(triggerIndexingRetry).toHaveBeenCalledTimes(1);
  });

  it("uses the real reparse contract and reports only safe result counts", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "重新解析" }));
    await waitFor(() =>
      expect(triggerIndexingReparse).toHaveBeenCalledWith({
        scope: "all",
        parse_statuses: ["failed", "pending"],
        limit: 50,
      }),
    );
    expect(await screen.findByText(/重新解析已提交：共 6 项/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("reparse-job-secret-84");
    expect(document.body).not.toHaveTextContent("trace-secret-84");
    expect(document.body).not.toHaveTextContent("SECRET MESSAGE");
  });

  it("keeps the independently loaded ingest overview when indexing fails", async () => {
    vi.mocked(fetchOpsIndexing).mockRejectedValue(new Error("SECRET upstream failure"));
    renderPage();

    expect(await screen.findByText("索引状态暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("失败任务暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("共 1 项")).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET upstream failure");
  });

  it("keeps a stable explicit empty state", async () => {
    vi.mocked(fetchOpsIndexing).mockResolvedValue({
      ...ops,
      counts: { ...ops.counts, index_failed: 0 },
      recent_failed: [],
    });
    renderPage();

    expect(await screen.findByText("当前没有索引失败任务")).toBeInTheDocument();
    expect(screen.getByText("当前没有索引失败项")).toBeInTheDocument();
  });

  it("does not echo action errors returned by the service", async () => {
    vi.mocked(triggerIndexingRetry).mockRejectedValue(new Error("SECRET TOKEN IN ERROR"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "批量重试索引" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("批量重试未能发起，请稍后重试。");
    expect(document.body).not.toHaveTextContent("SECRET TOKEN IN ERROR");
  });
});
