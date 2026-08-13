import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchKnowledgeDetail,
  fetchKnowledgeDirectories,
  fetchKnowledgePage,
  requestOriginalAccess,
  searchKnowledge,
} from "../api/knowledge";
import type {
  KnowledgeCardVM,
  KnowledgeDetailVM,
  KnowledgePageVM,
  KnowledgeQueryParams,
  KnowledgeDirectoryDTO,
} from "../types/knowledge";
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
  fetchKnowledgeDetail: vi.fn(),
  fetchKnowledgeDirectories: vi.fn(),
  fetchKnowledgePage: vi.fn(),
  requestOriginalAccess: vi.fn(),
  searchKnowledge: vi.fn(),
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
    canManageLifecycle: false,
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

const crossProjectAsset: KnowledgeCardVM = {
  ...restrictedAsset,
  id: "00000000-0000-0000-0000-0000000000a3",
  title: "其他项目客户访谈洞察",
  scope: "project",
  projectName: "北区增长项目",
  summary: "（脱敏）可跨项目共享的访谈摘要。",
  access: {
    ...restrictedAsset.access,
    effectiveSource: "system_rule",
    crossProjectSummary: true,
  },
  indexStatus: null,
};

const crossProjectDetail: KnowledgeDetailVM = {
  ...crossProjectAsset,
  projectId: null,
  maintainerName: "王顾问",
  categoryPath: "项目资料 / 项目复盘",
  safeVersion: "V3",
  retrievalAvailable: true,
  qaAvailable: false,
  archivedAt: null,
  archiveReason: null,
  oneLiner: "（脱敏）可跨项目共享的访谈摘要。",
  detailed: "（脱敏）仅包含可共享结论，不包含访谈原文。",
  keyPoints: [],
  currentVersionNo: null,
  indexErrorCode: null,
  canonicalMarkdownStatus: null,
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

const directories: KnowledgeDirectoryDTO[] = [
  {
    directory_key: "company.methodology",
    name: "01 公司方法论",
    description: "公司级方法资产",
    scope: "company",
    display_path: "公司库 / 01 公司方法论",
    parent_key: null,
    project_id: null,
    project_name: null,
  },
  {
    directory_key: "project.deliverables",
    name: "03 交付成果",
    description: "项目交付成果",
    scope: "project",
    display_path: "项目库 / 华东交付项目 / 03 交付成果",
    parent_key: null,
    project_id: PROJECT_A,
    project_name: "华东交付项目",
  },
  {
    directory_key: "project.deliverables",
    name: "03 交付成果",
    description: "项目交付成果",
    scope: "project",
    display_path: "项目库 / 供应链优化项目 / 03 交付成果",
    parent_key: null,
    project_id: PROJECT_B,
    project_name: "供应链优化项目",
  },
];

function renderPage(entry = "/knowledge?scope=company&directory_key=company.methodology") {
  return render(
    <MemoryRouter
      initialEntries={[entry]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <KnowledgeListPage />
    </MemoryRouter>,
  );
}

function LocationStateProbe() {
  const location = useLocation();
  return <output aria-label="detail navigation state">{JSON.stringify(location.state)}</output>;
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
    vi.mocked(fetchKnowledgeDirectories).mockResolvedValue(directories);
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue(crossProjectDetail);
    vi.mocked(requestOriginalAccess).mockResolvedValue({
      status: "created",
      message: "created",
      request: null,
      grant: null,
    });
    vi.mocked(searchKnowledge).mockResolvedValue({
      intent: "search",
      cards: [],
      answer: null,
      citations: [],
      original: null,
      trace_id: null,
    });
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
      scope: "company",
      directoryKey: "company.methodology",
    });
    expect(screen.getByRole("link", { name: "上传资产" })).toHaveAttribute("href", "/upload");
    expect(screen.queryByText(/运营洞察|新建项目知识库/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "在当前目录检索" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /删除|预览|下载/ })).not.toBeInTheDocument();
  });

  it("starts with folders and does not request a cross-directory asset page", async () => {
    renderPage("/knowledge");

    expect(await screen.findByRole("button", { name: /公司库/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /项目库/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /个人库/ })).toBeInTheDocument();
    expect(fetchKnowledgeDirectories).toHaveBeenCalled();
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
    expect(screen.queryByRole("table", { name: "知识资产列表" })).not.toBeInTheDocument();
  });

  it("only crosses directories after the user explicitly enters global search", async () => {
    renderPage("/knowledge");
    fireEvent.click(await screen.findByRole("button", { name: /全库搜索/ }));
    expect(screen.getByRole("heading", { name: "全库搜索" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("用自然语言描述要找的内容"), {
      target: { value: "跨目录方法" },
    });
    fireEvent.click(screen.getByRole("button", { name: "语义检索" }));
    await waitFor(() =>
      expect(searchKnowledge).toHaveBeenCalledWith({
        query: "跨目录方法",
        scope: "all",
        intent: "search",
        filters: {
          include_archived: false,
          directory_key: undefined,
          project_id: undefined,
        },
      }),
    );
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
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

    fireEvent.click(screen.getByRole("button", { name: "知识资产库" }));
    fireEvent.click(await screen.findByRole("button", { name: /项目库/ }));
    fireEvent.click(await screen.findByRole("button", { name: /供应链优化项目/ }));
    fireEvent.click(await screen.findByRole("button", { name: /03 交付成果/ }));
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
        directoryKey: "project.deliverables",
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
        scope: "project",
        projectId: PROJECT_B,
        directoryKey: "project.deliverables",
      }),
    );
    expect(screen.getByLabelText("关键词")).toHaveValue("");
    expect(screen.getByRole("navigation", { name: "知识资产目录路径" })).toHaveTextContent(
      "供应链优化项目",
    );
  });

  it("still loads cross-project summaries when the identity has no active project relationship", async () => {
    auth.authMe.projects = [];
    auth.capabilities.hasProject = false;
    renderPage("/knowledge");
    expect(await screen.findByRole("button", { name: /公司库/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /项目库/ })).not.toBeInTheDocument();
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
  });

  it("fails closed when a project directory URL names a project outside the current identity", async () => {
    auth.authMe.projects = [
      { projectId: PROJECT_A, projectName: "华东交付项目", projectRole: "consultant" },
    ];

    renderPage(
      `/knowledge?scope=project&project_id=${PROJECT_B}&directory_key=project.deliverables`,
    );

    expect(await screen.findByRole("button", { name: /公司库/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /项目库/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /个人库/ })).toBeInTheDocument();
    expect(fetchKnowledgeDirectories).toHaveBeenLastCalledWith({});
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
    expect(screen.queryByText("供应链优化项目")).not.toBeInTheDocument();
    expect(screen.queryByText("03 交付成果")).not.toBeInTheDocument();
  });

  it("returns a project directory URL without a project id to the knowledge root", async () => {
    renderPage("/knowledge?scope=project&directory_key=project.deliverables");

    expect(await screen.findByRole("button", { name: /公司库/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /项目库/ })).toBeInTheDocument();
    expect(screen.queryByText("03 交付成果")).not.toBeInTheDocument();
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
  });

  it.each([
    ["company", "personal.learning_notes"],
    ["personal", "company.methodology"],
    ["company", "project.deliverables"],
  ])(
    "returns a %s scope URL with a mismatched %s directory to the knowledge root",
    async (urlScope, directoryKey) => {
      renderPage(`/knowledge?scope=${urlScope}&directory_key=${directoryKey}`);

      await waitFor(() => expect(fetchKnowledgeDirectories).toHaveBeenLastCalledWith({}));
      await waitFor(() =>
        expect(screen.queryByText("正在读取可进入的目录…")).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("button", { name: /公司库/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /项目库/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /个人库/ })).toBeInTheDocument();
      expect(fetchKnowledgeDirectories).toHaveBeenLastCalledWith({});
      expect(fetchKnowledgePage).not.toHaveBeenCalled();
      expect(screen.queryByText("03 交付成果")).not.toBeInTheDocument();
    },
  );

  it.each([
    ["company", "company.retired"],
    ["personal", "personal.unknown"],
    ["project", "project.unknown"],
  ])(
    "returns a valid %s scope URL with missing directory %s to the knowledge root",
    async (urlScope, directoryKey) => {
      const projectContext = urlScope === "project" ? `&project_id=${PROJECT_A}` : "";
      renderPage(`/knowledge?scope=${urlScope}${projectContext}&directory_key=${directoryKey}`);

      await waitFor(() => expect(fetchKnowledgeDirectories).toHaveBeenLastCalledWith({}));
      await waitFor(() =>
        expect(screen.queryByText("正在读取可进入的目录…")).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("button", { name: /公司库/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /项目库/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /个人库/ })).toBeInTheDocument();
      expect(fetchKnowledgePage).not.toHaveBeenCalled();
      expect(screen.queryByText(directoryKey)).not.toBeInTheDocument();
    },
  );

  it("keeps the directory return context when an opened original leaves the summary drawer", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchKnowledgePage).mockResolvedValue(response([crossProjectAsset]));
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...crossProjectDetail,
      access: { ...crossProjectDetail.access, original: true },
    });
    render(
      <MemoryRouter
        initialEntries={["/knowledge?scope=company&directory_key=company.methodology"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/knowledge" element={<KnowledgeListPage />} />
          <Route path="/knowledge/:assetId" element={<LocationStateProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: `查看《${crossProjectAsset.title}》安全摘要`,
      }),
    );
    await user.click(await screen.findByRole("link", { name: "原文访问已开放，查看详情" }));

    expect(screen.getByLabelText("detail navigation state")).toHaveTextContent(
      '"backTo":"/knowledge?scope=company&directory_key=company.methodology"',
    );
    expect(screen.getByLabelText("detail navigation state")).toHaveTextContent(
      '"source":"directory"',
    );
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
    const titleLink = screen.getByRole("link", {
      name: `查看《${restrictedAsset.title}》详情`,
    });
    expect(titleLink).toHaveAttribute("href", `/knowledge/${restrictedAsset.id}`);
    titleLink.focus();
    expect(titleLink).toHaveFocus();
    expect(screen.queryByText(restrictedAsset.id)).not.toBeInTheDocument();
    expect(screen.queryByText(/storage_ref|WeKnora|token/i)).not.toBeInTheDocument();
  });

  it("opens a cross-project summary drawer and submits an honest original request", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchKnowledgePage).mockResolvedValue(response([crossProjectAsset]));
    vi.mocked(fetchKnowledgeDetail)
      .mockResolvedValueOnce(crossProjectDetail)
      .mockResolvedValueOnce({
        ...crossProjectDetail,
        access: {
          ...crossProjectDetail.access,
          canRequestOriginal: false,
          existingRequestStatus: "pending",
        },
      });
    renderPage();

    expect(await screen.findByText("其他项目 · 摘要可见")).toBeInTheDocument();
    const titleButton = screen.getByRole("button", {
      name: `查看《${crossProjectAsset.title}》安全摘要`,
    });
    titleButton.focus();
    expect(titleButton).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(
      await screen.findByRole("dialog", { name: crossProjectAsset.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(crossProjectDetail.detailed)).toBeInTheDocument();
    expect(screen.getByText(/不授予项目空间权限/)).toBeInTheDocument();
    expect(screen.getByText("王顾问")).toBeInTheDocument();
    expect(screen.getByText("项目资料 / 项目复盘")).toBeInTheDocument();
    expect(screen.getByText("问答不可用 · 检索可用")).toBeInTheDocument();
    expect(screen.queryByText(/Markdown|WeKnora|storage_ref/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "申请原文" }));
    expect(screen.getByRole("dialog", { name: "申请原文" })).toBeInTheDocument();
    expect(requestOriginalAccess).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "提交申请" }));
    await waitFor(() =>
      expect(requestOriginalAccess).toHaveBeenCalledWith(crossProjectAsset.id, undefined),
    );
    expect(await screen.findAllByText(/已提交原文访问申请/)).not.toHaveLength(0);
    expect(screen.getByRole("link", { name: "原文申请审批中" })).toHaveAttribute(
      "href",
      "/original-access?box=mine",
    );
  });

  it("cancels the request modal without side effects and keeps semantic empty distinct", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(response([restrictedAsset]));
    renderPage();
    await screen.findByText(restrictedAsset.title);

    fireEvent.click(screen.getByRole("button", { name: "为什么？" }));
    expect(await screen.findByRole("dialog", { name: "为什么是这个访问状态" })).toHaveTextContent(
      "原文需要逐项申请",
    );
    fireEvent.click(screen.getByRole("button", { name: "申请原文" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(requestOriginalAccess).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("用自然语言描述要找的内容"), {
      target: { value: "项目复盘方法" },
    });
    fireEvent.click(screen.getByRole("button", { name: "语义检索" }));
    await waitFor(() =>
      expect(searchKnowledge).toHaveBeenCalledWith({
        query: "项目复盘方法",
        scope: "company",
        intent: "search",
        filters: {
          include_archived: false,
          directory_key: "company.methodology",
          project_id: null,
        },
      }),
    );
    expect(await screen.findByText("当前检索没有匹配结果")).toBeInTheDocument();
    expect(screen.queryByText("当前条件没有匹配资料")).not.toBeInTheDocument();
  });

  it("shows a safe empty state when no cross-project summary is available", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      response([{ ...crossProjectAsset, summary: "" }]),
    );
    vi.mocked(fetchKnowledgeDetail).mockResolvedValue({
      ...crossProjectDetail,
      summary: "",
      oneLiner: "",
      detailed: "",
    });
    renderPage();

    expect(await screen.findByText("暂无可共享摘要")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: `查看《${crossProjectAsset.title}》安全摘要` }),
    );
    expect(await screen.findByText(/安全摘要尚未生成/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "申请原文" })).toBeInTheDocument();
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
    await screen.findByText("当前身份暂无可浏览资料");

    fireEvent.change(screen.getByLabelText("资产类型"), { target: { value: "template" } });
    expect(await screen.findByText("当前条件没有匹配资料")).toBeInTheDocument();
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
      scope: "company",
      directoryKey: "company.methodology",
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

    fireEvent.change(screen.getByLabelText("关键词"), { target: { value: "新响应" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
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
