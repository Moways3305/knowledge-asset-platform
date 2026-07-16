import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchKnowledgePage } from "../api/knowledge";
import type { KnowledgeCardVM, KnowledgePageVM, KnowledgeQueryParams } from "../types/knowledge";
import KnowledgeListPage from "./KnowledgeListPage";

const PROJECT_A = "00000000-0000-0000-0000-000000000075";
const PROJECT_B = "00000000-0000-0000-0000-000000000076";

const auth = vi.hoisted(() => ({
  status: "authenticated" as "loading" | "authenticated" | "anonymous" | "error",
  capabilities: {
    isAdmin: false,
    isBoss: false,
    isConsultingDirector: false,
    isBusinessUser: true,
    isGovernance: false,
    hasProject: true,
    isProjectManager: false,
  },
  authMe: {
    userId: "user-safe-id",
    name: "知识顾问",
    email: "not-rendered@example.test",
    companyRoles: ["consultant"],
    isBusinessUser: true,
    canDiscoverL5: false,
    projects: [
      {
        projectId: "00000000-0000-0000-0000-000000000075",
        projectName: "华东交付项目",
        projectRole: "consultant",
      },
      {
        projectId: "00000000-0000-0000-0000-000000000076",
        projectName: "供应链优化项目",
        projectRole: "coach",
      },
    ],
  },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    status: auth.status,
    capabilities: auth.capabilities,
    authMe: auth.authMe,
    reload: vi.fn(),
    setAuthMe: vi.fn(),
  }),
}));

vi.mock("../api/knowledge", () => ({
  fetchKnowledgePage: vi.fn(),
}));

const restrictedAsset: KnowledgeCardVM = {
  id: "00000000-0000-0000-0000-0000000000a1",
  title: "客户经营诊断方法论",
  scope: "company",
  zone: "asset",
  assetType: "methodology",
  confidentialityLevel: "L4",
  aiAccessLevel: "A3",
  assetStatus: "active",
  visibility: "confidential",
  tags: [],
  summary: "已按当前身份提供的安全摘要，不包含客户敏感原文。",
  projectName: "",
  lifecyclePhase: "",
  confidence: null,
  lastCalledAt: "",
  updatedAt: "2026-07-15",
  access: {
    discovery: true,
    summary: true,
    original: false,
    effectiveSource: "company_role",
    canRequestOriginal: true,
    existingRequestStatus: null,
    existingGrantExpiresAt: null,
    canDelete: false,
    canRetryIndex: false,
  },
  indexStatus: "indexed",
  parseStatus: null,
  indexErrorMessage: null,
  indexedAt: null,
};

const longProjectAsset: KnowledgeCardVM = {
  ...restrictedAsset,
  id: "00000000-0000-0000-0000-0000000000a2",
  title: "这是一个用于验证表格列不会被超长资产名称撑破的项目交付方法论与实施复盘知识资产标题",
  scope: "project",
  projectName: "华东交付项目",
  assetType: "deliverable",
  confidentialityLevel: "L2",
  access: { ...restrictedAsset.access, original: true },
};

function response(
  items: KnowledgeCardVM[] = [restrictedAsset, longProjectAsset],
  overrides: Partial<KnowledgePageVM> = {},
): KnowledgePageVM {
  return {
    items,
    total: items.length,
    page: 1,
    pageSize: 20,
    hasNext: false,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <KnowledgeListPage />
    </MemoryRouter>,
  );
}

