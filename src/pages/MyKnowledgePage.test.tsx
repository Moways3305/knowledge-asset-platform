import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { fetchAuthMe } from "../api/auth";
import {
  confirmPersonalAsset,
  createMyKnowledgeBase,
  fetchMyKnowledge,
  fetchMyKnowledgeBase,
  registerPersonalKnowledgeEvidence,
  renameMyKnowledgeBase,
  submitPersonalKnowledge,
} from "../api/personal";
import type { KnowledgeCardVM } from "../types/knowledge";
import MyKnowledgePage from "./MyKnowledgePage";

vi.mock("../api/auth", () => ({ fetchAuthMe: vi.fn() }));
vi.mock("../api/personal", () => ({
  fetchMyKnowledge: vi.fn(),
  confirmPersonalAsset: vi.fn(),
  submitPersonalKnowledge: vi.fn(),
  registerPersonalKnowledgeEvidence: vi.fn(),
  fetchMyKnowledgeBase: vi.fn(),
  createMyKnowledgeBase: vi.fn(),
  renameMyKnowledgeBase: vi.fn(),
}));
vi.mock("../hooks/useModelSelection", () => ({
  useModelSelection: () => ({
    loading: false,
    loaded: true,
    weknoraDisabled: true,
    defaultMissing: false,
    embeddingOptions: [],
    rerankOptions: [],
    embeddingRef: "",
    rerankRef: "",
    setEmbeddingRef: vi.fn(),
    setRerankRef: vi.fn(),
    reload: vi.fn(),
    blockSubmit: false,
  }),
}));

const draft: KnowledgeCardVM = {
  id: "asset-draft-82",
  title: "客户访谈整理",
  scope: "personal",
  zone: "material",
  assetType: "insight",
  confidentialityLevel: "L2",
  aiAccessLevel: "A2",
  assetStatus: "active",
  visibility: "confidential",
  tags: [],
  summary: "",
  projectName: "",
  lifecyclePhase: "",
  confidence: null,
  lastCalledAt: "",
  updatedAt: "2026-07-17T02:30:00Z",
  access: {
    discovery: true,
    summary: true,
    original: true,
    effectiveSource: "owner",
    canRequestOriginal: false,
    existingRequestStatus: null,
    existingGrantExpiresAt: null,
    canDelete: true,
    canManageLifecycle: true,
    canRetryIndex: false,
  },
  indexStatus: null,
  parseStatus: null,
  indexErrorMessage: null,
  indexedAt: null,
};

const confirmed = {
  ...draft,
  id: "asset-confirmed-82",
  title: "项目复盘模板",
  zone: "asset",
  assetType: "template",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <MyKnowledgePage />
    </MemoryRouter>,
  );
}

