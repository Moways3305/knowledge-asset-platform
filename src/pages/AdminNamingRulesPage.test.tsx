import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  confirmDirectoryMigration,
  fetchDirectoryMigration,
  fetchNamingRuleCenter,
  publishNamingRuleDraft,
  saveNamingRuleDraft,
} from "../api/naming";
import { ApiError } from "../api/http";
import type { NamingRuleCenterDTO, NamingRuleRevisionDTO } from "../types/naming";
import AdminNamingRulesPage from "./AdminNamingRulesPage";

vi.mock("../api/naming", () => ({
  confirmDirectoryMigration: vi.fn(),
  fetchDirectoryMigration: vi.fn(),
  fetchNamingRuleCenter: vi.fn(),
  publishNamingRuleDraft: vi.fn(),
  saveNamingRuleDraft: vi.fn(),
}));

const legacyCategory = {
  id: "10000000-0000-0000-0000-000000000001",
  scope: "company" as const,
  primary: "方法论",
  secondary: "模型工具",
  prefix: "方法论-模型工具",
  asset_type: "methodology" as const,
  default_confidentiality: "L2",
  enabled: true,
  sort_order: 20,
};

const center: NamingRuleCenterDTO = {
  published: {
    version: 1,
    status: "published",
    base_published_version: 0,
    config: { schema_version: 2, enforced: true, project_codes: [], categories: [] },
    updated_at: "2026-08-31T00:00:00Z",
    published_at: "2026-08-31T00:00:00Z",
  },
  draft: {
    version: 2,
    status: "draft",
    base_published_version: 1,
    config: {
      schema_version: 2,
      enforced: true,
      project_codes: [],
      categories: [legacyCategory],
      directories: [
        {
          directory_key: "company.methodology",
          scope: "company",
          display_name: "02 方法论",
          description: "模型与工具",
          naming_code: "方法论",
          default_confidentiality: "L2",
          enabled: true,
          sort_order: 20,
        },
        {
          directory_key: "project.deliverables",
          scope: "project",
          display_name: "03 交付成果",
          enabled: true,
          sort_order: 30,
        },
      ],
    },
    updated_at: "2026-08-31T00:00:00.123456Z",
    published_at: null,
  },
  projects: [],
};

