import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchIndexingJobs,
  fetchIndexingHealth,
  fetchLLMUsage,
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
  fetchLLMUsage: vi.fn(),
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
    parse_stalled: 0,
    parse_failed: 5,
    kb_init_failed: 0,
  },
  reparse_actionable_count: 4,
  recent_failed: [
    {
      retry_target: "opaque-retry-target-84",
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
      recovery_state: "interrupted",
      wait_seconds: 3600,
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
  recovery_summary: {
    interrupted: 1,
    needs_recovery: 8,
    processing: 2,
    searchable: 12,
  },
  last_reconcile: {
    observed_at: "2026-08-06T09:33:20Z",
    processed: 50,
    updated: 0,
    failed: 3,
    duration_ms: 334,
  },
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
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AdminIngestPage />
    </MemoryRouter>,
  );
}

async function openRuntimeDetails(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByText("运行详情", { selector: "summary span" }));
}

describe("AdminIngestPage operations reference", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchOpsIndexing).mockResolvedValue(ops);
    vi.mocked(fetchIndexingJobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(fetchIndexingHealth).mockResolvedValue(health);
    vi.mocked(fetchLLMUsage).mockResolvedValue({
      days: 14,
      items: [
        {
          day: "2026-07-17",
          scenario: "content_generation",
          request_count: 2,
          item_count: 2,
          prompt_tokens: 20,
          completion_tokens: 10,
          total_tokens: 30,
          cache_hits: 1,
          cache_misses: 1,
          cache_hit_rate: 0.5,
        },
      ],
    });
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
          suggestion_generation_status: "needs_correction",
          suggestion_generation_reason: "历史任务信息不足，请人工核对",
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

  it("renders the recovery track without the old operations tabs and only safe failure data", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "索引恢复控制台" })).toBeInTheDocument();
    expect(screen.getByText("让未完成索引恢复为可检索资料")).toBeInTheDocument();
    expect(
      screen.queryByText("优先恢复失败、卡住和待确认的入库与索引任务。"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "管理员运维页面" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "微盘扫描" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "安全日志" })).not.toBeInTheDocument();

    const track = screen.getByRole("list", { name: "索引处理轨道" });
    expect(within(track).getByText("已入库").closest("li")).toHaveTextContent("—");
    expect(within(track).getByText("索引提交").closest("li")).toHaveTextContent("2");
    expect(within(track).getByText("中断待恢复").closest("li")).toHaveTextContent("1");
    expect(within(track).getByText("可检索").closest("li")).toHaveTextContent("12");
    const currentState = screen.getByLabelText("索引当前状态");
    expect(within(currentState).getByText("需恢复").closest("p")).toHaveTextContent("8");
    expect(within(currentState).getByText("处理中").closest("p")).toHaveTextContent("2");
    expect(within(currentState).getByText("已可检索").closest("p")).toHaveTextContent("12");

    expect(await screen.findByText("连接检查未通过，请确认平台配置。")).toBeInTheDocument();
    expect(screen.getByText("1 项索引中断，等待恢复")).toBeInTheDocument();
    expect(screen.getByText("共 1 项")).toBeInTheDocument();
    expect(screen.getByLabelText("近 14 天模型用量")).toHaveTextContent("2外部请求数");
    expect(screen.getByLabelText("近 14 天模型用量")).toHaveTextContent("30总 token");
    expect(screen.getByLabelText("近 14 天模型用量")).toHaveTextContent("50%缓存命中率");
    expect(screen.getByLabelText("按日和调用场景的模型用量")).toHaveTextContent(
      "2026-07-17内容生成2 次外部请求 · 30 token缓存命中率 50%",
    );
    expect(document.body).toHaveTextContent("绝不能显示的业务标题");
    expect(document.body).not.toHaveTextContent("绝不能显示的项目名称");
    expect(document.body).not.toHaveTextContent("绝不能显示的人员名称");
    expect(document.body).not.toHaveTextContent("绝不能显示的原始文件名.docx");
    expect(document.body).not.toHaveTextContent("asset-secret-84");
    expect(document.body).not.toHaveTextContent("UPSTREAM_SECRET_CODE");
    expect(document.body).not.toHaveTextContent("critical");
    expect(screen.getByText("正在积累运维数据")).toBeInTheDocument();
    expect(screen.queryByLabelText("近 24 小时索引运维趋势")).not.toBeInTheDocument();
    expect(screen.getAllByText("待确认").length).toBeGreaterThan(0);
  });

  it("filters the current failure list by the server diagnostic category", async () => {
    vi.mocked(fetchOpsIndexing).mockResolvedValue({
      ...ops,
      recent_failed: [
        ops.recent_failed[0],
        {
          ...ops.recent_failed[0],
          retry_target: null,
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
    await user.selectOptions(
      screen.getByRole("combobox", { name: "诊断类别筛选" }),
      "configuration",
    );
    expect(screen.getByText("请完成平台默认模型配置。")).toBeInTheDocument();
    expect(screen.queryByText("连接检查未通过，请确认平台配置。")).not.toBeInTheDocument();
  });

  it("shows interrupted tasks first and reveals the remaining candidates on demand", async () => {
    const recoveryItems = [
      {
        ...ops.recent_failed[0],
        retry_target: "waiting-1",
        title: "等待任务一",
        operator_error_message: "等待重新提交。",
        recovery_state: "waiting" as const,
        wait_seconds: 900,
      },
      {
        ...ops.recent_failed[0],
        retry_target: "failed-1",
        title: "失败任务一",
        operator_error_message: "本次提交失败。",
        recovery_state: "failed" as const,
        wait_seconds: 1800,
      },
      {
        ...ops.recent_failed[0],
        retry_target: "interrupted-1",
        title: "中断任务一",
        operator_error_message: "长时间没有进展。",
        recovery_state: "interrupted" as const,
        wait_seconds: 7200,
      },
      {
        ...ops.recent_failed[0],
        retry_target: "failed-2",
        title: "失败任务二",
        operator_error_message: "再次提交失败。",
        recovery_state: "failed" as const,
        wait_seconds: 1200,
      },
      {
        ...ops.recent_failed[0],
        retry_target: "waiting-2",
        title: "等待任务二",
        operator_error_message: "等待运行资源。",
        recovery_state: "waiting" as const,
        wait_seconds: 600,
      },
      {
        ...ops.recent_failed[0],
        retry_target: "skipped-1",
        title: "跳过任务一",
        operator_error_message: "当前不满足条件。",
        recovery_state: "skipped" as const,
        wait_seconds: 300,
      },
    ];
    vi.mocked(fetchOpsIndexing)
      .mockResolvedValueOnce({
        ...ops,
        recent_failed: recoveryItems.slice(0, 4),
        recovery_items: recoveryItems.slice(0, 4),
        recovery_summary: { interrupted: 1, needs_recovery: 6, processing: 2, searchable: 12 },
      })
      .mockResolvedValueOnce({
        ...ops,
        recent_failed: recoveryItems,
        recovery_items: recoveryItems,
        recovery_summary: { interrupted: 1, needs_recovery: 6, processing: 2, searchable: 12 },
      });
    const user = userEvent.setup();
    renderPage();

    const taskList = await screen.findByRole("list", { name: "待恢复任务列表" });
    const visibleItems = within(taskList).getAllByRole("listitem");
    expect(visibleItems).toHaveLength(4);
    expect(visibleItems[0]).toHaveTextContent("中断任务一");
    expect(visibleItems[1]).toHaveTextContent("失败任务一");
    expect(screen.queryByText("等待任务二")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看全部 6 项" }));
    await waitFor(() => expect(fetchOpsIndexing).toHaveBeenLastCalledWith(true));
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "待恢复任务列表" })).getAllByRole("listitem"),
      ).toHaveLength(6),
    );
    expect(screen.getByText("等待任务二")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "收起为优先项" })).toBeInTheDocument();
  });

  it("keeps the current candidate projection when loading all candidates fails", async () => {
    vi.mocked(fetchOpsIndexing)
      .mockResolvedValueOnce(ops)
      .mockRejectedValueOnce(new Error("SECRET full candidate failure"));
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("绝不能显示的业务标题")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看全部 8 项" }));
    expect(await screen.findByText("全部恢复候选暂时无法加载，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByText("绝不能显示的业务标题")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET full candidate failure");
  });

  it("confirms and completes one safe targeted retry", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "此操作仅重新发起索引恢复，不查看、不下载、不修改原文。",
    );
    await user.click(screen.getByRole("button", { name: "确认恢复" }));
    await waitFor(() =>
      expect(triggerTargetedIndexingRetry).toHaveBeenCalledWith("opaque-retry-target-84"),
    );
    expect(await screen.findByText(/单条索引恢复已到达终态：共 1 项/)).toBeInTheDocument();
    expect(screen.getByText("作业已完成")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each([
    [409, "任务状态已变化或正在执行，请刷新后重试。"],
    [403, "当前身份无权执行此操作。"],
    [500, "单项恢复未能发起，请稍后重试。"],
  ])("unlocks targeted retry after safe HTTP %s feedback", async (status, message) => {
    vi.mocked(triggerTargetedIndexingRetry).mockRejectedValue(
      new ApiError(status, "SECRET upstream response"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    await user.click(screen.getByRole("button", { name: "确认恢复" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认恢复" })).toBeEnabled();
    expect(document.body).not.toHaveTextContent("SECRET upstream response");
  });

  it("shows a readable real trend with legend, Beijing ticks, focus detail and zero values", async () => {
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
        {
          ...health.trend_points[0],
          completed_jobs: 0,
          failed_jobs: 0,
          queued_jobs: 0,
          index_failed: 3,
        },
        {
          ...health.trend_points[0],
          observed_at: "2026-07-17T03:00:00Z",
          completed_jobs: 4,
          failed_jobs: 1,
          queued_jobs: 2,
          index_failed: 5,
        },
        {
          ...health.trend_points[0],
          observed_at: "2026-07-17T04:00:00Z",
          completed_jobs: 2,
          failed_jobs: 0,
          queued_jobs: 1,
          index_failed: 4,
        },
      ],
    });
    renderPage();

    expect(await screen.findByText("心跳过期")).toBeInTheDocument();
    expect(screen.getAllByText("正常").length).toBeGreaterThan(0);
    expect(screen.getByText("近 24 小时索引运维趋势")).toBeInTheDocument();
    expect(screen.getByText("深蓝：已完成索引运维作业数")).toBeInTheDocument();
    expect(screen.getByText("红色：失败或部分失败的索引运维作业数")).toBeInTheDocument();
    expect(screen.getByText("10:00")).toBeInTheDocument();
    expect(screen.getByText("11:00")).toBeInTheDocument();
    expect(screen.getByText("12:00")).toBeInTheDocument();
    expect(document.querySelectorAll(".ao85-trend-tick:not(.is-hidden)")).toHaveLength(3);
    const zeroPoint = screen.getByRole("img", {
      name: /已完成作业 0，失败或部分失败作业 0，排队作业 0，索引失败存量 3/,
    });
    expect(zeroPoint.querySelector<HTMLElement>(".is-completed")).toHaveStyle({ height: "0%" });
    expect(zeroPoint.querySelector<HTMLElement>(".is-failed")).toHaveStyle({ height: "0%" });
    const detailPoint = screen.getByRole("img", {
      name: /已完成作业 4，失败或部分失败作业 1，排队作业 2，索引失败存量 5/,
    });
    const tooltip = document.getElementById(detailPoint.getAttribute("aria-describedby") ?? "");
    expect(tooltip).not.toBeNull();
    expect(tooltip).toHaveClass("ao85-trend-tooltip");
    act(() => detailPoint.focus());
    expect(detailPoint).toHaveFocus();
    await waitFor(() => expect(tooltip).toHaveTextContent("已完成作业 4"));
    expect(tooltip).toHaveTextContent("失败或部分失败作业 1");
    expect(tooltip).toHaveTextContent("排队作业 2");
    expect(tooltip).toHaveTextContent("索引失败存量 5");
    expect(screen.queryByText("正在积累运维数据")).not.toBeInTheDocument();
  });

  it("uses at least eight real ticks and marks the first point of a new Beijing date", async () => {
    const start = Date.parse("2026-07-16T03:00:00Z");
    vi.mocked(fetchIndexingHealth).mockResolvedValue({
      ...health,
      insufficient_data: false,
      message: "最近运行趋势已更新",
      trend_points: Array.from({ length: 24 }, (_, index) => ({
        ...health.trend_points[0],
        observed_at: new Date(start + index * 60 * 60 * 1000).toISOString(),
        completed_jobs: index % 3,
        failed_jobs: index % 2,
      })),
    });
    renderPage();

    expect(await screen.findByText("近 24 小时索引运维趋势")).toBeInTheDocument();
    const visibleTicks = document.querySelectorAll(".ao85-trend-tick:not(.is-hidden)");
    expect(visibleTicks.length).toBeGreaterThanOrEqual(8);
    expect(visibleTicks[0]).toHaveTextContent("11:00");
    expect([...visibleTicks].some((tick) => tick.textContent === "07/17 00:00")).toBe(true);
    expect(document.querySelectorAll(".ao85-trend-point")).toHaveLength(24);
  });

  it("isolates a health endpoint failure from the indexing panels", async () => {
    vi.mocked(fetchIndexingHealth).mockRejectedValue(new Error("SECRET health payload"));
    renderPage();

    expect(await screen.findByText("运行健康暂时无法加载。")).toBeInTheDocument();
    expect(screen.getByText("1 项索引中断，等待恢复")).toBeInTheDocument();
    expect(screen.queryByLabelText("近 24 小时索引运维趋势")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET health payload");
  });

  it("does not render a trend when the health endpoint is forbidden", async () => {
    vi.mocked(fetchIndexingHealth).mockRejectedValue(new ApiError(403, "SECRET forbidden"));
    renderPage();

    expect(await screen.findByText("运行健康暂时无法加载。")).toBeInTheDocument();
    expect(screen.queryByLabelText("近 24 小时索引运维趋势")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET forbidden");
  });

  it("submits the selected bounded batch retry and prevents duplicate actions", async () => {
    let resolveJob!: (job: IndexingJobSummaryDTO) => void;
    vi.mocked(fetchIndexingJobs)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValue({
        items: [{ ...completedJob, status: "running" }],
        total: 1,
      });
    vi.mocked(triggerIndexingRetry).mockImplementation(
      () => new Promise((resolve) => (resolveJob = resolve)),
    );
    const user = userEvent.setup();
    renderPage();

    const retry = await screen.findByRole("button", { name: /^恢复索引/ });
    await openRuntimeDetails(user);
    await user.click(screen.getByRole("checkbox", { name: "包含已跳过" }));
    await user.click(screen.getByRole("checkbox", { name: "包含未索引" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "处理上限" }), "100");
    await user.click(retry);

    expect(triggerIndexingRetry).toHaveBeenCalledWith({
      scope: "all",
      statuses: ["index_failed", "skipped", "not_indexed"],
      limit: 100,
    });
    expect(screen.getAllByRole("button", { name: "正在执行：恢复索引" })).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "正在执行：恢复索引" })[1]).toBeDisabled();

    resolveJob({ ...completedJob, status: "running" });
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "正在执行：恢复索引" })[0]).toBeDisabled(),
    );
    expect(
      screen.getByText(/恢复索引请求已提交，共 6 项；作业仍在排队或处理中/),
    ).toBeInTheDocument();
    expect(screen.getByText("请求已提交")).toBeInTheDocument();
    expect(triggerIndexingRetry).toHaveBeenCalledTimes(1);
  });

  it("keeps candidates returned by the refreshed server projection after recovery submission", async () => {
    const runningJob = { ...completedJob, status: "running", total_count: 1 };
    vi.mocked(triggerIndexingRetry).mockResolvedValue(runningJob);
    vi.mocked(fetchIndexingJobs)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValue({ items: [runningJob], total: 1 });
    vi.mocked(fetchOpsIndexing).mockResolvedValue(ops);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("绝不能显示的业务标题")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^恢复索引/ }));

    await screen.findByText(/恢复索引请求已提交，共 1 项/);
    await waitFor(() => expect(fetchOpsIndexing).toHaveBeenCalledTimes(2));
    expect(screen.getByText("绝不能显示的业务标题")).toBeInTheDocument();
    const currentState = screen.getByLabelText("索引当前状态");
    expect(within(currentState).getByText("需恢复").closest("p")).toHaveTextContent("8");
    expect(within(currentState).getByText("处理中").closest("p")).toHaveTextContent("2");
  });

  it("treats a zero-target reparse as terminal and refreshes every dependent summary", async () => {
    vi.mocked(triggerIndexingReparse).mockResolvedValue({
      ...completedJob,
      status: "no_action",
      operation_type: "reparse",
      total_count: 0,
      success_count: 0,
      failed_count: 0,
    });
    const user = userEvent.setup();
    renderPage();

    await openRuntimeDetails(user);
    await user.click(await screen.findByRole("button", { name: /^重新解析/ }));

    expect(
      (await screen.findByText(/重新解析未找到可处理项/)).closest(".action-feedback"),
    ).toHaveClass("is-info");
    await waitFor(() => expect(screen.getByRole("button", { name: /^重新解析（/ })).toBeEnabled());
    expect(fetchAdminIngest).toHaveBeenCalledTimes(2);
    expect(fetchOpsIndexing).toHaveBeenCalledTimes(2);
    expect(fetchIndexingJobs).toHaveBeenCalledTimes(2);
    expect(fetchIndexingHealth).toHaveBeenCalledTimes(2);
  });

  it("polls one running job to its terminal state, refreshes summaries, and then stops", async () => {
    const runningJob = { ...completedJob, status: "running" };
    vi.mocked(triggerIndexingRetry).mockResolvedValue(runningJob);
    vi.mocked(fetchIndexingJobs)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [runningJob], total: 1 })
      .mockResolvedValue({ items: [completedJob], total: 1 });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /^恢复索引/ }));
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "正在执行：恢复索引" })[0]).toBeDisabled(),
    );
    await waitFor(() => expect(fetchIndexingJobs).toHaveBeenCalledTimes(3), {
      timeout: 3_500,
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /^恢复索引/ })).toBeEnabled());
    expect(fetchAdminIngest).toHaveBeenCalledTimes(3);
    expect(fetchOpsIndexing).toHaveBeenCalledTimes(3);
    expect(fetchIndexingHealth).toHaveBeenCalledTimes(3);

    const stoppedAt = vi.mocked(fetchIndexingJobs).mock.calls.length;
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 1_700));
    });
    expect(fetchIndexingJobs).toHaveBeenCalledTimes(stoppedAt);
  }, 7_000);

  it("reuses a slow manual jobs refresh when the polling timer fires", async () => {
    const runningJob = { ...completedJob, status: "running" };
    let resolveRefresh!: (value: { items: IndexingJobSummaryDTO[]; total: number }) => void;
    vi.mocked(fetchIndexingJobs)
      .mockResolvedValueOnce({ items: [runningJob], total: 1 })
      .mockImplementationOnce(() => new Promise((resolve) => (resolveRefresh = resolve)));
    const user = userEvent.setup();
    const page = renderPage();

    await waitFor(() => expect(fetchIndexingJobs).toHaveBeenCalledTimes(1));
    await user.click(await screen.findByRole("button", { name: "刷新" }));
    expect(fetchIndexingJobs).toHaveBeenCalledTimes(2);

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 1_700));
    });
    expect(fetchIndexingJobs).toHaveBeenCalledTimes(2);

    resolveRefresh({ items: [completedJob], total: 1 });
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新" })).toBeEnabled());
    page.unmount();
  }, 7_000);

  it("does not poll while hidden and cancels the single poller on unmount", async () => {
    const runningJob = { ...completedJob, status: "running" };
    let visibility: DocumentVisibilityState = "hidden";
    const visibilitySpy = vi
      .spyOn(document, "visibilityState", "get")
      .mockImplementation(() => visibility);
    vi.mocked(fetchIndexingJobs).mockResolvedValue({ items: [runningJob], total: 1 });
    const page = renderPage();

    await waitFor(() => expect(fetchIndexingJobs).toHaveBeenCalledTimes(1));
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 1_700));
    });
    expect(fetchIndexingJobs).toHaveBeenCalledTimes(1);

    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(fetchIndexingJobs).toHaveBeenCalledTimes(2), {
      timeout: 3_000,
    });
    page.unmount();
    const stoppedAt = vi.mocked(fetchIndexingJobs).mock.calls.length;
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 1_700));
    });
    expect(fetchIndexingJobs).toHaveBeenCalledTimes(stoppedAt);
    visibilitySpy.mockRestore();
  }, 7_000);

  it("uses the real reparse contract and reports only safe result counts", async () => {
    const user = userEvent.setup();
    renderPage();

    await openRuntimeDetails(user);
    await user.click(await screen.findByRole("button", { name: "重新解析（4 项）" }));
    await waitFor(() =>
      expect(triggerIndexingReparse).toHaveBeenCalledWith({
        scope: "all",
        parse_statuses: ["failed", "pending"],
        limit: 50,
      }),
    );
    expect(await screen.findByText(/重新解析已到达终态：共 6 项/)).toBeInTheDocument();
    expect(screen.getByText("作业已完成")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("reparse-job-secret-84");
    expect(document.body).not.toHaveTextContent("trace-secret-84");
    expect(document.body).not.toHaveTextContent("SECRET MESSAGE");
  });

  it("keeps the independently loaded ingest overview when indexing fails", async () => {
    vi.mocked(fetchOpsIndexing).mockRejectedValue(new Error("SECRET upstream failure"));
    renderPage();

    expect(await screen.findByText("索引状态暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("恢复任务暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("共 1 项")).toBeInTheDocument();
    expect(screen.getAllByText("处理中").length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent("SECRET upstream failure");
  });

  it("keeps a stable explicit empty state", async () => {
    vi.mocked(fetchOpsIndexing).mockResolvedValue({
      ...ops,
      counts: { ...ops.counts, index_failed: 0, parse_failed: 0 },
      reparse_actionable_count: 0,
      recent_failed: [],
      recovery_summary: { interrupted: 0, needs_recovery: 0, processing: 2, searchable: 12 },
    });
    renderPage();

    expect(await screen.findAllByText("当前没有待恢复索引")).toHaveLength(2);
  });

  it("keeps parse-only recovery in the folded runtime details", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchOpsIndexing).mockResolvedValue({
      ...ops,
      counts: { ...ops.counts, index_failed: 0, parse_failed: 5 },
      reparse_actionable_count: 2,
      recent_failed: [],
      recovery_summary: { interrupted: 0, needs_recovery: 0, processing: 2, searchable: 12 },
    });
    renderPage();

    expect(await screen.findAllByText("当前没有待恢复索引")).toHaveLength(2);
    expect(
      screen.getByText("底座对账仍有异常；恢复前会再次校验连接与嵌入模型。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("当前没有索引失败项")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新解析" })).not.toBeInTheDocument();
    await openRuntimeDetails(user);
    expect(screen.getByRole("button", { name: "重新解析（2 项）" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新解析（2 项）" }));
    await waitFor(() =>
      expect(triggerIndexingReparse).toHaveBeenCalledWith({
        scope: "all",
        limit: 50,
        parse_statuses: ["failed", "pending"],
      }),
    );
  });

  it("reports action-specific empty results without claiming parse failures were handled", async () => {
    vi.mocked(triggerIndexingRetry).mockResolvedValue({ ...completedJob, total_count: 0 });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /^恢复索引/ }));
    expect(
      await screen.findByText(/恢复索引未找到可处理项：本次没有符合条件的索引失败/),
    ).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("解析失败已处理");
  });

  it("does not echo action errors returned by the service", async () => {
    vi.mocked(triggerIndexingRetry).mockRejectedValue(new Error("SECRET TOKEN IN ERROR"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /^恢复索引/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("索引恢复未能发起，请稍后重试。");
    expect(document.body).not.toHaveTextContent("SECRET TOKEN IN ERROR");
  });
});
