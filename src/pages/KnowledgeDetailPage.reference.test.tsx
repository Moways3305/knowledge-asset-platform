import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import {
  deleteKnowledgeAsset,
  fetchKnowledgeDetail,
  fetchLifecycleEvents,
  lifecycleArchiveConfirm,
  lifecycleArchiveRequest,
  requestOriginalAccess,
  retryKnowledgeIndex,
} from "../api/knowledge";
import type { KnowledgeDetailVM } from "../types/knowledge";
import KnowledgeDetailPage from "./KnowledgeDetailPage";

vi.mock("../api/knowledge", () => ({
  deleteKnowledgeAsset: vi.fn(),
  fetchKnowledgeDetail: vi.fn(),
  fetchLifecycleEvents: vi.fn(),
  fetchPreviewEntry: vi.fn(),
  issuePreview: vi.fn(),
  lifecycleArchiveConfirm: vi.fn(),
  lifecycleArchiveRequest: vi.fn(),
  requestOriginalAccess: vi.fn(),
  retryKnowledgeIndex: vi.fn(),
}));

const asset: KnowledgeDetailVM = {
  id: "asset-76",
  title: "客户增长项目复盘方法论",
  scope: "project",
  zone: "asset",
  assetType: "methodology",
  confidentialityLevel: "L3",
  aiAccessLevel: "A2",
  assetStatus: "active",
  visibility: "project-only",
  tags: ["增长", "复盘"],
  summary: "归纳增长项目中的验证路径。",
  projectName: "增长策略项目",
  lifecyclePhase: "项目复盘",
  confidence: 0.94,
  lastCalledAt: "",
  updatedAt: "2026-07-15T08:00:00Z",
  access: {
    discovery: true,
    summary: true,
    original: true,
    effectiveSource: "project_role",
    canRequestOriginal: false,
    existingRequestStatus: null,
    existingGrantExpiresAt: null,
    canDelete: false,
    canManageLifecycle: false,
    canRetryIndex: false,
  },
  indexStatus: "indexed",
  parseStatus: "success",
  indexErrorMessage: null,
  indexedAt: "2026-07-15T08:10:00Z",
  projectId: "project-76",
  maintainerName: "王顾问",
  archivedAt: null,
  archiveReason: null,
  oneLiner: "归纳增长项目中的验证路径。",
  detailed: "覆盖目标拆解、假设验证和复盘沉淀三个阶段。",
  keyPoints: ["先验证关键假设", "复盘结论进入项目知识"],
  currentVersionNo: "v2",
  indexErrorCode: null,
};

