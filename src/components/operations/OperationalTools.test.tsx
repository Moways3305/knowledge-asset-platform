import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import * as admin from "../../api/admin";
import * as knowledge from "../../api/knowledge";
import * as ingest from "../../api/ingest";
import * as agentCalls from "../../api/agentCalls";
const operations = { ...admin, ...knowledge, ...ingest, ...agentCalls };
import { fetchAuthMe } from "../../api/auth";
import { ApiError } from "../../api/http";
import { SessionTools } from "./SessionTools";
import { RestoreAssetButton, RefreshParseButton } from "./AssetTools";
import { AgentRegistrationButton } from "./AgentRegistration";
import { IngestTools } from "./IngestTools";
import {
  AgentCallButton,
  AlertHistoryButton,
  AuditTraceButton,
  KnowledgeInsightsButton,
} from "./ReadTools";

vi.mock("../../api/admin", () => ({
  fetchPeople: vi.fn(),
  fetchUserSessions: vi.fn(),
  registerAgent: vi.fn(),
  backfillMarkdown: vi.fn(),
  fetchOpsSummary: vi.fn(),
  fetchAuditTrace: vi.fn(),
  fetchWecomScanOwnerOptions: vi.fn(),
  revokeUserSessions: vi.fn(),
  reconcileWecomIdentity: vi.fn(),
  fetchWecomScanProjectOptions: vi.fn(),
  fetchAlertNotifications: vi.fn(),
}));
vi.mock("../../api/knowledge", () => ({
  fetchKnowledgeOpsInsights: vi.fn(),
  requestAssetReenable: vi.fn(),
  confirmAssetReenable: vi.fn(),
}));
vi.mock("../../api/ingest", () => ({ refreshIngestParse: vi.fn() }));
vi.mock("../../api/agentCalls", () => ({ fetchAgentCall: vi.fn(), fetchAgentDecisions: vi.fn() }));
vi.mock("../../api/auth", () => ({ fetchAuthMe: vi.fn() }));

const user = {
  user_id: "user-a",
  name: "验收用户",
  email: "qa@example.test",
  wecom_bound: true,
  status: "active",
  company_roles: [{ status: "active", company_role: "consultant" }],
};
const sessions = {
  user_id: "user-a",
  active_count: 1,
  sessions: [
    {
      session_id: "session-private",
      login_method: "password",
      created_at: "2026-11-03T01:00:00Z",
      last_seen_at: null,
      expires_at: null,
      revoked_at: null,
      active: true,
      is_current_actor_session: false,
    },
  ],
};
const reconciliation = {
  ok: true,
  checked: 1,
  deactivated: 1,
  already_inactive: 0,
  failed: 0,
  dry_run: true,
  items: [
    {
      user_id: "user-a",
      user_name: "验收用户",
      previous_status: "active",
      new_status: "inactive",
      wecom_status: "disabled",
      sessions_revoked: 0,
      error_code: null,
    },
  ],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(admin.fetchPeople).mockResolvedValue({ items: [user], total: 1 } as Awaited<
    ReturnType<typeof admin.fetchPeople>
  >);
  vi.mocked(admin.fetchWecomScanProjectOptions).mockResolvedValue({
    items: [
      {
        id: "project-a",
        name: "验收项目",
        scan_space_status: "ready",
        manager_access_status: "ready",
      },
    ],
  });
  vi.mocked(operations.fetchUserSessions).mockResolvedValue(sessions);
  vi.mocked(admin.fetchWecomScanOwnerOptions).mockResolvedValue({
    items: [
      {
        user_id: "user-a",
        name: "验收用户",
        role_label: "顾问",
        project_ids: [],
        is_governance: false,
      },
    ],
  });
  vi.mocked(fetchAuthMe).mockResolvedValue({
    userId: "admin-a",
    name: "验收管理员",
    activeCompanyRole: "admin",
  } as Awaited<ReturnType<typeof fetchAuthMe>>);
});

