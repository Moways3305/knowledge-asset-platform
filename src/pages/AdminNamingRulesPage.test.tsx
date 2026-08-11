import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchNamingRuleCenter, publishNamingRuleDraft, saveNamingRuleDraft } from "../api/naming";
import type { NamingRuleCenterDTO } from "../types/naming";
import AdminNamingRulesPage from "./AdminNamingRulesPage";

vi.mock("../api/naming", () => ({
  fetchNamingRuleCenter: vi.fn(),
  publishNamingRuleDraft: vi.fn(),
  saveNamingRuleDraft: vi.fn(),
}));

const alphaId = "20000000-0000-0000-0000-000000000001";
const betaId = "20000000-0000-0000-0000-000000000002";
const center: NamingRuleCenterDTO = {
  published: {
    version: 1,
    status: "published",
    base_published_version: 0,
    config: { schema_version: 1, enforced: false, project_codes: [], categories: [] },
    updated_at: "2026-08-02T00:00:00Z",
    published_at: "2026-08-02T00:00:00Z",
  },
  draft: {
    version: 2,
    status: "draft",
    base_published_version: 1,
    config: {
      schema_version: 1,
      enforced: false,
      project_codes: [
        { project_id: alphaId, code: "ALPHA-26", enabled: true, default_confidentiality: "L2" },
        { project_id: betaId, code: "BETA-26", enabled: true, default_confidentiality: "L3" },
      ],
      categories: [
        {
          id: "10000000-0000-0000-0000-000000000001",
          scope: "project",
          primary: "项目资料",
          secondary: "交付件",
          prefix: "交付件",
          asset_type: "deliverable",
          default_confidentiality: "L2",
          enabled: true,
          sort_order: 10,
        },
        {
          id: "10000000-0000-0000-0000-000000000002",
          scope: "company",
          primary: "方法论",
          secondary: "模型工具",
          prefix: "方法论-模型工具",
          asset_type: "methodology",
          default_confidentiality: "L2",
          enabled: true,
          sort_order: 20,
        },
      ],
    },
    updated_at: "2026-08-02T00:00:00Z",
    published_at: null,
  },
  projects: [
    {
      id: alphaId,
      name: "Alpha咨询",
      status: "active",
      project_code: "ALPHA-26",
      project_code_active: true,
      default_confidentiality: "L2",
    },
    {
      id: betaId,
      name: "Beta转型",
      status: "active",
      project_code: "BETA-26",
      project_code_active: true,
      default_confidentiality: "L3",
    },
  ],
};

function chooseUnifiedProjectScope() {
  fireEvent.click(screen.getByRole("button", { name: "全项目通用规范" }));
}

