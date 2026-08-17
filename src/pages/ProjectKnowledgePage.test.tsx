import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { bulkDeleteKnowledgeAssets, fetchKnowledgePage } from "../api/knowledge";
import { fetchNamingOptions } from "../api/naming";
import { fetchProjectQaModelOptions, projectQa } from "../api/project";
import {
  preflightAssetization,
  previewCompanyUpgrade,
  registerAssetEvidence,
  requestCompanyUpgrade,
  submitAssetization,
} from "../api/review";
import type { KnowledgeCardVM, KnowledgePageVM } from "../types/knowledge";
import ProjectKnowledgePage from "./ProjectKnowledgePage";

const PROJECT_A = "00000000-0000-0000-0000-0000000000a1";
const PROJECT_B = "00000000-0000-0000-0000-0000000000b2";

const authState = {
  status: "authenticated",
  authMe: {
    userId: "user-1",
    name: "测试顾问",
    projects: [
      { projectId: PROJECT_A, projectName: "甲项目", projectRole: "consultant" },
      { projectId: PROJECT_B, projectName: "乙项目", projectRole: "project_manager" },
    ],
  },
};

vi.mock("../auth/AuthContext", () => ({ useAuth: () => authState }));
vi.mock("../api/knowledge", () => ({
  bulkDeleteKnowledgeAssets: vi.fn(),
  deleteKnowledgeAsset: vi.fn(),
  fetchKnowledgePage: vi.fn(),
}));
vi.mock("../api/project", () => ({
  fetchProjectQaModelOptions: vi.fn(),
  projectQa: vi.fn(),
}));
vi.mock("../api/naming", () => ({ fetchNamingOptions: vi.fn() }));
vi.mock("../api/review", () => ({
  preflightAssetization: vi.fn(),
  previewCompanyUpgrade: vi.fn(),
  registerAssetEvidence: vi.fn(),
  requestCompanyUpgrade: vi.fn(),
  submitAssetization: vi.fn(),
}));