describe("account operations", () => {
  it("loads on demand, confirms revocation, preserves current session and blocks dismissal while writing", async () => {
    let finish!: (value: Awaited<ReturnType<typeof admin.revokeUserSessions>>) => void;
    vi.mocked(admin.revokeUserSessions).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<SessionTools />);
    expect(admin.fetchWecomScanOwnerOptions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "会话管理" }));
    await screen.findByRole("option", { name: /验收用户/ });
    fireEvent.change(screen.getByLabelText("选择账号"), { target: { value: "user-a" } });
    await screen.findByText("1 个有效会话");
    expect(screen.queryByText("session-private")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "撤销会话…" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("撤销原因"), { target: { value: "账号安全核对" } });
    fireEvent.click(screen.getByRole("button", { name: "撤销会话…" }));
    expect(admin.revokeUserSessions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认撤销" }));
    expect(screen.getByRole("button", { name: "关闭详情" })).toBeDisabled();
    expect(screen.getByLabelText("选择账号")).toBeDisabled();
    expect(admin.revokeUserSessions).toHaveBeenCalledWith("user-a", {
      reason: "账号安全核对",
      preserve_current_session: true,
    });
    await act(async () =>
      finish({
        ok: true,
        user_id: "user-a",
        revoked_count: 1,
        revoked_at: null,
        preserved_current_session: false,
      }),
    );
    expect(await screen.findByText("已撤销 1 个会话。")).toBeInTheDocument();
    expect(operations.fetchUserSessions).toHaveBeenCalledTimes(2);
  });

  it("requires a successful dry run before applying identity changes", async () => {
    vi.mocked(admin.reconcileWecomIdentity).mockResolvedValue(reconciliation);
    render(<SessionTools />);
    fireEvent.click(screen.getByRole("button", { name: "企微身份核对" }));
    await screen.findByRole("option", { name: /验收用户/ });
    fireEvent.change(screen.getByLabelText("选择账号"), { target: { value: "user-a" } });
    expect(screen.queryByRole("button", { name: "确认核对并应用" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "预览企微身份核对" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认核对并应用" }));
    await waitFor(() => expect(admin.reconcileWecomIdentity).toHaveBeenCalledTimes(2));
    expect(admin.reconcileWecomIdentity).toHaveBeenNthCalledWith(1, {
      user_id: "user-a",
      dry_run: true,
    });
    expect(admin.reconcileWecomIdentity).toHaveBeenNthCalledWith(2, {
      user_id: "user-a",
      dry_run: false,
    });
  });
});

describe("asset and ingestion operations", () => {
  it("records a restore request without falsely restoring, then respects a backend conflict", async () => {
    vi.mocked(operations.requestAssetReenable).mockResolvedValue({
      asset_id: "asset-a",
      review_task_id: null,
    });
    vi.mocked(operations.confirmAssetReenable).mockRejectedValue(
      new ApiError(409, "该资料已由新版替代"),
    );
    const changed = vi.fn();
    render(<RestoreAssetButton assetId="asset-a" onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "恢复归档资料" }));
    fireEvent.change(screen.getByLabelText("恢复原因"), { target: { value: "复核仍可用" } });
    fireEvent.click(screen.getByRole("button", { name: "登记恢复申请" }));
    await screen.findByText("已登记恢复申请，资料仍处于归档状态。");
    expect(changed).not.toHaveBeenCalled();
    expect(operations.confirmAssetReenable).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "恢复使用…" }));
    fireEvent.click(screen.getByRole("button", { name: "确认恢复" }));
    await screen.findByRole("alert");
    expect(changed).not.toHaveBeenCalled();
  });

  it("does not call state synchronization a successful reparse", async () => {
    vi.mocked(operations.refreshIngestParse).mockResolvedValue({
      task_id: "task-a",
      result_asset_id: "asset-a",
      parse_status: "failed",
    });
    render(<RefreshParseButton taskId="task-a" />);
    fireEvent.click(screen.getByRole("button", { name: "同步解析状态" }));
    expect(await screen.findByRole("status")).toHaveTextContent("当前解析状态：解析失败");
  });

  it("confirms a bounded backfill and keeps system summary admin-only", async () => {
    vi.mocked(fetchAuthMe).mockResolvedValue({ activeCompanyRole: "boss" } as Awaited<
      ReturnType<typeof fetchAuthMe>
    >);
    vi.mocked(operations.backfillMarkdown).mockResolvedValue({ status: "queued" } as Awaited<
      ReturnType<typeof operations.backfillMarkdown>
    >);
    render(<IngestTools />);
    fireEvent.click(await screen.findByRole("button", { name: "历史正文回填" }));
    expect(screen.queryByRole("button", { name: "系统运行概况" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "准备正文回填" }));
    expect(operations.backfillMarkdown).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    await screen.findByRole("status");
    expect(operations.backfillMarkdown).toHaveBeenCalledWith({
      scope: "all",
      project_id: undefined,
      limit: 50,
      rebuild_index: false,
    });
  });
});