describe("KnowledgeListPage reference implementation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.status = "authenticated";
    auth.capabilities.isAdmin = false;
    auth.capabilities.isBusinessUser = true;
    auth.capabilities.hasProject = true;
    auth.authMe.isBusinessUser = true;
    auth.authMe.projects = [
      { projectId: PROJECT_A, projectName: "华东交付项目", projectRole: "consultant" },
      { projectId: PROJECT_B, projectName: "供应链优化项目", projectRole: "coach" },
    ];
    vi.mocked(fetchKnowledgePage).mockResolvedValue(response());
  });

  it("loads one server page without the former three-scope fan-out", async () => {
    renderPage();

    expect(await screen.findByText(restrictedAsset.title)).toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenCalledTimes(1);
    expect(fetchKnowledgePage).toHaveBeenCalledWith({
      page: 1,
      pageSize: 20,
      sortBy: "updated_at",
      sortDirection: "desc",
      includeArchived: false,
    });
    expect(screen.getByRole("link", { name: "上传资产" })).toHaveAttribute("href", "/upload");
    expect(screen.queryByText(/运营洞察|语义检索|新建项目知识库/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /删除|预览|下载/ })).not.toBeInTheDocument();
  });

  it("sends keyword and every governed filter to the server using real projects", async () => {
    renderPage();
    await screen.findByText(restrictedAsset.title);

    fireEvent.change(screen.getByLabelText("关键词"), { target: { value: "  供应链  " } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith(
        expect.objectContaining({ keyword: "供应链", page: 1 }),
      ),
    );

    fireEvent.change(screen.getByLabelText("资产范围"), { target: { value: "project" } });
    const projectSelect = await screen.findByLabelText("项目");
    expect(projectSelect).toHaveTextContent("华东交付项目");
    expect(projectSelect).toHaveTextContent("供应链优化项目");
    expect(projectSelect).not.toHaveTextContent(PROJECT_A);
    fireEvent.change(projectSelect, { target: { value: PROJECT_B } });
    fireEvent.change(screen.getByLabelText("资产类型"), { target: { value: "case" } });
    fireEvent.change(screen.getByLabelText("资产状态"), { target: { value: "needs_update" } });
    fireEvent.change(screen.getByLabelText("保密等级"), { target: { value: "L3" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "包含归档" }));

    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith({
        page: 1,
        pageSize: 20,
        keyword: "供应链",
        scope: "project",
        projectId: PROJECT_B,
        assetType: "case",
        assetStatus: "needs_update",
        confidentialityLevel: "L3",
        sortBy: "updated_at",
        sortDirection: "desc",
        includeArchived: true,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "重置" }));
    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith({
        page: 1,
        pageSize: 20,
        sortBy: "updated_at",
        sortDirection: "desc",
        includeArchived: false,
      }),
    );
    expect(screen.getByLabelText("关键词")).toHaveValue("");
    expect(screen.getByLabelText("资产范围")).toHaveValue("");
  });

  it("does not request a project scope when the identity has no active project relationship", async () => {
    auth.authMe.projects = [];
    auth.capabilities.hasProject = false;
    renderPage();
    await screen.findByText(restrictedAsset.title);
    expect(fetchKnowledgePage).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("资产范围"), { target: { value: "project" } });

    expect(await screen.findByText("项目范围不可用")).toBeInTheDocument();
    expect(screen.queryByLabelText("项目")).not.toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenCalledTimes(1);
  });

  it("shows safe summaries and an honest original restriction without management actions", async () => {
    renderPage();

    expect(await screen.findAllByText(restrictedAsset.summary)).toHaveLength(2);
    expect(screen.getByText("可查看摘要，原文受限")).toBeInTheDocument();
    expect(screen.getByText(longProjectAsset.title)).toBeInTheDocument();
    expect(screen.getByText("可查看摘要与原文")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "查看详情" })[0]).toHaveAttribute(
      "href",
      `/knowledge/${restrictedAsset.id}`,
    );
    expect(screen.queryByText(restrictedAsset.id)).not.toBeInTheDocument();
    expect(screen.queryByText(/storage_ref|WeKnora|token/i)).not.toBeInTheDocument();
  });

  it("keeps a pure administrator out of the business list without revealing counts", async () => {
    auth.capabilities.isAdmin = true;
    auth.capabilities.isBusinessUser = false;
    auth.authMe.isBusinessUser = false;
    auth.authMe.projects = [];
    renderPage();

    expect(await screen.findByText("当前身份不浏览业务知识")).toBeInTheDocument();
    expect(screen.getByText(/不显示任何业务知识资产或资产数量/)).toBeInTheDocument();
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "上传资产" })).not.toBeInTheDocument();
  });

  it("distinguishes filtered empty results and clears the real request filters", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(response([]));
    renderPage();
    await screen.findByText("暂无可浏览的知识资产");

    fireEvent.change(screen.getByLabelText("资产类型"), { target: { value: "template" } });
    expect(await screen.findByText("当前条件没有匹配资产")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));

    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith(
        expect.not.objectContaining({ assetType: expect.anything() }),
      ),
    );
  });

  it("shows a safe API failure and retries the same request", async () => {
    vi.mocked(fetchKnowledgePage)
      .mockRejectedValueOnce(new Error("SECRET-LIKE upstream text"))
      .mockResolvedValueOnce(response([restrictedAsset]));
    renderPage();

    expect(await screen.findByText("知识资产加载失败")).toBeInTheDocument();
    expect(screen.queryByText(/SECRET-LIKE/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText(restrictedAsset.title)).toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenCalledTimes(2);
    expect(fetchKnowledgePage).toHaveBeenNthCalledWith(2, {
      page: 1,
      pageSize: 20,
      sortBy: "updated_at",
      sortDirection: "desc",
      includeArchived: false,
    });
  });

  it("ignores an older response when a newer scope request finishes first", async () => {
    const initial = deferred<KnowledgePageVM>();
    const company = deferred<KnowledgePageVM>();
    vi.mocked(fetchKnowledgePage)
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(company.promise);
    renderPage();
    await waitFor(() => expect(fetchKnowledgePage).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("资产范围"), { target: { value: "company" } });
    await waitFor(() => expect(fetchKnowledgePage).toHaveBeenCalledTimes(2));
    await act(async () => {
      company.resolve(response([{ ...restrictedAsset, title: "公司范围新响应" }]));
      await company.promise;
    });
    expect(await screen.findByText("公司范围新响应")).toBeInTheDocument();

    await act(async () => {
      initial.resolve(response([{ ...restrictedAsset, title: "过期的全部范围响应" }]));
      await initial.promise;
    });
    expect(screen.getByText("公司范围新响应")).toBeInTheDocument();
    expect(screen.queryByText("过期的全部范围响应")).not.toBeInTheDocument();
  });

  it("uses server pagination and enforces previous and next boundaries", async () => {
    vi.mocked(fetchKnowledgePage).mockImplementation(async (params?: KnowledgeQueryParams) => {
      const current = params?.page ?? 1;
      return response([{ ...restrictedAsset, title: `第 ${current} 页资产` }], {
        total: 21,
        page: current,
        hasNext: current === 1,
      });
    });
    renderPage();

    expect(await screen.findByText("第 1 页资产")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("第 2 页资产")).toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
    expect(screen.getByText("显示 21-21 条，共 21 条")).toBeInTheDocument();
  });
});
