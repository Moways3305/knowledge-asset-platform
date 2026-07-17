import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAuthMe } from "../api/auth";
import { ApiError } from "../api/http";
import { deleteKnowledgeAsset } from "../api/knowledge";
import {
  confirmPersonalAsset,
  createMyKnowledgeBase,
  fetchMyKnowledge,
  fetchMyKnowledgeBase,
  registerPersonalKnowledgeEvidence,
  renameMyKnowledgeBase,
  submitPersonalKnowledge,
  updatePersonalKnowledge,
} from "../api/personal";
import type {
  PersonalKnowledgeItemVM,
  PersonalKnowledgePageVM,
  PersonalKnowledgeState,
} from "../types/myKnowledge";
import MyKnowledgePage from "./MyKnowledgePage";

vi.mock("../api/auth", () => ({ fetchAuthMe: vi.fn() }));
vi.mock("../api/knowledge", () => ({ deleteKnowledgeAsset: vi.fn() }));
vi.mock("../api/personal", () => ({
  fetchMyKnowledge: vi.fn(),
  confirmPersonalAsset: vi.fn(),
  submitPersonalKnowledge: vi.fn(),
  registerPersonalKnowledgeEvidence: vi.fn(),
  updatePersonalKnowledge: vi.fn(),
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

function item(
  id: string,
  title: string,
  state: PersonalKnowledgeState,
  assetType = "methodology",
): PersonalKnowledgeItemVM {
  return {
    id,
    title,
    scope: "personal",
    zone: state === "awaiting_confirmation" ? "material" : "asset",
    assetType,
    confidentialityLevel: "L2",
    aiAccessLevel: "A2",
    assetStatus: "active",
    visibility: "confidential",
    tags: ["治理", "访谈"],
    summary: "",
    projectName: "",
    lifecyclePhase: "",
    confidence: null,
    lastCalledAt: "",
    updatedAt: "2026-07-17T02:30:00Z",
    createdAt: "2026-07-10T02:30:00Z",
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
    personalState: state,
    personalStateLabel: "server label must not render",
    projectSubmission:
      state === "pending_project_review" || state === "active_in_project"
        ? {
            status: state === "active_in_project" ? "approved" : "pending",
            target_project_name: "企业知识治理项目",
            submitted_at: "2026-07-16T02:30:00Z",
            resolved_at: null,
          }
        : null,
    evidenceSummary:
      id === "ready-83"
        ? { registered_count: 2, latest_status: "pending", updated_at: "2026-07-17T02:30:00Z" }
        : null,
  };
}

const items = [
  item("draft-83", "客户访谈整理", "awaiting_confirmation", "insight"),
  item("ready-83", "项目复盘模板", "ready_to_submit", "template"),
  item("pending-83", "交付方案", "pending_project_review", "deliverable"),
  item("active-83", "治理方法", "active_in_project", "methodology"),
  item("rejected-83", "失败案例", "project_rejected", "case"),
];

function page(overrides: Partial<PersonalKnowledgePageVM> = {}): PersonalKnowledgePageVM {
  return {
    items,
    total: 25,
    page: 1,
    pageSize: 20,
    hasNext: true,
    summary: {
      total_assets: 25,
      awaiting_confirmation: 4,
      pending_project_review: 3,
      active_in_project: 8,
      created_this_month: 6,
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MyKnowledgePage />
    </MemoryRouter>,
  );
}

describe("MyKnowledgePage complete personal workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMyKnowledge).mockResolvedValue(page());
    vi.mocked(fetchMyKnowledgeBase).mockResolvedValue({
      exists: true,
      display_name: "林顾问的知识库",
      status: "active",
    });
    vi.mocked(fetchAuthMe).mockResolvedValue({
      userId: "user-83",
      name: "林顾问",
      email: "lin@example.test",
      companyRoles: ["consultant"],
      isBusinessUser: true,
      canDiscoverL5: false,
      projects: [
        { projectId: "project-83", projectName: "企业知识治理项目", projectRole: "consultant" },
      ],
    });
    vi.mocked(confirmPersonalAsset).mockResolvedValue({
      asset_id: "draft-83",
      zone: "asset",
      status: "confirmed",
      message: "secret server copy",
    });
    vi.mocked(submitPersonalKnowledge).mockResolvedValue({} as never);
    vi.mocked(registerPersonalKnowledgeEvidence).mockResolvedValue({} as never);
    vi.mocked(updatePersonalKnowledge).mockResolvedValue(items[1]);
    vi.mocked(deleteKnowledgeAsset).mockResolvedValue({
      asset_id: "ready-83",
      asset_status: "deleted",
      deleted_at: "2026-07-17T02:30:00Z",
      trace_id: null,
    });
    vi.mocked(createMyKnowledgeBase).mockResolvedValue({ exists: true, status: "active" });
    vi.mocked(renameMyKnowledgeBase).mockResolvedValue({
      exists: true,
      display_name: "新名称",
      status: "active",
    });
  });

  it("renders four real summary cards, type icons and localized states", async () => {
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "个人资料" })).toBeInTheDocument();
    expect(screen.getByText("资料总数").parentElement).toHaveTextContent("25");
    expect(screen.getByText("本月新增 6 份")).toBeInTheDocument();
    expect(screen.getByText("待项目审批").parentElement).toHaveTextContent("3");
    const stats = screen.getByLabelText("个人知识统计");
    expect(within(stats).getByText("已进入项目").parentElement).toHaveTextContent("8");
    expect(container.querySelectorAll(".mk83-type-icon svg")).toHaveLength(5);
    for (const label of [
      "待本人确认",
      "可提交项目",
      "待项目经理审批",
      "已进入项目",
      "项目未通过",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("已登记 2 条候选证据")).toBeInTheDocument();
    expect(screen.queryByText("server label must not render")).not.toBeInTheDocument();
  });

  it("sends search, filters, sorting and pagination to the server", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("客户访谈整理");

    await user.type(screen.getByLabelText("搜索个人资料"), "客户洞察");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() =>
      expect(fetchMyKnowledge).toHaveBeenLastCalledWith(
        expect.objectContaining({ keyword: "客户洞察", page: 1 }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "筛选" }));
    const panel = screen.getByRole("dialog", { name: "筛选个人资料" });
    await user.selectOptions(within(panel).getByLabelText("资料类型"), "template");
    await user.selectOptions(within(panel).getByLabelText("个人状态"), "pending_project_review");
    await user.selectOptions(within(panel).getByLabelText("排序方式"), "title:asc");
    await waitFor(() =>
      expect(fetchMyKnowledge).toHaveBeenLastCalledWith(
        expect.objectContaining({
          keyword: "客户洞察",
          assetType: "template",
          personalState: "pending_project_review",
          sortBy: "title",
          sortDirection: "asc",
        }),
      ),
    );
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(fetchMyKnowledge).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })),
    );
  });

  it("shows edit and delete only for an unlocked authorized item", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("项目复盘模板");

    await user.click(screen.getByRole("button", { name: "更多操作：项目复盘模板" }));
    expect(screen.getByRole("menuitem", { name: "编辑资料" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "删除资料" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "更多操作：交付方案" }));
    expect(screen.queryByRole("menuitem", { name: "编辑资料" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "删除资料" })).not.toBeInTheDocument();
  });

  it("edits safe metadata and refreshes the current query", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("项目复盘模板");
    await user.click(screen.getByRole("button", { name: "更多操作：项目复盘模板" }));
    await user.click(screen.getByRole("menuitem", { name: "编辑资料" }));
    const dialog = screen.getByRole("dialog");
    const title = within(dialog).getByLabelText("资料标题");
    await user.clear(title);
    await user.type(title, "更新后的模板");
    await user.click(within(dialog).getByRole("button", { name: "保存修改" }));

    await waitFor(() =>
      expect(updatePersonalKnowledge).toHaveBeenCalledWith(
        "ready-83",
        expect.objectContaining({ title: "更新后的模板", asset_type: "template" }),
      ),
    );
    expect(await screen.findByText("资料信息已更新")).toBeInTheDocument();
    expect(fetchMyKnowledge).toHaveBeenCalledTimes(2);
  });

  it("requires a delete confirmation and forwards the optional reason", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("项目复盘模板");
    await user.click(screen.getByRole("button", { name: "更多操作：项目复盘模板" }));
    await user.click(screen.getByRole("menuitem", { name: "删除资料" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("删除原因（可选）"), "重复上传");
    await user.click(within(dialog).getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(deleteKnowledgeAsset).toHaveBeenCalledWith("ready-83", "重复上传"));
    expect(await screen.findByText("个人资料已删除")).toBeInTheDocument();
  });

  it("keeps submission and evidence wording honest", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("项目复盘模板");
    await user.click(screen.getAllByRole("button", { name: "提交项目" })[0]);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "提交" }));
    expect(await screen.findByText("已提交，等待项目经理确认")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "更多操作：项目复盘模板" }));
    await user.click(screen.getByRole("menuitem", { name: "登记候选证据" }));
    expect(screen.getByText(/不代表分享、客户验证或项目采纳已经成立/)).toBeInTheDocument();
  });

  it("renders no-result, forbidden and safe error states", async () => {
    vi.mocked(fetchMyKnowledge).mockResolvedValue(page({ items: [], total: 0, hasNext: false }));
    const { unmount } = renderPage();
    expect(await screen.findByText("还没有个人资料")).toBeInTheDocument();
    unmount();

    vi.mocked(fetchMyKnowledge).mockRejectedValue(new ApiError(403, "secret", "secret_reason"));
    const forbidden = renderPage();
    expect(await screen.findByText("当前身份无法使用个人知识")).toBeInTheDocument();
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
    forbidden.unmount();

    vi.mocked(fetchMyKnowledge).mockRejectedValue(new ApiError(500, "SECRET-LIKE upstream"));
    renderPage();
    expect(await screen.findByText("个人资料暂时无法加载")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET-LIKE/)).not.toBeInTheDocument();
  });

  it("discards an older response after the query changes", async () => {
    const user = userEvent.setup();
    let resolveOld: (value: PersonalKnowledgePageVM) => void = () => undefined;
    vi.mocked(fetchMyKnowledge).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    );
    vi.mocked(fetchMyKnowledge).mockResolvedValueOnce(
      page({ items: [item("new-83", "新查询结果", "ready_to_submit")], total: 1, hasNext: false }),
    );
    renderPage();
    await user.type(screen.getByLabelText("搜索个人资料"), "新查询");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    expect(await screen.findByText("新查询结果")).toBeInTheDocument();
    resolveOld(page({ items: [item("old-83", "旧查询结果", "ready_to_submit")] }));
    await waitFor(() => expect(screen.queryByText("旧查询结果")).not.toBeInTheDocument());
  });

  it("preserves knowledge-base creation and rename dialogs", async () => {
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
});