describe("AdminNamingRulesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchNamingRuleCenter).mockResolvedValue(structuredClone(center));
    vi.mocked(saveNamingRuleDraft).mockImplementation(async (base, config) => ({
      ...structuredClone(center.draft),
      base_published_version: base,
      config,
    }));
    vi.mocked(publishNamingRuleDraft).mockResolvedValue({
      ...structuredClone(center),
      published: { ...structuredClone(center.draft), status: "published" },
    });
  });

  it("keeps category rows in the current-scope modal", async () => {
    render(<AdminNamingRulesPage />);
    expect(await screen.findByText("公司级类别不会出现在项目资料中")).toBeInTheDocument();
    expect(screen.queryByText("方法论 / 模型工具")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "管理目录类别" }));
    expect(screen.getByRole("dialog", { name: "管理目录类别" })).toHaveTextContent(
      "方法论 / 模型工具",
    );
  });

  it("manages one project category set without selecting a project", async () => {
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");
    chooseUnifiedProjectScope();
    expect(screen.getByText("一次维护，所有项目使用同一类别集合")).toBeInTheDocument();
    expect(screen.queryByLabelText("管理项目")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "管理目录类别" }));
    expect(screen.getByText("交付件")).toBeInTheDocument();
    expect(screen.queryByText("方法论 / 模型工具")).not.toBeInTheDocument();
  });

  it("writes a new category once without exposing project ownership", async () => {
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");
    chooseUnifiedProjectScope();
    fireEvent.click(screen.getByRole("button", { name: "管理目录类别" }));
    fireEvent.click(screen.getByRole("button", { name: "新增类别" }));
    const editor = screen.getByRole("dialog", { name: "新增目录类别" });
    expect(editor).toHaveTextContent("全项目通用规范");
    expect(editor).not.toHaveTextContent(alphaId);
    fireEvent.change(within(editor).getByLabelText("类别名称"), { target: { value: "访谈纪要" } });
    fireEvent.change(within(editor).getByLabelText("资产分类"), {
      target: { value: "insight" },
    });
    fireEvent.click(within(editor).getByRole("button", { name: "写入草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalled());
    expect(vi.mocked(saveNamingRuleDraft).mock.calls[0][1].categories).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          scope: "project",
          secondary: "访谈纪要",
          asset_type: "insight",
        }),
      ]),
    );
    expect(vi.mocked(saveNamingRuleDraft).mock.calls[0][1].categories[0]).not.toHaveProperty(
      "project_id",
    );
  });

  it("keeps project codes in a separate project-facts modal", async () => {
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");
    chooseUnifiedProjectScope();
    fireEvent.click(screen.getByRole("button", { name: "管理项目代码" }));
    const modal = screen.getByRole("dialog", { name: "管理项目代码" });
    expect(modal).toHaveTextContent("目录类别仍由全项目通用规范统一提供");
    expect(within(modal).getByDisplayValue("ALPHA-26")).toBeInTheDocument();
    expect(within(modal).getByDisplayValue("BETA-26")).toBeInTheDocument();
  });

  it("opens scoped details and confirms destructive deletion", async () => {
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");
    chooseUnifiedProjectScope();
    fireEvent.click(screen.getByRole("button", { name: "管理目录类别" }));
    fireEvent.click(screen.getByRole("button", { name: /交付件/ }));
    const drawer = screen.getByRole("dialog", { name: "交付件" });
    expect(drawer).toHaveTextContent("全项目通用规范");
    fireEvent.click(within(drawer).getByRole("button", { name: "删除" }));
    const confirmation = screen.getByRole("dialog", { name: /删除「交付件」/ });
    expect(confirmation).toHaveTextContent("无法从当前草稿恢复");
    fireEvent.click(within(confirmation).getByRole("button", { name: "删除类别" }));
    expect(screen.getByRole("status")).toHaveTextContent("全项目通用规范");
  });

  it("initialization distinguishes local draft from save and publish", async () => {
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");
    chooseUnifiedProjectScope();
    fireEvent.click(screen.getByRole("button", { name: "初始化标准目录" }));
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(screen.getByRole("dialog", { name: "初始化标准目录" })).toHaveTextContent(
      "受理不等于发布",
    );
    fireEvent.click(screen.getByRole("button", { name: "加入本地草稿" }));
    expect(screen.getByRole("status")).toHaveTextContent("尚未保存或发布");
    expect(saveNamingRuleDraft).not.toHaveBeenCalled();
    expect(publishNamingRuleDraft).not.toHaveBeenCalled();
  });

  it("reports retryable save failure without clearing the scope", async () => {
    vi.mocked(saveNamingRuleDraft).mockRejectedValueOnce(new Error("offline"));
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");
    chooseUnifiedProjectScope();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("草稿保存失败");
    expect(screen.getByText("全项目通用规范", { selector: "#scope-heading" })).toBeInTheDocument();
  });

  it("blocks publication and identifies an enabled category without an asset classification", async () => {
    const incomplete = structuredClone(center);
    incomplete.draft!.config.categories[0].asset_type = null;
    vi.mocked(fetchNamingRuleCenter).mockResolvedValueOnce(incomplete);
    render(<AdminNamingRulesPage />);
    await screen.findByText("命名规则中心");

    fireEvent.click(screen.getByRole("button", { name: "发布规则" }));

    expect(screen.getByRole("alert")).toHaveTextContent("交付件");
    expect(screen.getByRole("alert")).toHaveTextContent("尚未配置资产分类");
    expect(publishNamingRuleDraft).not.toHaveBeenCalled();
  });
});
