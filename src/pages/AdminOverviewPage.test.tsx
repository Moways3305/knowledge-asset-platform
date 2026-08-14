import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAudit,
  fetchOpsIndexing,
  fetchWecomScanConfigs,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
} from "../api/admin";
import { fetchAdminIngest } from "../api/ingest";
import { ADMIN_OVERVIEW_INVALIDATED_EVENT } from "../admin/adminOverviewEvents";
import AdminOverviewPage from "./AdminOverviewPage";

const auth = vi.hoisted(() => ({
  capabilities: {
    isAdmin: true,
    isBoss: true,
    isConsultingDirector: false,
    isBusinessUser: true,
    isGovernance: true,
    hasProject: true,
    isProjectManager: true,
  },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities: auth.capabilities }),
}));

vi.mock("../api/admin", () => ({
  fetchAudit: vi.fn(),
  fetchOpsIndexing: vi.fn(),
  fetchWecomScanConfigs: vi.fn(),
  fetchWeknoraKbConfigs: vi.fn(),
  fetchWeknoraModels: vi.fn(),
}));

vi.mock("../api/ingest", () => ({ fetchAdminIngest: vi.fn() }));

const ingestFailure = {
  id: "ingest-secret",
  source: "path_b_upload",
  source_file_name: "文件.docx",
  status: "failed",
  target_scope: "company",
  confidentiality_level: "L2",
  ai_access_level: "summary",
  confidence: 0.8,
  suggestion_generation_status: "generated" as const,
  suggestion_generation_reason: "ready",
  naming_compliant: true,
  extraction_status: "completed",
  error_type: "service_unavailable",
  error_message: "safe error",
  result_asset_id: null,
  created_at: "2026-08-14T01:00:00Z",
};

const indexing = {
  counts: {
    index_failed: 2,
    indexing: 1,
    not_indexed: 0,
    skipped: 0,
    parse_pending: 0,
    parse_processing: 1,
    parse_stalled: 1,
    parse_failed: 1,
    kb_init_failed: 0,
  },
  reparse_actionable_count: 1,
  recent_failed: [],
  diagnostic_counts: {
    configuration: 0,
    external_service: 0,
    source_content: 0,
    permission: 0,
    platform: 0,
    unknown: 0,
  },
  title_visible: true,
  last_reconcile: null,
};

function renderPage() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AdminOverviewPage />
    </MemoryRouter>,
  );
}

describe("AdminOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(auth.capabilities, {
      isAdmin: true,
      isBoss: true,
      isConsultingDirector: false,
      isBusinessUser: true,
      isGovernance: true,
      hasProject: true,
      isProjectManager: true,
    });
    vi.mocked(fetchAdminIngest).mockResolvedValue({ items: [ingestFailure], total: 1 });
    vi.mocked(fetchOpsIndexing).mockResolvedValue(indexing);
    vi.mocked(fetchWecomScanConfigs).mockResolvedValue({
      items: [
        {
          id: "scan-secret",
          name: "项目扫描",
          scope_type: "project",
          related_project_id: "project-secret",
          related_project_name: "Alpha 项目",
          scan_space_status: "ready",
          manager_access_status: "ready",
          enabled: true,
          created_by: "user-secret",
          task_owner_name: "王顾问",
          task_owner_role_label: "项目经理",
          scan_frequency: null,
          last_scan_at: null,
          created_at: "2026-08-14T01:00:00Z",
          updated_at: "2026-08-14T01:00:00Z",
        },
      ],
    });
    vi.mocked(fetchWeknoraModels).mockResolvedValue([
      {
        model_ref: "model-secret",
        name: "Embedding",
        type: "embedding",
        source: "remote",
        provider: "provider",
        enabled: true,
        is_builtin: false,
        description: null,
        credential_status: "configured",
      },
    ]);
    vi.mocked(fetchWeknoraKbConfigs).mockResolvedValue([]);
    vi.mocked(fetchAudit).mockResolvedValue({
      items: [
        {
          id: "audit-secret",
          log_type: "operation",
          action: "config.permission_rule_updated",
          actor_user_id: "actor-secret",
          actor_name: "治理管理员",
          actor_company_role: "boss",
          actor_project_role: null,
          target_type: "permission_rule",
          target_id: "rule-secret",
          severity: null,
          is_processed: true,
          processed_by: null,
          processed_at: null,
          trace_id: "trace-secret",
          denied_reason: null,
          risk_level: null,
          created_at: "2026-08-14T01:00:00Z",
          before_snapshot: null,
          after_snapshot: null,
          extra: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 80,
      view: "governance",
    });
  });

  it("turns authorized real status into actions, runtime rows, and governance changes", async () => {
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "运营中枢" })).toBeInTheDocument();
    expect(await screen.findByText("入库失败")).toBeInTheDocument();
    expect(screen.getByText("索引或知识库连接失败")).toBeInTheDocument();
    expect(screen.getByText("解析与索引")).toBeInTheDocument();
    expect(screen.getByText("更新权限规则")).toBeInTheDocument();
    expect(screen.getByText("状态已更新")).toBeInTheDocument();
    for (const secret of ["ingest-secret", "audit-secret", "trace-secret", "model-secret"])
      expect(container.innerHTML).not.toContain(secret);
  });

  it("does not manufacture zero-value risk cards when no action is needed", async () => {
    vi.mocked(fetchAdminIngest).mockResolvedValueOnce({ items: [], total: 0 });
    vi.mocked(fetchOpsIndexing).mockResolvedValueOnce({
      ...indexing,
      counts: Object.fromEntries(
        Object.keys(indexing.counts).map((key) => [key, 0]),
      ) as typeof indexing.counts,
    });
    vi.mocked(fetchAudit).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 80,
      view: "governance",
    });
    renderPage();

    expect(await screen.findByText("当前没有需要管理员处理的事项")).toBeInTheDocument();
    expect(screen.queryByText("入库失败")).not.toBeInTheDocument();
  });

  it("only requests workspaces allowed for a project manager", async () => {
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isBoss: false,
      isGovernance: false,
      isProjectManager: true,
    });
    renderPage();

    await waitFor(() => expect(fetchWecomScanConfigs).toHaveBeenCalledTimes(1));
    expect(fetchWeknoraModels).toHaveBeenCalledTimes(1);
    expect(fetchWeknoraKbConfigs).toHaveBeenCalledTimes(1);
    expect(fetchAdminIngest).not.toHaveBeenCalled();
    expect(fetchOpsIndexing).not.toHaveBeenCalled();
    expect(fetchAudit).not.toHaveBeenCalled();
  });

  it("refreshes affected summaries when an admin write succeeds", async () => {
    renderPage();
    await waitFor(() => expect(fetchAdminIngest).toHaveBeenCalledTimes(1));

    act(() => window.dispatchEvent(new CustomEvent(ADMIN_OVERVIEW_INVALIDATED_EVENT)));

    await waitFor(() => expect(fetchAdminIngest).toHaveBeenCalledTimes(2));
    expect(fetchOpsIndexing).toHaveBeenCalledTimes(2);
  });
});