describe("read-only tools and registration", () => {
  it("blocks a backfill form submission while the required project cannot load", async () => {
    vi.mocked(admin.fetchWecomScanProjectOptions).mockRejectedValue(new Error("unavailable"));
    render(<IngestTools />);
    fireEvent.click(await screen.findByRole("button", { name: "历史正文回填" }));
    fireEvent.change(screen.getByLabelText("资料范围"), { target: { value: "project" } });
    await screen.findByRole("button", { name: "重试" });
    const submit = screen.getByRole("button", { name: "准备正文回填" });
    expect(submit).toBeDisabled();
    fireEvent.submit(submit.closest("form")!);
    expect(screen.queryByRole("button", { name: "确认执行" })).not.toBeInTheDocument();
    expect(operations.backfillMarkdown).not.toHaveBeenCalled();
  });

  it("renders base insight counts when the backend supplies no extra cards", async () => {
    vi.mocked(knowledge.fetchKnowledgeOpsInsights).mockResolvedValue({
      title_visible: false,
      scope: "all",
      window_days: 30,
      cards: [],
      recommendations: [],
      recent_items: [],
      indexing: {
        index_failed: 2,
        parse_pending: 0,
        parse_processing: 0,
        parse_failed: 1,
        skipped: 0,
        not_indexed: 0,
        kb_init_failed: 0,
        recent_jobs: [],
      },
      access: {
        pending_original_requests: 3,
        overdue_original_requests: 0,
        recent_auto_approved: 0,
        timeout_enabled: false,
      },
      lifecycle: {
        needs_update: 4,
        archive_candidates: 0,
        archive_warnings: 0,
        reuse_upgrade_candidates: 0,
      },
    });
    render(
      <MemoryRouter>
        <KnowledgeInsightsButton />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "知识运行概况" }));
    await screen.findByText("索引失败");
    expect(screen.getByText("待审批原文申请").parentElement).toHaveTextContent("3");
    expect(screen.getByText("待更新资料").parentElement).toHaveTextContent("4");
  });

  it("does not advance registration when required project choices cannot load, including after retry", async () => {
    vi.mocked(admin.fetchWecomScanProjectOptions).mockRejectedValue(new Error("unavailable"));
    render(<AgentRegistrationButton onCreated={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "新增助手" }));
    fireEvent.change(screen.getByLabelText("助手名称"), { target: { value: "测试助手" } });
    fireEvent.change(screen.getByLabelText("接入标识"), { target: { value: "qa-helper" } });
    fireEvent.click(await screen.findByRole("button", { name: "重试" }));
    await waitFor(() => expect(admin.fetchWecomScanProjectOptions).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "核对并创建" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "确认创建" })).not.toBeInTheDocument();
    expect(operations.registerAgent).not.toHaveBeenCalled();
  });
  it("loads alert history only on opening and supports permission errors", async () => {
    vi.mocked(admin.fetchAlertNotifications).mockRejectedValue(
      new ApiError(403, "当前身份没有权限"),
    );
    render(<AlertHistoryButton />);
    expect(admin.fetchAlertNotifications).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "告警通知记录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("当前身份没有权限");
  });

  it("uses the selected trace and respects backend metadata redaction", async () => {
    vi.mocked(operations.fetchAuditTrace).mockResolvedValue({
      trace_id: "trace-a",
      view: "admin_metadata",
      items: [],
    });
    render(<AuditTraceButton traceId="trace-a" />);
    fireEvent.click(screen.getByRole("button", { name: "关联审计" }));
    await screen.findByText("没有可见的关联记录。");
    expect(operations.fetchAuditTrace).toHaveBeenCalledWith("trace-a");
  });

  it("shows call records and avoids links for undiscoverable candidates", async () => {
    vi.mocked(operations.fetchAgentCall).mockResolvedValue({
      call_id: "call-a",
      query_text: "核对标记",
      response_text: "依据不足",
      project_name: "验收项目",
      caller_name: "验收用户",
      created_at: "2026-11-03T01:00:00Z",
      call_status: "allowed",
      denied_reason: null,
      citations: [],
    });
    vi.mocked(operations.fetchAgentDecisions).mockResolvedValue({
      decision_status: "allowed",
      items: [
        {
          target_asset_id: "hidden-asset",
          discovery_allowed: false,
          summary_allowed: false,
          original_allowed: false,
          returned_layer: "none",
          denied_reason: null,
        },
      ],
    });
    render(
      <MemoryRouter>
        <AgentCallButton callId="call-a" />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "问答记录与引用权限" }));
    await screen.findByText("依据不足");
    await screen.findByText("候选资料 1");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("hidden-asset")).not.toBeInTheDocument();
  });

  it("creates only after confirmation and discards one-time credentials when closed", async () => {
    vi.mocked(operations.registerAgent).mockResolvedValue({
      rule: { id: "agent-a" },
      token: "one-time-secret",
    } as Awaited<ReturnType<typeof operations.registerAgent>>);
    const created = vi.fn();
    render(<AgentRegistrationButton onCreated={created} />);
    fireEvent.click(screen.getByRole("button", { name: "新增助手" }));
    fireEvent.change(screen.getByLabelText("助手名称"), { target: { value: "测试助手" } });
    fireEvent.change(screen.getByLabelText("接入标识"), { target: { value: "qa-helper" } });
    await screen.findByRole("option", { name: "验收项目" });
    fireEvent.change(screen.getByLabelText("项目"), { target: { value: "project-a" } });
    fireEvent.click(screen.getByRole("button", { name: "核对并创建" }));
    expect(operations.registerAgent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认创建" }));
    const credential = await screen.findByLabelText("接入凭证");
    expect(credential).toHaveAttribute("type", "password");
    expect(created).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
    fireEvent.click(screen.getByRole("button", { name: "新增助手" }));
    await screen.findByRole("option", { name: "验收项目" });
    expect(
      within(screen.getByRole("dialog")).queryByDisplayValue("one-time-secret"),
    ).not.toBeInTheDocument();
  });
});