describe("AdminNamingRulesPage directory governance", () => {
  it("adds a company third-level directory to draft with stable parent and inherited defaults", async () => {
    render(<AdminNamingRulesPage />);
    await screen.findByText("目录治理");
    fireEvent.click(screen.getByText("新建三级目录", { selector: "summary" }));
    fireEvent.change(screen.getByLabelText("所属分类"), {
      target: { value: "company.methodology" },
    });
    fireEvent.change(screen.getByLabelText("三级目录名称"), { target: { value: "战略模板" } });
    fireEvent.click(screen.getByRole("button", { name: "添加到草稿" }));
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));
    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    const saved = vi.mocked(saveNamingRuleDraft).mock.calls[0][1].directories ?? [];
    const child = saved[saved.length - 1];
    expect(child).toMatchObject({
      scope: "company",
      parent_key: "company.methodology",
      display_name: "战略模板",
      default_confidentiality: "L2",
    });
    expect(child?.directory_key).toMatch(/^company\.custom_[0-9a-f]{32}$/);
  });
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchNamingRuleCenter).mockResolvedValue(structuredClone(center));
    vi.mocked(saveNamingRuleDraft).mockImplementation(async (base, config) => ({
      ...structuredClone(center.draft),
      base_published_version: base,
      config,
      updated_at: "2026-08-31T00:00:01.123457Z",
    }));
    vi.mocked(publishNamingRuleDraft).mockResolvedValue(structuredClone(center));
  });

  it("saves the exact draft stamp, then publishes only the successfully saved draft", async () => {
    render(<AdminNamingRulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑02 方法论" }));
    const name = screen.getByDisplayValue("02 方法论");
    fireEvent.change(name, { target: { value: "02 核对后的方法论" } });
    expect(screen.getByRole("button", { name: /发布正式目录/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));
    await screen.findByText("目录草稿已保存；发布前不会影响新入库资料。");
    expect(saveNamingRuleDraft).toHaveBeenCalledWith(
      1,
      expect.any(Object),
      "2026-08-31T00:00:00.123456Z",
    );
    fireEvent.click(screen.getByRole("button", { name: /发布正式目录/ }));
    await waitFor(() =>
      expect(publishNamingRuleDraft).toHaveBeenCalledWith(1, "2026-08-31T00:00:01.123457Z"),
    );
  });

  it("keeps edits typed during a save and requires saving them with the returned stamp before publishing", async () => {
    let finishSave!: (value: NamingRuleRevisionDTO) => void;
    vi.mocked(saveNamingRuleDraft).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishSave = resolve;
        }),
    );
    render(<AdminNamingRulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑02 方法论" }));
    const name = screen.getByDisplayValue("02 方法论");
    fireEvent.change(name, { target: { value: "先提交的名称" } });
    const saveButton = screen.getByRole("button", { name: /保存草稿/ });
    act(() => {
      saveButton.click();
      saveButton.click();
    });
    expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1);
    fireEvent.change(name, { target: { value: "请求中继续编辑的名称" } });
    const config = vi.mocked(saveNamingRuleDraft).mock.calls[0][1];
    await act(async () =>
      finishSave({ ...center.draft, config, updated_at: "2026-08-31T00:00:02.123458Z" }),
    );
    expect(name).toHaveValue("请求中继续编辑的名称");
    expect(screen.getByText("已保存先前提交的草稿；当前页面还有未保存修改。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /发布正式目录/ })).toBeDisabled();
    fireEvent.click(saveButton);
    await screen.findByText("目录草稿已保存；发布前不会影响新入库资料。");
    expect(saveNamingRuleDraft).toHaveBeenLastCalledWith(
      1,
      expect.objectContaining({
        directories: expect.arrayContaining([
          expect.objectContaining({ display_name: "请求中继续编辑的名称" }),
        ]),
      }),
      "2026-08-31T00:00:02.123458Z",
    );
    expect(screen.getByRole("button", { name: /发布正式目录/ })).toBeEnabled();
  });

  it.each(["save", "publish"])(
    "preserves input after a %s conflict and reloads only on explicit action",
    async (action) => {
      const command = action === "save" ? saveNamingRuleDraft : publishNamingRuleDraft;
      vi.mocked(command).mockRejectedValueOnce(
        new ApiError(409, "目录草稿已更新，请重新加载后核对"),
      );
      render(<AdminNamingRulesPage />);
      fireEvent.click(await screen.findByRole("button", { name: "编辑02 方法论" }));
      const name = screen.getByDisplayValue("02 方法论");
      if (action === "save") fireEvent.change(name, { target: { value: "我的未保存输入" } });
      fireEvent.click(
        screen.getByRole("button", { name: action === "save" ? /保存草稿/ : /发布正式目录/ }),
      );
      await screen.findByText("目录草稿已更新，请重新加载后核对");
      expect(name).toHaveValue(action === "save" ? "我的未保存输入" : "02 方法论");
      expect(fetchNamingRuleCenter).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: /保存草稿/ })).toBeDisabled();
      expect(screen.getByRole("button", { name: /发布正式目录/ })).toBeDisabled();
      let finishReload!: (value: NamingRuleCenterDTO) => void;
      vi.mocked(fetchNamingRuleCenter).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishReload = resolve;
          }),
      );
      fireEvent.click(screen.getByRole("button", { name: "重新加载目录" }));
      expect(name).toBeDisabled();
      expect(screen.getByRole("button", { name: "重新加载目录" })).toBeDisabled();
      const latest = structuredClone(center);
      latest.draft.updated_at = "2026-08-31T00:00:03.123459Z";
      latest.draft.config.directories![0].display_name = "其他治理者保存的名称";
      await act(async () => finishReload(latest));
      expect(name).toHaveValue("其他治理者保存的名称");
      expect(screen.queryByRole("button", { name: "重新加载目录" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /发布正式目录/ }));
      await waitFor(() =>
        expect(publishNamingRuleDraft).toHaveBeenLastCalledWith(1, latest.draft.updated_at),
      );
    },
  );

  it("blocks editing and duplicate requests while publishing the reviewed draft", async () => {
    let finishPublish!: (value: NamingRuleCenterDTO) => void;
    vi.mocked(publishNamingRuleDraft).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishPublish = resolve;
        }),
    );
    render(<AdminNamingRulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑02 方法论" }));
    const name = screen.getByDisplayValue("02 方法论");
    const publishButton = screen.getByRole("button", { name: /发布正式目录/ });
    act(() => {
      publishButton.click();
      publishButton.click();
    });
    expect(publishNamingRuleDraft).toHaveBeenCalledTimes(1);
    expect(publishNamingRuleDraft).toHaveBeenCalledWith(1, center.draft.updated_at);
    expect(name).toBeDisabled();
    expect(screen.getByRole("button", { name: /保存草稿/ })).toBeDisabled();
    await act(async () => finishPublish(structuredClone(center)));
    expect(name).toBeEnabled();
  });

  it("shows formal directories without category or project-code management", async () => {
    render(<AdminNamingRulesPage />);
    expect(await screen.findByText("目录治理")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑02 方法论" })).toBeInTheDocument();
    expect(screen.queryByLabelText("目录名称")).not.toBeInTheDocument();
    expect(screen.queryByText("目录类别")).not.toBeInTheDocument();
    expect(screen.queryByText("项目代码")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "项目目录" }));
    expect(screen.getByRole("button", { name: "编辑03 交付成果" })).toBeInTheDocument();
  });

  it("round-trips historical categories unchanged while saving directory edits", async () => {
    render(<AdminNamingRulesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑02 方法论" }));
    const name = screen.getByDisplayValue("02 方法论");
    fireEvent.change(name, { target: { value: "02 方法与工具" } });
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));

    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    const config = vi.mocked(saveNamingRuleDraft).mock.calls[0][1];
    expect(config.categories).toEqual([legacyCategory]);
    expect(config.directories?.[0].display_name).toBe("02 方法与工具");
  });

  it("reports the auditable pending-governance counts", async () => {
    vi.mocked(fetchDirectoryMigration).mockResolvedValue({
      overview: {
        total: 3,
        migrated: 1,
        clear_match: 1,
        manual_required: 1,
        no_candidate: 1,
        failed: 0,
        rule_version: 1,
      },
      items: [],
      total: 0,
      directories: [],
    });
    render(<AdminNamingRulesPage />);
    await screen.findByText("目录治理");
    fireEvent.click(screen.getByRole("button", { name: /历史待治理/ }));
    expect(fetchDirectoryMigration).toHaveBeenCalledWith({ status: "pending", page: 1 });
    expect(
      await screen.findByText(/资产总计 3 · 已归类 1 · 待治理 0 · 待人工 1 · 无明确候选 1/),
    ).toBeInTheDocument();
  });
  it("loads subsequent pending pages", async () => {
    vi.mocked(fetchDirectoryMigration).mockResolvedValue({
      overview: {
        total: 100,
        migrated: 49,
        clear_match: 51,
        manual_required: 0,
        no_candidate: 0,
        failed: 0,
        rule_version: 1,
      },
      items: [],
      total: 51,
      directories: [],
    });
    render(<AdminNamingRulesPage />);
    await screen.findByText("目录治理");
    fireEvent.click(screen.getByRole("button", { name: /历史待治理/ }));
    await screen.findByText(/第 1 \/ 2 页/);
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText(/第 2 \/ 2 页/);
    expect(fetchDirectoryMigration).toHaveBeenLastCalledWith({ status: "pending", page: 2 });
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });
  it("selects only clear candidates, clears selection, and submits without overriding confidence", async () => {
    const item = (id: string, confidence: string, status: string, key: string | null) => ({
      id,
      asset_title: id,
      scope: "project",
      project_id: null,
      project_name: null,
      old_category: null,
      suggested_directory_key: key,
      suggested_directory_name: key,
      candidate_source: "legacy",
      confidence,
      status,
      failure_code: null,
      updated_at: null,
    });
    vi.mocked(fetchDirectoryMigration).mockResolvedValue({
      overview: {
        total: 51,
        migrated: 1,
        clear_match: 1,
        manual_required: 1,
        no_candidate: 1,
        failed: 0,
        rule_version: 1,
      },
      items: [
        item("clear", "clear", "clear_match", "project.deliverables"),
        item("low", "low", "manual_required", "project.deliverables"),
        item("missing", "none", "no_candidate", null),
        item("done", "clear", "migrated", "project.deliverables"),
      ],
      total: 51,
      directories: [],
    });
    vi.mocked(confirmDirectoryMigration).mockResolvedValue({
      submitted: 1,
      migrated: 1,
      skipped: 0,
      failed: 0,
    });
    render(<AdminNamingRulesPage />);
    await screen.findByText("目录治理");
    fireEvent.click(screen.getByRole("button", { name: /历史待治理/ }));
    const clear = await screen.findByRole("checkbox", { name: /^clear/ });
    for (const name of [/^low/, /^missing/, /^done/]) {
      expect(screen.getByRole("checkbox", { name })).toBeDisabled();
    }
    fireEvent.click(screen.getByRole("button", { name: "全选本页可迁移项" }));
    expect(clear).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^low/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "确认迁移 1 项" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "取消全选" }));
    expect(clear).not.toBeChecked();
    expect(screen.getByRole("button", { name: "确认迁移 0 项" })).toBeDisabled();
    fireEvent.click(clear);
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText(/第 2 \/ 2 页/);
    expect(clear).not.toBeChecked();
    expect(screen.getByRole("button", { name: "确认迁移 0 项" })).toBeDisabled();
    fireEvent.click(clear);
    fireEvent.click(screen.getByRole("button", { name: "确认迁移 1 项" }));
    await waitFor(() =>
      expect(confirmDirectoryMigration).toHaveBeenCalledWith([{ candidate_id: "clear" }]),
    );
    await screen.findByText(/迁移成功 1 项/);
  });
});