function card(overrides: Partial<KnowledgeCardVM> = {}): KnowledgeCardVM {
  return {
    id: "asset-1",
    title: "客户访谈纪要",
    scope: "project",
    zone: "material",
    assetType: "case",
    confidentialityLevel: "L2",
    aiAccessLevel: "A2",
    assetStatus: "active",
    visibility: "project-only",
    tags: [],
    summary: "不应在紧凑列表展示的摘要",
    projectName: "甲项目",
    lifecyclePhase: "internal-phase",
    confidence: null,
    lastCalledAt: "",
    updatedAt: "2026-07-15",
    access: {
      discovery: true,
      summary: true,
      original: false,
      effectiveSource: "internal-access-source",
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
    ...overrides,
  };
}

function page(items: KnowledgeCardVM[] = [], overrides: Partial<KnowledgePageVM> = {}) {
  return { items, total: items.length, page: 1, pageSize: 20, hasNext: false, ...overrides };
}

function LocationProbe() {
  return <output aria-label="当前路径">{useLocation().pathname}</output>;
}

function AuthRefreshHarness() {
  const [, forceRender] = useState(0);
  return (
    <>
      <button
        onClick={() => {
          authState.authMe.projects = authState.authMe.projects.filter(
            (project) => project.projectId !== PROJECT_A,
          );
          forceRender((value) => value + 1);
        }}
      >
        模拟身份刷新移除当前项目
      </button>
      <ProjectKnowledgePage />
    </>
  );
}

function renderPage(path = `/project/${PROJECT_A}/knowledge`, withAuthRefresh = false) {
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      initialEntries={[path]}
    >
      <LocationProbe />
      <Routes>
        <Route
          path="/project/:id/knowledge"
          element={withAuthRefresh ? <AuthRefreshHarness /> : <ProjectKnowledgePage />}
        />
        <Route path="/knowledge/:id" element={<div>知识详情</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function expectDocumentOrder(firstSelector: string, secondSelector: string) {
  const first = document.querySelector(firstSelector);
  const second = document.querySelector(secondSelector);
  if (!first || !second) {
    throw new Error(`Missing ordered elements: ${firstSelector}, ${secondSelector}`);
  }
  expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
}

describe("ProjectKnowledgePage reference workspace", () => {
  beforeEach(() => {
    authState.status = "authenticated";
    authState.authMe.projects = [
      { projectId: PROJECT_A, projectName: "甲项目", projectRole: "consultant" },
      { projectId: PROJECT_B, projectName: "乙项目", projectRole: "project_manager" },
    ];
    vi.mocked(fetchKnowledgePage)
      .mockReset()
      .mockResolvedValue(page([card()]));
    vi.mocked(fetchProjectQaModelOptions)
      .mockReset()
      .mockResolvedValue({
        items: [
          { model_ref: "fallback-private-ref", display_name: "备用问答模型", is_default: false },
          { model_ref: "default-private-ref", display_name: "项目默认问答模型", is_default: true },
        ],
        total: 2,
      });
    vi.mocked(projectQa).mockReset().mockResolvedValue({
      call_id: "secret-call-id",
      trace_id: "secret-trace-id",
      model_key: "secret-model-key",
      decision_status: "internal-allowed",
      response_text: "访谈材料显示客户关注交付节奏。",
      citations: [],
      created_at: "2026-07-15T00:00:00Z",
    });
    vi.mocked(requestCompanyUpgrade)
      .mockReset()
      .mockResolvedValue({} as never);
    vi.mocked(fetchNamingOptions)
      .mockReset()
      .mockResolvedValue({
        required: true,
        rule_version: 7,
        categories: [
          {
            id: "category-company",
            scope: "company",
            primary: "公司资产",
            secondary: "方法论",
            prefix: "方法",
            asset_type: "methodology",
            default_confidentiality: "L2",
            suggested_directory_key: "company.methodology",
          },
        ],
        directories: [
          {
            directory_key: "company.methodology",
            scope: "company",
            display_name: "公司方法论",
            sort_order: 1,
            enabled: true,
          },
        ],
        default_confidentiality: "L2",
        message: null,
      });
    vi.mocked(previewCompanyUpgrade).mockReset().mockResolvedValue({
      required: true,
      canonical_name: "【公司资产-方法论】项目资产_全公司_20260817_V1_L2.docx",
      rule_version: 7,
      fields: {},
      notices: [],
      message: null,
    });
    vi.mocked(preflightAssetization)
      .mockReset()
      .mockImplementation(async (_projectId, ids) =>
        ids.map((id) => ({
          item_id: id,
          title: id,
          status: "ready",
          evidence_count: 1,
          reason_code: null,
          message: "已有可绑定证据",
        })),
      );
    vi.mocked(registerAssetEvidence).mockReset().mockResolvedValue();
    vi.mocked(submitAssetization).mockReset().mockResolvedValue({
      submitted: 1,
      created: 1,
      existing: 0,
      evidence_missing: 0,
      ineligible: 0,
      failed: 0,
      items: [],
    });
    vi.mocked(bulkDeleteKnowledgeAssets).mockReset().mockResolvedValue({
      operation_id: "bulk-delete",
      status: "completed",
      execution_mode: "synchronous",
      submitted: 2,
      succeeded: 2,
      skipped: 0,
      failed: 0,
      items: [],
    });
  });

  it("uses the exact project-scoped server page and a compact reference table", async () => {
    renderPage();

    expect(await screen.findByRole("table", { name: "项目知识列表" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "项目知识库" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回项目空间" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_A}`,
    );
    expect(screen.getByText("甲项目", { selector: ".product-page-heading p" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "知识名称" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "最后更新" })).toBeInTheDocument();
    expect(screen.getByText("资料区")).toBeInTheDocument();
    expect(screen.queryByText("不应在紧凑列表展示的摘要")).not.toBeInTheDocument();
    expect(screen.queryByText("internal-phase")).not.toBeInTheDocument();
    expect(screen.queryByText(/生命周期阶段|资产沉淀提醒|常用问题/)).not.toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenCalledWith({
      scope: "project",
      projectId: PROJECT_A,
      page: 1,
      pageSize: 20,
      sortBy: "updated_at",
      sortDirection: "desc",
      includeArchived: false,
    });
    expectDocumentOrder(".pk-filter-form", ".pk-list-section");
    expectDocumentOrder(".pk-pagination", ".pk-qa-section");
    expect(document.querySelectorAll(".pk-qa-section")).toHaveLength(1);
  });

  it("keeps project QA last, collapsed and lazy-loads models only after disclosure", async () => {
    renderPage();
    await screen.findByRole("table", { name: "项目知识列表" });

    const qaToggle = screen.getByRole("button", { name: /项目问答/ });
    expect(qaToggle).toHaveAttribute("aria-expanded", "false");
    expect(fetchProjectQaModelOptions).not.toHaveBeenCalled();
    expectDocumentOrder(".pk-list-section", ".pk-qa-section");

    fireEvent.click(qaToggle);
    await waitFor(() => expect(fetchProjectQaModelOptions).toHaveBeenCalledTimes(1));
    expect(qaToggle).toHaveAttribute("aria-expanded", "true");
  });

  it("sends real search, filter, date, sort and pagination parameters to the server", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(page([card()], { total: 41, hasNext: true }));
    renderPage();
    await screen.findByText("显示 1-20 条，共 41 条");

    fireEvent.change(screen.getByPlaceholderText("按标题或标签搜索"), {
      target: { value: "访谈" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "资料区域" }), {
      target: { value: "asset" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "资产类型" }), {
      target: { value: "case" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "资产状态" }), {
      target: { value: "active" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "保密级别" }), {
      target: { value: "L2" },
    });
    fireEvent.click(screen.getByText("更多筛选"));
    fireEvent.change(screen.getByLabelText("更新开始"), { target: { value: "2026-01-01" } });
    fireEvent.change(screen.getByLabelText("更新结束"), { target: { value: "2026-07-15" } });
    fireEvent.change(screen.getByRole("combobox", { name: "排序字段" }), {
      target: { value: "title" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "排序方向" }), {
      target: { value: "asc" },
    });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));

    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith(
        expect.objectContaining({
          scope: "project",
          projectId: PROJECT_A,
          keyword: "访谈",
          zone: "asset",
          assetType: "case",
          assetStatus: "active",
          confidentialityLevel: "L2",
          updatedFrom: "2026-01-01",
          updatedTo: "2026-07-15",
          sortBy: "title",
          sortDirection: "asc",
          page: 1,
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "资料区域" }), {
      target: { value: "material" },
    });
    await waitFor(() =>
      expect(fetchKnowledgePage).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 1, zone: "material" }),
      ),
    );
  });

  it("keeps company upgrade hidden from ordinary members", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(page([card({ zone: "asset" })]));
    renderPage();
    await screen.findByText("客户访谈纪要");

    expect(screen.queryByRole("button", { name: "申请升格公司资产" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/更多操作/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    expect(await screen.findByText("知识详情")).toBeInTheDocument();
  });

  it("localizes unknown list enums without echoing internal values", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      page([
        card({
          zone: "secret-zone",
          assetType: "secret-type",
          assetStatus: "secret-status" as KnowledgeCardVM["assetStatus"],
          confidentialityLevel: "secret-level" as KnowledgeCardVM["confidentialityLevel"],
        }),
      ]),
    );
    renderPage();

    expect((await screen.findAllByText("信息待确认")).length).toBe(4);
    const visibleText = document.body.textContent ?? "";
    expect(visibleText).not.toMatch(/secret-zone|secret-type|secret-status|secret-level/);
  });

  it("offers one low-interference upgrade action only for a manager's asset-zone row", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      page([
        card({ id: "material-1", title: "项目资料", zone: "material" }),
        card({ id: "asset-2", title: "项目资产", zone: "asset" }),
      ]),
    );
    renderPage(`/project/${PROJECT_B}/knowledge`);
    await screen.findByText("项目资产");

    expect(screen.getByLabelText("更多操作：项目资料")).toBeInTheDocument();
    const assetDetails = screen.getByLabelText("更多操作：项目资产").closest("details")!;
    fireEvent.click(screen.getByLabelText("更多操作：项目资产"));
    fireEvent.click(within(assetDetails).getByRole("button", { name: "申请升格公司资产" }));
    const dialog = await screen.findByRole("dialog", { name: "升格为公司资产" });
    expect(await within(dialog).findByText("公司方法论")).toBeInTheDocument();
    expect(within(dialog).queryByRole("combobox", { name: "正式目录" })).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("适用对象"), {
      target: { value: "全公司" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "预览目标文件名" }));
    await within(dialog).findByText(/【公司资产-方法论】/);
    fireEvent.click(within(dialog).getByRole("button", { name: "提交双角色确认" }));
    await waitFor(() =>
      expect(requestCompanyUpgrade).toHaveBeenCalledWith(
        PROJECT_B,
        "asset-2",
        expect.objectContaining({
          naming: expect.objectContaining({
            applicable_to: "全公司",
            directory_key: "company.methodology",
          }),
        }),
      ),
    );
    expect(await screen.findByText("公司资产升格申请已提交。")).toBeInTheDocument();
    expectDocumentOrder(".pk-upgrade-notice", ".pk-qa-section");
  });

  it("upgrades only active asset-zone selections while allowing all deletable project knowledge", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      page([
        card({
          id: "material-1",
          title: "项目资料",
          zone: "material",
          access: { ...card().access, canDelete: true },
        }),
        card({
          id: "asset-2",
          title: "有效项目资产",
          zone: "asset",
          assetStatus: "active",
          access: { ...card().access, canDelete: true },
        }),
        card({
          id: "asset-3",
          title: "待更新项目资产",
          zone: "asset",
          assetStatus: "needs_update",
          access: { ...card().access, canDelete: true },
        }),
      ]),
    );
    renderPage(`/project/${PROJECT_B}/knowledge`);
    await screen.findByText("有效项目资产");

    await act(async () => {
      fireEvent.click(screen.getByLabelText("全选当前页项目知识"));
    });
    expect(screen.getByRole("button", { name: "发起资产化审核（1）" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /批量升级为公司资产/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批量删除（3）" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "发起资产化审核（1）" }));
    await waitFor(() =>
      expect(preflightAssetization).toHaveBeenCalledWith(PROJECT_B, ["material-1"]),
    );
    expect(await screen.findByRole("dialog", { name: "发起资产化审核" })).toBeInTheDocument();
  });

  it("keeps assetization bulk-only while company publication remains item governed", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      page([
        card({
          id: "material-only",
          title: "纯资料区知识",
          zone: "material",
          access: { ...card().access, canDelete: true },
        }),
      ]),
    );
    const materialView = renderPage(`/project/${PROJECT_B}/knowledge`);
    await screen.findByText("纯资料区知识");
    await act(async () => {
      fireEvent.click(screen.getByLabelText("全选当前页项目知识"));
    });
    expect(screen.getByRole("button", { name: "发起资产化审核（1）" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /批量升级为公司资产/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批量删除（1）" })).toBeInTheDocument();
    materialView.unmount();

    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      page([
        card({
          id: "asset-only",
          title: "纯资产区知识",
          zone: "asset",
          access: { ...card().access, canDelete: true },
        }),
      ]),
    );
    renderPage(`/project/${PROJECT_B}/knowledge`);
    await screen.findByText("纯资产区知识");
    await act(async () => {
      fireEvent.click(screen.getByLabelText("全选当前页项目知识"));
    });
    expect(screen.queryByRole("button", { name: /批量升级为公司资产/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /发起资产化审核/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批量删除（1）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "申请升格公司资产" })).toBeInTheDocument();
  });

  it("opens an evidence preflight without silently creating review tasks", async () => {
    vi.mocked(fetchKnowledgePage).mockResolvedValue(
      page([
        card({ id: "material-ok", title: "成功资料", zone: "material" }),
        card({ id: "material-failed", title: "失败资料", zone: "material" }),
      ]),
    );
    vi.mocked(preflightAssetization).mockResolvedValue([
      {
        item_id: "material-ok",
        title: "成功资料",
        status: "ready",
        evidence_count: 1,
        reason_code: null,
        message: "已有可绑定证据",
      },
      {
        item_id: "material-failed",
        title: "失败资料",
        status: "evidence_missing",
        evidence_count: 0,
        reason_code: "assetization_evidence_required",
        message: "需先登记验证证据",
      },
    ]);
    renderPage(`/project/${PROJECT_B}/knowledge`);
    await screen.findByText("失败资料");

    await act(async () => {
      fireEvent.click(screen.getByLabelText("全选当前页项目知识"));
    });
    fireEvent.click(screen.getByRole("button", { name: "发起资产化审核（2）" }));
    expect(await screen.findByText("需先登记验证证据")).toBeInTheDocument();
    expect(submitAssetization).not.toHaveBeenCalled();
    expect(screen.getByLabelText("选择项目知识 失败资料")).toBeChecked();
    expect(screen.getByLabelText("选择项目知识 成功资料")).toBeChecked();
  });

  it("uses the default model and renders only safe QA fields", async () => {
    vi.mocked(projectQa).mockResolvedValue({
      call_id: "secret-call-id",
      trace_id: "secret-trace-id",
      model_key: "secret-model-key",
      decision_status: "internal-allowed",
      response_text: "访谈材料显示客户关注交付节奏。",
      citations: [
        {
          asset_id: "secret-asset-id",
          asset_title: "客户访谈纪要",
          scope: "project",
          cited_zone: "material",
          used_access_layer: "secret-access-layer",
          is_pending_review: true,
          is_asset_zone: false,
          citation_order: 1,
        },
      ],
      created_at: "2026-07-15T00:00:00Z",
    });
    renderPage();
    await screen.findByText("客户访谈纪要");
    fireEvent.click(screen.getByText("项目问答"));
    expect(await screen.findByRole("option", { name: "项目默认问答模型" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "问答模型" })).toHaveValue("1");
    fireEvent.change(screen.getByPlaceholderText("向当前项目知识提问…"), {
      target: { value: "项目风险是什么？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));

    expect(await screen.findByText("访谈材料显示客户关注交付节奏。")).toBeInTheDocument();
    expect(projectQa).toHaveBeenCalledWith(PROJECT_A, {
      query: "项目风险是什么？",
      modelRef: "default-private-ref",
    });
    expect(screen.getByText("内容待审核，请谨慎参考")).toBeInTheDocument();
    const visibleText = document.body.textContent ?? "";
    for (const secret of [
      "secret-call-id",
      "secret-trace-id",
      "secret-model-key",
      "internal-allowed",
      "secret-asset-id",
      "secret-access-layer",
      "default-private-ref",
    ]) {
      expect(visibleText).not.toContain(secret);
    }
  });

  it("keeps list, models, QA and upgrade failures generic and recoverable", async () => {
    vi.mocked(fetchKnowledgePage)
      .mockRejectedValueOnce(new Error("storage_ref=s3://secret"))
      .mockResolvedValueOnce(page([]));
    renderPage();
    expect(await screen.findByText("项目知识暂时无法加载，请稍后重试。")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("storage_ref");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("该项目暂无知识")).toBeInTheDocument();

    vi.mocked(fetchProjectQaModelOptions)
      .mockRejectedValueOnce(new Error("provider-secret"))
      .mockResolvedValueOnce({ items: [], total: 0 });
    fireEvent.click(screen.getByText("项目问答"));
    expect(await screen.findByText("问答模型暂时无法加载。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("当前项目暂无可用问答模型。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提问" })).toBeDisabled();
    expect(document.body.textContent).not.toContain("provider-secret");
  });

  it("clears old project data and ignores late list and QA responses after switching", async () => {
    const lateList = deferred<KnowledgePageVM>();
    const lateQa = deferred<Awaited<ReturnType<typeof projectQa>>>();
    vi.mocked(fetchKnowledgePage).mockImplementation((params) =>
      params?.projectId === PROJECT_A
        ? lateList.promise
        : Promise.resolve(page([card({ id: "b-asset", title: "乙项目知识" })])),
    );
    vi.mocked(projectQa).mockReturnValueOnce(lateQa.promise);
    renderPage();

    fireEvent.click(screen.getByText("项目问答"));
    await screen.findByRole("option", { name: "项目默认问答模型" });
    fireEvent.change(screen.getByPlaceholderText("向当前项目知识提问…"), {
      target: { value: "甲项目问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    fireEvent.change(screen.getByRole("combobox", { name: "切换项目" }), {
      target: { value: PROJECT_B },
    });

    expect(await screen.findByText("乙项目知识")).toBeInTheDocument();
    expect(screen.queryByText("甲项目问题")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("向当前项目知识提问…")).not.toBeInTheDocument();
    lateList.resolve(page([card({ title: "甲项目迟到知识" })]));
    lateQa.resolve({
      call_id: "late-call",
      trace_id: null,
      model_key: "late-model",
      decision_status: "allowed",
      response_text: "甲项目迟到回答",
      citations: [],
      created_at: "2026-07-15T00:00:00Z",
    });
    await Promise.resolve();
    expect(screen.queryByText("甲项目迟到知识")).not.toBeInTheDocument();
    expect(screen.queryByText("甲项目迟到回答")).not.toBeInTheDocument();
    expect(screen.getByLabelText("当前路径")).toHaveTextContent(`/project/${PROJECT_B}/knowledge`);
  });

  it("distinguishes no project, inaccessible project and filtered empty states safely", async () => {
    authState.authMe.projects = [];
    const noProject = renderPage();
    expect(await screen.findByText("暂无可访问项目")).toBeInTheDocument();
    expect(fetchKnowledgePage).not.toHaveBeenCalled();
    noProject.unmount();

    authState.authMe.projects = [
      { projectId: PROJECT_A, projectName: "甲项目", projectRole: "consultant" },
    ];
    const inaccessible = renderPage(`/project/${PROJECT_B}/knowledge`);
    expect(await screen.findByText("项目不可访问")).toBeInTheDocument();
    expect(screen.queryByText("乙项目")).not.toBeInTheDocument();
    inaccessible.unmount();

    vi.mocked(fetchKnowledgePage).mockResolvedValue(page([]));
    renderPage();
    await screen.findByText("该项目暂无知识");
    fireEvent.change(screen.getByPlaceholderText("按标题或标签搜索"), {
      target: { value: "不存在" },
    });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    expect(await screen.findByText("当前条件没有匹配内容")).toBeInTheDocument();
  });

  it("drops the stale project workspace immediately after refreshed auth removes membership", async () => {
    renderPage(`/project/${PROJECT_A}/knowledge`, true);
    expect(await screen.findByRole("table", { name: "项目知识列表" })).toBeInTheDocument();
    expect(screen.getByText("甲项目", { selector: ".product-page-heading p" })).toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "模拟身份刷新移除当前项目" }));

    expect(await screen.findByText("项目不可访问")).toBeInTheDocument();
    expect(screen.queryByText("甲项目")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "项目知识列表" })).not.toBeInTheDocument();
    expect(fetchKnowledgePage).toHaveBeenCalledTimes(1);
  });
});
