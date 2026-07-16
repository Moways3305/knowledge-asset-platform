import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeDetailPage, { OnlyOfficePreview } from "./KnowledgeDetailPage";
import {
  fetchKnowledgeDetail,
  fetchPreviewEntry,
  issuePreview,
  requestOriginalAccess,
} from "../api/knowledge";
import type { KnowledgeDetailVM } from "../types/knowledge";
import type { PreviewEntryVM } from "../types/preview";

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

const baseAsset: KnowledgeDetailVM = {
  id: "asset-1",
  title: "项目复盘方法论",
  scope: "personal",
  zone: "consulting",
  assetType: "methodology",
  confidentialityLevel: "L2",
  aiAccessLevel: "A2",
  assetStatus: "active",
  visibility: "public",
  tags: ["复盘", "交付"],
  summary: "帮助项目组沉淀关键经验。",
  projectName: "Alpha 项目",
  lifecyclePhase: "复盘",
  confidence: 0.92,
  lastCalledAt: "",
  updatedAt: "2026-07-08T08:00:00Z",
  access: {
    discovery: true,
    summary: true,
    original: true,
    effectiveSource: "owner",
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
  indexedAt: "2026-07-08T08:10:00Z",
  projectId: "project-1",
  maintainerName: "Alice",
  archivedAt: null,
  archiveReason: null,
  oneLiner: "帮助项目组沉淀关键经验。",
  detailed: "适用于交付后复盘，关注客户反馈、行动项与方法沉淀。",
  keyPoints: ["复盘节奏", "行动项"],
  currentVersionNo: "v1",
  indexErrorCode: null,
};

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/knowledge/asset-1"]}>
      <Routes>
        <Route path="/knowledge/:id" element={<KnowledgeDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("KnowledgeDetailPage", () => {
  beforeEach(() => {
    vi.mocked(fetchKnowledgeDetail).mockReset();
    vi.mocked(issuePreview).mockReset();
    vi.mocked(fetchPreviewEntry).mockReset();
    vi.mocked(requestOriginalAccess).mockReset();
  });

  it("opens a frontend preview shell instead of exposing preview JSON", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue(baseAsset);
    vi.mocked(issuePreview).mockResolvedValue({
      credential_id: "credential-secret",
      preview_type: "full",
      credential_fingerprint: "fingerprint-secret",
      preview_entry_url: "/api/v1/preview/credential-secret",
      expires_at: "2026-07-08T08:30:00Z",
      credential_status: "active",
    });
    vi.mocked(fetchPreviewEntry).mockResolvedValue({
      previewType: "full",
      documentTitle: "项目复盘方法论.docx",
      expiresAt: "2026-07-08T08:30:00Z",
      status: "active",
      onlyofficeConfig: null,
      message: "onlyoffice_not_configured",
    });

    renderDetail();

    fireEvent.click((await screen.findAllByRole("button", { name: "预览原文" }))[0]);

    expect(await screen.findByRole("dialog", { name: "原文预览" })).toBeInTheDocument();
    expect(screen.getByText("项目复盘方法论.docx")).toBeInTheDocument();
    expect(screen.getByText(/在线预览服务暂未启用/)).toBeInTheDocument();
    expect(fetchPreviewEntry).toHaveBeenCalledWith("/api/v1/preview/credential-secret");

    const visibleText = document.body.textContent ?? "";
    expect(visibleText).not.toContain("credential-secret");
    expect(visibleText).not.toContain("fingerprint-secret");
    expect(visibleText).not.toContain("onlyoffice_config");
    expect(visibleText).not.toContain("documentServerUrl");
  });

  it("shows knowledge card and asks for original access when original permission is missing", async () => {
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...baseAsset,
      access: {
        ...baseAsset.access,
        original: false,
        canRequestOriginal: true,
      },
    });
    vi.mocked(requestOriginalAccess).mockResolvedValue({
      status: "created",
      message: "created",
      request: null,
      grant: null,
    });

    renderDetail();

    expect(await screen.findByRole("heading", { name: "项目复盘方法论" })).toBeInTheDocument();
    expect(screen.queryByText("处理进度")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "申请原文访问" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "申请原文访问" }));
    await waitFor(() => expect(requestOriginalAccess).toHaveBeenCalledWith("asset-1"));
    expect(await screen.findByText("原文访问申请已提交，待审批。")).toBeInTheDocument();
    expect(screen.queryByText("原文入口")).not.toBeInTheDocument();
  });
});

type PreviewEvents = {
  onDocumentReady: () => void;
  onError: () => void;
  onWarning: () => void;
};

