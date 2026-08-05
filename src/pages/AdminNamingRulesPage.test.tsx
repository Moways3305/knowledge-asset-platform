import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchNamingRuleCenter, publishNamingRuleDraft, saveNamingRuleDraft } from "../api/naming";
import type { NamingRuleCenterDTO } from "../types/naming";
import AdminNamingRulesPage from "./AdminNamingRulesPage";

vi.mock("../api/naming", () => ({
  fetchNamingRuleCenter: vi.fn(),
  publishNamingRuleDraft: vi.fn(),
  saveNamingRuleDraft: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

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
      project_codes: [],
      categories: [
        {
          id: "10000000-0000-0000-0000-000000000001",
          scope: "project",
          primary: "项目资料",
          secondary: "交付件",
          prefix: "项目资料-交付件",
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
      id: "20000000-0000-0000-0000-000000000001",
      name: "示例项目",
      status: "active",
      project_code: null,
      project_code_active: false,
      default_confidentiality: "L2",
    },
  ],
};

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

  it("keeps edits in the draft until an explicit publish", async () => {
    render(<AdminNamingRulesPage />);

    const code = await screen.findByPlaceholderText("如 BW-2601");
    fireEvent.change(code, { target: { value: "bw-2601" } });
    fireEvent.change(screen.getByLabelText("客户命名别名（顿号分隔）"), {
      target: { value: "琥崧、琥崧智能" },
    });
    fireEvent.click(screen.getAllByLabelText("启用")[0]);
    fireEvent.click(screen.getByLabelText(/发布后强制/));
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    expect(saveNamingRuleDraft).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        enforced: true,
        project_codes: [
          expect.objectContaining({
            code: "BW-2601",
            enabled: true,
            client_aliases: ["琥崧", "琥崧智能"],
            client_aliases_enabled: true,
          }),
        ],
        categories: expect.arrayContaining([
          expect.objectContaining({
            scope: "project",
            primary: "项目资料",
            secondary: "交付件",
            prefix: "交付件",
          }),
          expect.objectContaining({
            scope: "company",
            primary: "方法论",
            secondary: "模型工具",
            prefix: "方法论-模型工具",
          }),
        ]),
      }),
    );
    expect(publishNamingRuleDraft).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /发布规则/ }));
    await waitFor(() => expect(publishNamingRuleDraft).toHaveBeenCalledWith(1));
  });

  it("shows the project canonical-name shape without customer names", async () => {
    render(<AdminNamingRulesPage />);
    expect(await screen.findByText(/【PRJ-2026-交付件】/)).toBeInTheDocument();
  });

  it("exposes the typed field help through pointer hover and keyboard focus", async () => {
    render(<AdminNamingRulesPage />);
    const trigger = await screen.findByRole("button", { name: "查看目录类别填写说明" });

    fireEvent.mouseEnter(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("项目基础信息 | L4 | 10 | 启用");
    expect(screen.getByRole("tooltip")).toHaveTextContent("方法论 | 模型工具 | L2 | 10 | 启用");
    expect(screen.getByRole("tooltip")).toHaveTextContent("排序数值越小越靠前");
    fireEvent.mouseLeave(trigger.parentElement!);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.focus(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("文件形成日期年份和二级分类");
    fireEvent.blur(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows only the fields belonging to each category scope", async () => {
    render(<AdminNamingRulesPage />);
    const project = await screen.findByRole("group", { name: /项目库目录类别 交付件/ });
    expect(within(project).getByLabelText("类别名称")).toBeInTheDocument();
    expect(within(project).queryByLabelText("一级分类")).not.toBeInTheDocument();
    expect(within(project).queryByLabelText("二级分类")).not.toBeInTheDocument();
    expect(within(project).queryByLabelText("规范前缀")).not.toBeInTheDocument();

    const company = screen.getByRole("group", { name: /公司库目录类别 模型工具/ });
    expect(within(company).getByLabelText("一级分类")).toHaveValue("方法论");
    expect(within(company).getByLabelText("二级分类")).toHaveValue("模型工具");
    expect(within(company).queryByLabelText("规范前缀")).not.toBeInTheDocument();
  });

  it("safely derives compatibility fields when switching category scope", async () => {
    render(<AdminNamingRulesPage />);
    const project = await screen.findByRole("group", { name: /项目库目录类别 交付件/ });
    fireEvent.change(within(project).getByLabelText("适用库范围"), {
      target: { value: "company" },
    });

    const converted = screen.getByRole("group", { name: /公司库目录类别 交付件/ });
    expect(within(converted).getByLabelText("一级分类")).toHaveValue("方法论");
    expect(within(converted).getByLabelText("二级分类")).toHaveValue("交付件");

    fireEvent.change(within(converted).getByLabelText("适用库范围"), {
      target: { value: "project" },
    });
    const restored = screen.getByRole("group", { name: /项目库目录类别 交付件/ });
    expect(within(restored).queryByLabelText("一级分类")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveNamingRuleDraft).mock.calls[0][1].categories[0]).toMatchObject({
      scope: "project",
      primary: "项目资料",
      secondary: "交付件",
      prefix: "交付件",
    });
  });

  it("initializes only missing project standards in the current draft", async () => {
    render(<AdminNamingRulesPage />);
    const initialize = await screen.findByRole("button", {
      name: /一键初始化项目库标准目录/,
    });
    fireEvent.click(initialize);
    expect(screen.getByRole("status")).toHaveTextContent("已新增 5 个项目库标准类别");

    fireEvent.click(initialize);
    expect(screen.getByRole("status")).toHaveTextContent("5 个标准类别均已存在");
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    const saved = vi.mocked(saveNamingRuleDraft).mock.calls[0][1];
    for (const name of ["项目基础信息", "辅导过程", "交付成果", "关键资料", "项目复盘"]) {
      expect(
        saved.categories.filter((item) => item.scope === "project" && item.secondary === name),
      ).toHaveLength(1);
    }
    expect(publishNamingRuleDraft).not.toHaveBeenCalled();
  });

  it("cancels or confirms draft deletion and saves the reduced category set", async () => {
    render(<AdminNamingRulesPage />);
    const remove = await screen.findByRole("button", { name: "删除目录类别 交付件" });

    fireEvent.click(remove);
    expect(screen.getByRole("dialog")).toHaveTextContent("确认从草稿中删除「交付件」？");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.getByRole("button", { name: "删除目录类别 交付件" })).toBeInTheDocument();

    fireEvent.click(remove);
    fireEvent.click(screen.getByRole("button", { name: "删除类别" }));
    expect(screen.queryByRole("button", { name: "删除目录类别 交付件" })).not.toBeInTheDocument();
    expect(screen.getByText("先新增并启用一个目录类别")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveNamingRuleDraft).mock.calls[0][1].categories).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "10000000-0000-0000-0000-000000000001" }),
      ]),
    );
    expect(publishNamingRuleDraft).not.toHaveBeenCalled();
  });

  it("keeps edits made while an older save request is still in flight", async () => {
    const pending = deferred<NamingRuleCenterDTO["draft"]>();
    vi.mocked(saveNamingRuleDraft).mockReturnValueOnce(pending.promise);
    render(<AdminNamingRulesPage />);
    const categoryName = await screen.findByLabelText("类别名称");

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    const submittedConfig = vi.mocked(saveNamingRuleDraft).mock.calls[0][1];
    fireEvent.change(categoryName, { target: { value: "保存期间新增编辑" } });

    await act(async () => {
      pending.resolve({ ...structuredClone(center.draft), config: submittedConfig });
      await pending.promise;
    });

    expect(screen.getByLabelText("类别名称")).toHaveValue("保存期间新增编辑");
    expect(screen.getByRole("status")).toHaveTextContent("后续编辑尚未保存");
    await waitFor(() => expect(screen.getByRole("button", { name: "保存草稿" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(2));
    expect(vi.mocked(saveNamingRuleDraft).mock.calls[1][1].categories[0].secondary).toBe(
      "保存期间新增编辑",
    );
  });
});