describe("MyKnowledgePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMyKnowledge).mockResolvedValue([draft, confirmed]);
    vi.mocked(fetchMyKnowledgeBase).mockResolvedValue({
      exists: true,
      display_name: "林顾问的知识库",
      status: "active",
      knowledge_count: 2,
      embedding_model_ref: "secret-model-ref",
    });
    vi.mocked(fetchAuthMe).mockResolvedValue({
      userId: "user-82",
      name: "林顾问",
      email: "lin@example.test",
      companyRoles: ["consultant"],
      isBusinessUser: true,
      canDiscoverL5: false,
      projects: [
        { projectId: "project-82", projectName: "华东交付项目", projectRole: "consultant" },
      ],
    });
    vi.mocked(confirmPersonalAsset).mockResolvedValue({
      asset_id: "asset-draft-82",
      zone: "asset",
      status: "active",
      message: "server secret message",
    });
    vi.mocked(submitPersonalKnowledge).mockResolvedValue({
      submission_id: "submission-82",
      asset_id: "asset-confirmed-82",
      target_project_id: "project-82",
      target_project_name: "华东交付项目",
      submission_type: "project_submission",
      status: "pending_reviewer",
      review_task_id: "review-82",
      evidence_id: null,
      created_at: "2026-07-17T02:30:00Z",
      message: "已正式加入项目知识库",
      next_action: "secret action",
    });
    vi.mocked(registerPersonalKnowledgeEvidence).mockResolvedValue({
      submission_id: "evidence-82",
      asset_id: "asset-confirmed-82",
      target_project_id: "project-82",
      target_project_name: "华东交付项目",
      submission_type: "validation_evidence",
      status: "pending_reviewer",
      review_task_id: "review-82",
      evidence_id: "candidate-82",
      created_at: "2026-07-17T02:30:00Z",
      message: "客户已验证通过",
      next_action: "secret action",
    });
    vi.mocked(createMyKnowledgeBase).mockResolvedValue({
      exists: true,
      display_name: "我的知识库",
      status: "active",
    });
    vi.mocked(renameMyKnowledgeBase).mockResolvedValue({
      exists: true,
      display_name: "新名称",
      status: "active",
    });
  });

  it("renders the compact repository table and never exposes model refs", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "个人资料" })).toBeInTheDocument();
    expect(screen.getByText("资料总数").nextSibling).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: "客户访谈整理" })).toHaveAttribute(
      "href",
      "/knowledge/asset-draft-82",
    );
    expect(screen.getAllByText("待本人确认").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("本人已确认").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("secret-model-ref")).not.toBeInTheDocument();
    expect(screen.queryByText(/索引分布|模型引用|WorkBuddy/)).not.toBeInTheDocument();
  });

  it("shows a strict forbidden state without fallback content", async () => {
    vi.mocked(fetchMyKnowledge).mockRejectedValue(
      new ApiError(403, "secret denied", "secret_reason"),
    );
    vi.mocked(fetchMyKnowledgeBase).mockRejectedValue(new ApiError(403, "secret denied"));
    renderPage();

    expect(await screen.findByText("当前身份无法使用个人知识")).toBeInTheDocument();
    expect(screen.queryByText("客户访谈整理")).not.toBeInTheDocument();
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
  });

  it("uses safe fallbacks for unknown backend enums", async () => {
    vi.mocked(fetchMyKnowledge).mockResolvedValue([
      { ...draft, assetType: "secret_type", zone: "secret_zone" },
    ]);
    renderPage();

    expect((await screen.findAllByText("信息待确认")).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("secret_type")).not.toBeInTheDocument();
    expect(screen.queryByText("secret_zone")).not.toBeInTheDocument();
  });

  it("confirms a draft through a controlled dialog and refreshes the list", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("客户访谈整理");

    await user.click(screen.getByRole("button", { name: "本人确认" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/不会将资料公开或加入项目/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "确认资产" }));

    await waitFor(() => expect(confirmPersonalAsset).toHaveBeenCalledWith("asset-draft-82"));
    expect(await screen.findByText("已确认为个人知识资产")).toBeInTheDocument();
    expect(screen.queryByText("server secret message")).not.toBeInTheDocument();
  });

  it("submits only to active auth projects and keeps the pending-review wording", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("项目复盘模板");

    await user.click(screen.getByRole("button", { name: "提交项目" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("option", { name: "华东交付项目" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "提交" }));

    expect(await screen.findByText("已提交，等待项目经理确认")).toBeInTheDocument();
    expect(submitPersonalKnowledge).toHaveBeenCalledWith("asset-confirmed-82", {
      target_project_id: "project-82",
    });
    expect(screen.queryByText("已正式加入项目知识库")).not.toBeInTheDocument();
  });

  it("registers evidence as a candidate and never upgrades the server message", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("项目复盘模板");

    const row = screen.getByRole("link", { name: "项目复盘模板" }).closest("tr");
    await user.click(within(row as HTMLElement).getByRole("button", { name: "登记证据" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("证据类型"), {
      target: { value: "client_validation" },
    });
    await user.click(within(dialog).getByRole("button", { name: "登记候选" }));

    expect(await screen.findByText("候选证据已登记，等待项目经理审核")).toBeInTheDocument();
    expect(registerPersonalKnowledgeEvidence).toHaveBeenCalledWith(
      "asset-confirmed-82",
      expect.objectContaining({
        target_project_id: "project-82",
        evidence_type: "client_validation",
      }),
    );
    expect(screen.queryByText("客户已验证通过")).not.toBeInTheDocument();
  });

  it("disables project actions when auth has no active project", async () => {
    vi.mocked(fetchAuthMe).mockResolvedValue({
      userId: "user-82",
      name: "林顾问",
      email: "lin@example.test",
      companyRoles: ["consultant"],
      isBusinessUser: true,
      canDiscoverL5: false,
      projects: [],
    });
    renderPage();

    const submit = await screen.findByRole("button", { name: "提交项目" });
    expect(submit).toBeDisabled();
    expect(screen.getAllByText("暂无可用项目").length).toBeGreaterThan(0);
  });

  it("creates a knowledge base in a dialog", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchMyKnowledgeBase).mockResolvedValue({ exists: false });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "创建知识库" }));
    await user.type(screen.getByLabelText("知识库名称（可选）"), "个人方法库");
    await user.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() =>
      expect(createMyKnowledgeBase).toHaveBeenCalledWith(
        expect.objectContaining({ displayName: "个人方法库" }),
      ),
    );
  });

  it("renames an existing knowledge base and reports sync failure safely", async () => {
    const user = userEvent.setup();
    vi.mocked(renameMyKnowledgeBase).mockResolvedValue({
      exists: true,
      display_name: "新名称",
      status: "active",
      weknora_sync_failed: true,
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "修改名称" }));
    const input = screen.getByLabelText("知识库名称");
    await user.clear(input);
    await user.type(input, "新名称");
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(await screen.findByText("名称已保存，检索服务同步稍后重试")).toBeInTheDocument();
    expect(renameMyKnowledgeBase).toHaveBeenCalledWith("新名称");
  });
});