const controlledPreviewEntry = (key: string): PreviewEntryVM => ({
  previewType: "full",
  documentTitle: "受控文档.docx",
  expiresAt: "2026-07-14T08:30:00Z",
  status: "active",
  message: null,
  onlyofficeConfig: {
    documentServerUrl: "https://document-service.invalid",
    documentType: "word",
    token: `sensitive-jwt-${key}`,
    document: {
      title: "受控文档.docx",
      fileType: "docx",
      key,
      url: `https://platform.invalid/api/v1/preview/hidden/file?ft=sensitive-fetch-${key}`,
    },
    editorConfig: { mode: "view" },
  },
});

describe("OnlyOfficePreview", () => {
  afterEach(() => {
    delete window.DocsAPI;
    document
      .querySelectorAll("script[data-onlyoffice-preview]")
      .forEach((script) => script.remove());
    vi.useRealTimers();
  });

  it("removes the loading layer only after the official document-ready event", () => {
    let events: PreviewEvents | null = null;
    class ReadyEditor {
      destroyEditor = vi.fn();
      constructor(_holder: string, config: Record<string, unknown>) {
        events = config.events as PreviewEvents;
      }
    }
    window.DocsAPI = { DocEditor: ReadyEditor };

    render(<OnlyOfficePreview entry={controlledPreviewEntry("ready")} />);
    expect(screen.getByText("文档预览正在打开，请稍候。")).toBeInTheDocument();
    act(() => events?.onDocumentReady());

    expect(screen.queryByText("文档预览正在打开，请稍候。")).not.toBeInTheDocument();
    expect(screen.getByLabelText("原文在线预览")).toBeVisible();
  });

  it("turns an api.js network or CSP failure into a safe retry state", () => {
    render(<OnlyOfficePreview entry={controlledPreviewEntry("script-error")} />);
    const script = document.querySelector<HTMLScriptElement>("script[data-onlyoffice-preview]");
    expect(script).not.toBeNull();
    fireEvent.error(script!);

    expect(screen.getByText("在线预览服务不可达或被浏览器策略阻止。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新打开预览" })).toBeInTheDocument();
    const lateEditor = vi.fn();
    window.DocsAPI = { DocEditor: lateEditor as never };
    fireEvent.load(script!);
    expect(lateEditor).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toMatch(/sensitive-(jwt|fetch)/);
  });

  it("handles constructor and editor event failures without exposing upstream details", () => {
    class ThrowingEditor {
      constructor() {
        throw new Error("sensitive upstream response");
      }
    }
    window.DocsAPI = { DocEditor: ThrowingEditor };
    const { unmount } = render(<OnlyOfficePreview entry={controlledPreviewEntry("throw")} />);
    expect(screen.getByText("文档加载失败，请关闭后重试。")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("sensitive upstream response");
    unmount();

    let events: PreviewEvents | null = null;
    class ErrorEditor {
      constructor(_holder: string, config: Record<string, unknown>) {
        events = config.events as PreviewEvents;
      }
    }
    window.DocsAPI = { DocEditor: ErrorEditor };
    render(<OnlyOfficePreview entry={controlledPreviewEntry("event")} />);
    act(() => events?.onError());
    expect(screen.getByText("文档加载失败，请关闭后重试。")).toBeInTheDocument();
  });

  it("stops loading after a finite timeout", () => {
    vi.useFakeTimers();
    render(<OnlyOfficePreview entry={controlledPreviewEntry("timeout")} />);

    act(() => vi.advanceTimersByTime(20_000));

    expect(screen.getByText("预览超时，请重新打开预览。")).toBeInTheDocument();
    expect(screen.queryByText("文档预览正在打开，请稍候。")).not.toBeInTheDocument();
  });

  it("ignores stale callbacks after closing or switching preview credentials", () => {
    const eventSets: PreviewEvents[] = [];
    const destroyEditor = vi.fn();
    class TrackedEditor {
      destroyEditor = destroyEditor;
      constructor(_holder: string, config: Record<string, unknown>) {
        eventSets.push(config.events as PreviewEvents);
      }
    }
    window.DocsAPI = { DocEditor: TrackedEditor };
    const { rerender } = render(<OnlyOfficePreview entry={controlledPreviewEntry("first")} />);
    rerender(<OnlyOfficePreview entry={controlledPreviewEntry("second")} />);

    act(() => eventSets[0].onError());
    expect(screen.queryByText("文档加载失败，请关闭后重试。")).not.toBeInTheDocument();
    act(() => eventSets[1].onDocumentReady());
    expect(screen.queryByText("文档预览正在打开，请稍候。")).not.toBeInTheDocument();
    expect(destroyEditor).toHaveBeenCalled();
  });
});