function renderDetail() {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      initialEntries={["/knowledge/asset-76"]}
    >
      <Routes>
        <Route path="/knowledge/:id" element={<KnowledgeDetailPage />} />
        <Route path="/knowledge" element={<div>知识资产库列表</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("KnowledgeDetailPage reference contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue(asset);
    vi.mocked(fetchLifecycleEvents).mockResolvedValue({ items: [] });
  });

  it("renders the real summary, core facts and exactly one original action", async () => {
    renderDetail();

    expect(await screen.findByRole("heading", { name: asset.title })).toBeInTheDocument();
    expect(screen.getByText(asset.oneLiner)).toBeInTheDocument();
    expect(screen.getByText(asset.detailed)).toBeInTheDocument();
    expect(screen.getByText("先验证关键假设")).toBeInTheDocument();
    expect(screen.getByText("增长策略项目")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "预览原文" })).toHaveLength(1);
    expect(screen.queryByText("处理进度")).not.toBeInTheDocument();
    expect(screen.queryByText("原文入口")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("asset-76");
    expect(document.body.textContent).not.toContain("project-76");
  });

  it("shows the only request action for summary-only access", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...asset,
      access: { ...asset.access, original: false, canRequestOriginal: true },
    });
    vi.mocked(requestOriginalAccess).mockResolvedValue({
      status: "created",
      message: "created",
      request: null,
      grant: null,
    });
    renderDetail();

    const button = await screen.findByRole("button", { name: "申请原文访问" });
    expect(screen.queryByRole("button", { name: "预览原文" })).not.toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() => expect(requestOriginalAccess).toHaveBeenCalledWith("asset-76"));
    expect(await screen.findByText("原文访问申请已提交，待审批。")).toBeInTheDocument();
  });

  it("shows a disabled pending state without another original action", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...asset,
      access: {
        ...asset.access,
        original: false,
        canRequestOriginal: true,
        existingRequestStatus: "pending",
      },
    });
    renderDetail();

    expect(await screen.findByRole("button", { name: "申请审批中" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "申请原文访问" })).not.toBeInTheDocument();
    expect(screen.getByText("审批中")).toBeInTheDocument();
  });

  it("does not render protected summary content", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...asset,
      access: { ...asset.access, summary: false, original: false },
    });
    renderDetail();

    expect(await screen.findByText("当前身份不可查看内容摘要。")).toBeInTheDocument();
    expect(screen.queryByText(asset.oneLiner)).not.toBeInTheDocument();
    expect(screen.queryByText(asset.detailed)).not.toBeInTheDocument();
    expect(screen.queryByText("先验证关键假设")).not.toBeInTheDocument();
  });

  it("uses finite loading, unified denied state and a retryable load failure", async () => {
    let resolveDetail: ((value: KnowledgeDetailVM) => void) | undefined;
    vi.mocked(fetchKnowledgeDetail).mockImplementationOnce(
      () => new Promise((resolve) => (resolveDetail = resolve)),
    );
    const loadingView = renderDetail();
    expect(screen.getByText("正在加载资产详情…")).toBeInTheDocument();
    resolveDetail?.(asset);
    expect(await screen.findByRole("heading", { name: asset.title })).toBeInTheDocument();
    loadingView.unmount();

    vi.mocked(fetchKnowledgeDetail).mockRejectedValueOnce(new ApiError(403, "secret policy"));
    const deniedView = renderDetail();
    expect(await screen.findByRole("heading", { name: "未找到或无权查看" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("secret policy");
    deniedView.unmount();

    vi.mocked(fetchKnowledgeDetail)
      .mockRejectedValueOnce(new Error("upstream SECRET-LIKE"))
      .mockResolvedValueOnce(asset);
    renderDetail();
    expect(await screen.findByRole("heading", { name: "资产详情加载失败" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SECRET-LIKE");
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("heading", { name: asset.title })).toBeInTheDocument();
  });

  it("loads lifecycle records only after expansion", async () => {
    const lifecycleCases = [
      ["archive_warning", "归档预警"],
      ["archive_candidate", "归档候选"],
      ["archived", "资产已归档"],
      ["reenable_requested", "申请重新启用"],
      ["reenabled", "资产已重新启用"],
      ["status_changed", "资产状态已变更"],
    ] as const;
    vi.mocked(fetchLifecycleEvents).mockResolvedValue({
      items: lifecycleCases.map(([eventType], index) => ({
        event_id: `event-${index}`,
        event_type: eventType,
        old_status: "active",
        new_status: "active",
        reason: "完成年度复核",
        actor_display: "治理负责人",
        created_at: "2026-07-15T10:00:00Z",
        trace_id: "hidden-trace",
      })),
    });
    renderDetail();

    const lifecycle = await screen.findByText("生命周期");
    expect(fetchLifecycleEvents).not.toHaveBeenCalled();
    fireEvent.click(lifecycle);
    for (const [, label] of lifecycleCases) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
    expect(fetchLifecycleEvents).toHaveBeenCalledTimes(1);
    const visibleText = document.body.textContent ?? "";
    expect(visibleText).not.toContain("hidden-trace");
    for (const [eventType] of lifecycleCases) {
      expect(visibleText).not.toContain(eventType);
    }
  });

  it("shows a safe lifecycle error and retries", async () => {
    vi.mocked(fetchLifecycleEvents)
      .mockRejectedValueOnce(new Error("SECRET-LIKE lifecycle payload"))
      .mockResolvedValueOnce({ items: [] });
    renderDetail();

    fireEvent.click(await screen.findByText("生命周期"));
    expect(await screen.findByText("生命周期记录加载失败，请重试。")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SECRET-LIKE");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("暂无生命周期记录")).toBeInTheDocument();
    expect(fetchLifecycleEvents).toHaveBeenCalledTimes(2);
  });

  it("hides governance actions without server-granted capabilities", async () => {
    renderDetail();
    await screen.findByRole("heading", { name: asset.title });
    expect(screen.queryByText("更多操作")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /删除资产/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重新处理问答/ })).not.toBeInTheDocument();
  });

  it("lets a maintainer archive without granting delete permission", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...asset,
      access: {
        ...asset.access,
        canDelete: false,
        canManageLifecycle: true,
        canRetryIndex: false,
      },
    });
    vi.mocked(lifecycleArchiveRequest).mockResolvedValue({
      lifecycle_event_id: "event-maintainer",
      review_task_id: null,
      status: "candidate",
      trace_id: "trace-hidden",
    });
    renderDetail();

    fireEvent.click(await screen.findByText("更多操作"));
    const operations = screen.getByText("更多操作").closest("details")!;
    expect(within(operations).getByRole("button", { name: /发起归档候选/ })).toBeInTheDocument();
    expect(within(operations).getByRole("button", { name: "确认归档" })).toBeInTheDocument();
    expect(within(operations).queryByRole("button", { name: /删除资产/ })).not.toBeInTheDocument();

    fireEvent.change(within(operations).getByLabelText("归档原因"), {
      target: { value: "维护人完成复核" },
    });
    fireEvent.click(within(operations).getByRole("button", { name: /发起归档候选/ }));
    await waitFor(() =>
      expect(lifecycleArchiveRequest).toHaveBeenCalledWith("asset-76", {
        reason: "维护人完成复核",
        candidate_source: "manual",
      }),
    );
  });

  it("gates real archive, retry and delete calls behind the expanded operations", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...asset,
      indexStatus: "index_failed",
      access: {
        ...asset.access,
        canDelete: true,
        canManageLifecycle: true,
        canRetryIndex: true,
      },
    });
    vi.mocked(lifecycleArchiveRequest).mockResolvedValue({
      lifecycle_event_id: "event-2",
      review_task_id: null,
      status: "candidate",
      trace_id: "trace-hidden",
    });
    vi.mocked(lifecycleArchiveConfirm).mockResolvedValue({
      asset_id: "asset-76",
      asset_status: "archived",
      archived_at: "2026-07-16T08:00:00Z",
      archive_reason: "完成复核",
      trace_id: "trace-hidden",
    });
    vi.mocked(retryKnowledgeIndex).mockResolvedValue({
      asset_id: "asset-76",
      index_status: "indexed",
      weknora_parse_status: null,
      index_error_code: null,
      index_error_message: null,
      trace_id: "trace-hidden",
    });
    vi.mocked(deleteKnowledgeAsset).mockResolvedValue({
      asset_id: "asset-76",
      asset_status: "archived",
      deleted_at: "2026-07-16T08:00:00Z",
      trace_id: "trace-hidden",
    });
    renderDetail();

    fireEvent.click(await screen.findByText("更多操作"));
    const operations = screen.getByText("更多操作").closest("details")!;
    fireEvent.click(within(operations).getByRole("button", { name: /发起归档候选/ }));
    expect(await within(operations).findByText("请填写归档原因。")).toBeInTheDocument();
    fireEvent.change(within(operations).getByLabelText("归档原因"), {
      target: { value: "完成复核" },
    });
    fireEvent.click(within(operations).getByRole("button", { name: /发起归档候选/ }));
    await waitFor(() =>
      expect(lifecycleArchiveRequest).toHaveBeenCalledWith("asset-76", {
        reason: "完成复核",
        candidate_source: "manual",
      }),
    );
    fireEvent.click(within(operations).getByRole("button", { name: /重新处理问答/ }));
    await waitFor(() => expect(retryKnowledgeIndex).toHaveBeenCalledWith("asset-76"));
    fireEvent.click(within(operations).getByRole("button", { name: /删除资产/ }));
    fireEvent.click(within(operations).getByRole("button", { name: "确认删除" }));
    expect(await within(operations).findByText("请填写删除原因。")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("trace-hidden");
  });
});
