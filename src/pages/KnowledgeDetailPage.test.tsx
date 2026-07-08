import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeDetailPage from "./KnowledgeDetailPage";
import {
  fetchKnowledgeDetail,
  fetchPreviewEntry,
  issuePreview,
  requestOriginalAccess,
} from "../api/knowledge";
import type { KnowledgeDetailVM } from "../types/knowledge";

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

    expect(await screen.findByText("知识卡片")).toBeInTheDocument();
    expect(screen.getByText("处理进度")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "申请原文访问" }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("button", { name: "申请原文访问" })[0]);
    await waitFor(() => expect(requestOriginalAccess).toHaveBeenCalledWith("asset-1"));
    expect(await screen.findByText("原文访问申请已提交，待审批。")).toBeInTheDocument();
    expect(screen.getByText("来源与治理状态")).not.toBeVisible();
  });
});
