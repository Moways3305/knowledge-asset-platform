import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/http";
import type { PendingIngestItemDTO } from "../../types/ingest";
import PendingBatchActions from "./PendingBatchActions";
import type { UploadFlow } from "./useUploadFlow";

const namingApi = vi.hoisted(() => ({
  classifyBatchNamingCategories: vi.fn(),
  fetchNamingOptions: vi.fn(),
  previewIngestNaming: vi.fn(),
  previewBatchIngestNaming: vi.fn(),
  saveManualNamingCategory: vi.fn(),
}));
const ingestApi = vi.hoisted(() => ({
  decideUploadDuplicate: vi.fn(),
  fetchIngestAiResult: vi.fn(),
  retryIngestTask: vi.fn(),
}));
vi.mock("../../api/naming", () => namingApi);
vi.mock("../../api/ingest", () => ingestApi);

const noDuplicate = {
  duplicate_state: "none",
  match_type: null,
  match_count: 0,
  preferred_candidate: null,
  same_batch_group_id: null,
  same_batch_first_ordinal: null,
  default_selected: true,
  decision: null,
};

function task(id: string, overrides: Partial<PendingIngestItemDTO> = {}): PendingIngestItemDTO {
  return {
    id,
    source: "path_b_upload",
    status: "pending_confirmation",
    source_file_name: `${id}.pdf`,
    target_scope: null,
    target_project_id: null,
    can_batch_confirm: true,
    can_batch_reject: true,
    extraction_status: "extracted",
    error_type: null,
    error_message: null,
    suggested_title: `${id}主题`,
    suggested_one_liner: null,
    suggested_version: "V1",
    version_source: "ai_content",
    version_confidence: "medium",
    version_reason: "AI 根据正文与可用元数据建议版本",
    suggested_confidentiality_level: "L3",
    confidentiality_source: "ai_content",
    confidentiality_confidence: "medium",
    confidentiality_reason: "AI 根据正文内容特征建议为 L3",
    naming_parsed_fields: {
      primary_category: "项目资料",
      secondary_category: "交付成果",
      topic: `${id}主题`,
      subject_or_client: "华东区",
      date: "20260803",
      version: "V1",
      confidentiality_level: "L2",
      ai_access_level: "A2",
      normalized_title: "",
      inferred_fields: [],
      missing_fields: [],
      source_file_name: `${id}.pdf`,
      original_naming_compliant: false,
    },
    confidence: 0.9,
    suggestion_generation_status: "generated",
    suggestion_generation_reason: "建议已生成",
    result_asset_id: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function flowFixture(
  tasks: PendingIngestItemDTO[],
  overrides: Record<string, unknown> = {},
): UploadFlow {
  return {
    batchSelection: tasks.map((item) => item.id),
    batchStatus: {},
    batchBusy: false,
    batchOperation: null,
    batchErrors: {},
    batchRejectRetryability: {},
    handleBatchConfirm: vi.fn(),
    handleBatchReject: vi.fn(),
    handleDeleteBatchReviewItem: vi.fn().mockResolvedValue({ ok: true }),
    projects: [{ projectId: "project-a", projectName: "项目 A" }],
    canUseCompanyTarget: true,
    ...overrides,
  } as unknown as UploadFlow;
}

async function openProjectReview() {
  fireEvent.click(screen.getByRole("button", { name: /批量确认入库/ }));
  fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
    target: { value: "project" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
    target: { value: "project-a" },
  });
  fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));
  await screen.findByLabelText("核对状态筛选");
}

function topDialog(): HTMLElement {
  const dialogs = screen.getAllByRole("dialog");
  return dialogs[dialogs.length - 1];
}

describe("PendingBatchActions governed review", () => {
  beforeEach(() => {
    ingestApi.decideUploadDuplicate.mockReset();
    namingApi.previewIngestNaming.mockReset().mockResolvedValue({
      required: false,
      canonical_name: null,
      rule_version: null,
      fields: null,
      notices: [],
      message: "个人资料不强制规范命名",
      duplicate: noDuplicate,
    });
    namingApi.fetchNamingOptions.mockReset().mockResolvedValue({
      required: true,
      rule_version: 3,
      categories: [
        {
          id: "deliverable",
          primary: "项目资料",
          secondary: "交付成果",
          prefix: "项目资料-交付成果",
          asset_type: "deliverable",
          default_confidentiality: "L2",
        },
        {
          id: "method",
          primary: "项目资料",
          secondary: "工作方法",
          prefix: "项目资料-工作方法",
          asset_type: "methodology",
          default_confidentiality: "L2",
        },
      ],
      directories: [
        {
          directory_key: "personal.learning_notes",
          scope: "personal",
          display_name: "01 个人学习笔记",
          sort_order: 10,
          enabled: true,
        },
        {
          directory_key: "personal.project_materials",
          scope: "personal",
          display_name: "02 个人项目资料",
          sort_order: 20,
          enabled: true,
        },
        {
          directory_key: "personal.pending",
          scope: "personal",
          display_name: "04 待处理",
          sort_order: 40,
          enabled: true,
        },
        {
          directory_key: "project.deliverables",
          scope: "project",
          display_name: "03 项目交付成果",
          sort_order: 30,
          enabled: true,
        },
        {
          directory_key: "company.methodology",
          scope: "company",
          display_name: "03 公司方法论",
          sort_order: 30,
          enabled: true,
        },
      ],
      default_confidentiality: "L2",
      message: null,
    });
    namingApi.previewBatchIngestNaming.mockReset();
    ingestApi.fetchIngestAiResult.mockReset().mockResolvedValue({
      ingest_task_id: "safe-task",
      status: "ready",
      suggested_title: "AI 标题",
      suggested_one_liner: "AI 一句话摘要",
      suggested_summary: "AI 详细摘要",
      summary: "AI 详细摘要",
      suggested_key_points: ["关键点一"],
      suggested_tags: ["标签一"],
      suggestion_generation_status: "generated",
      suggestion_generation_reason: "已生成",
    });
    ingestApi.retryIngestTask.mockReset().mockResolvedValue({});
    namingApi.saveManualNamingCategory.mockReset().mockResolvedValue({});
    namingApi.classifyBatchNamingCategories.mockReset().mockImplementation((input) =>
      Promise.resolve({
        target_label: "项目知识库 / 项目 A",
        candidate_rule_revision: 3,
        candidate_count: 2,
        items: input.taskIds.map((taskId: string) => ({
          task_id: taskId,
          suggested_category_id: "deliverable",
          category_source: "ai_content",
          category_confidence: "high",
          category_reason: "AI 根据正文语义匹配当前目标的目录规则",
          candidate_rule_revision: 3,
          status: "classified",
          retryable: false,
        })),
      }),
    );
  });

  it("requires a formal personal directory, keeps item exceptions, and submits no naming requests", async () => {
    const tasks = [task("personal-one"), task("personal-two")];
    const handleBatchConfirm = vi.fn();
    render(<PendingBatchActions tasks={tasks} flow={flowFixture(tasks, { handleBatchConfirm })} />);

    fireEvent.click(screen.getByRole("button", { name: /批量确认入库/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "personal" },
    });

    const directory = await screen.findByRole("combobox", { name: "本批个人目录" });
    expect(directory).toHaveTextContent("01 个人学习笔记");
    expect(directory).toHaveTextContent("02 个人项目资料");
    expect(directory).not.toHaveTextContent("04 待处理");
    expect(screen.getByRole("button", { name: "下一步：核对入库" })).toBeDisabled();

    fireEvent.change(directory, { target: { value: "personal.learning_notes" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对入库" }));

    expect(await screen.findByText(/本批默认进入“01 个人学习笔记”/)).toBeInTheDocument();
    expect(screen.queryByText("目录类别")).not.toBeInTheDocument();
    expect(screen.queryByText("文件形成日期")).not.toBeInTheDocument();
    expect(screen.queryByText("规范名预览")).not.toBeInTheDocument();
    expect(namingApi.classifyBatchNamingCategories).not.toHaveBeenCalled();
    expect(namingApi.previewBatchIngestNaming).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("personal-two.pdf 个人目录"), {
      target: { value: "personal.project_materials" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "查看 AI 提取" })[0]);
    const aiDrawer = await screen.findByRole("dialog", { name: "AI 提取核对" });
    fireEvent.click(within(aiDrawer).getByRole("button", { name: "取消" }));
    expect(screen.getByLabelText("personal-one.pdf 个人目录")).toHaveValue(
      "personal.learning_notes",
    );
    expect(screen.getByLabelText("personal-two.pdf 个人目录")).toHaveValue(
      "personal.project_materials",
    );

    fireEvent.click(screen.getByRole("button", { name: "确认已选择的 2 项入库" }));
    expect(handleBatchConfirm).toHaveBeenCalledWith(
      tasks,
      "personal",
      undefined,
      undefined,
      expect.any(Object),
      true,
      expect.any(Function),
      undefined,
      {
        "personal-one": "personal.learning_notes",
        "personal-two": "personal.project_materials",
      },
    );
  });

  it("offers a scoped directory fallback only after governed preview reports a missing mapping", async () => {
    const item = task("company-fallback");
    namingApi.previewBatchIngestNaming
      .mockResolvedValueOnce({
        items: [
          {
            task_id: item.id,
            submittable: false,
            canonical_name: null,
            fields: {},
            notices: [],
            error_code: "directory_required",
            message: "该命名类别无法唯一映射目录，请人工选择",
          },
        ],
      })
      .mockResolvedValue({
        items: [
          {
            task_id: item.id,
            submittable: true,
            canonical_name: "公司规范名.pdf",
            fields: {},
            notices: [],
            error_code: null,
            message: null,
          },
        ],
      });
    render(<PendingBatchActions tasks={[item]} flow={flowFixture([item])} />);

    fireEvent.click(screen.getByRole("button", { name: /批量确认入库/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "company" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));
    const applicableTo = await screen.findByLabelText("company-fallback.pdf 适用对象");
    fireEvent.change(applicableTo, { target: { value: "咨询项目团队" } });

    const fallback = await screen.findByRole("button", { name: "选择正式公司目录" });
    fireEvent.click(fallback);
    const directory = screen.getByRole("combobox", { name: "正式公司目录" });
    expect(directory).toHaveTextContent("03 公司方法论");
    expect(directory).not.toHaveTextContent("03 项目交付成果");
    fireEvent.change(directory, { target: { value: "company.methodology" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并重新预览" }));

    await waitFor(() =>
      expect(namingApi.previewBatchIngestNaming).toHaveBeenLastCalledWith(
        expect.objectContaining({
          targetScope: "company",
          items: [
            expect.objectContaining({
              naming: expect.objectContaining({
                directory_key: "company.methodology",
                directory_fallback_confirmed: true,
              }),
            }),
          ],
        }),
      ),
    );
    expect(screen.getByLabelText("company-fallback.pdf 目录类别")).toHaveValue("deliverable");
  });

  it("uses a wide review workspace and retains manual categories when AI classification fails", async () => {
    namingApi.classifyBatchNamingCategories.mockRejectedValueOnce(new Error("model unavailable"));
    const tasks = [task("manual-after-ai-failure")];
    render(<PendingBatchActions tasks={tasks} flow={flowFixture(tasks)} />);

    await openProjectReview();

    const workspace = topDialog();
    expect(workspace).toHaveClass("naming-review-workspace");
    expect(workspace).toHaveTextContent("AI 目录建议暂时失败");
    const category = within(workspace).getByLabelText("manual-after-ai-failure.pdf 目录类别");
    expect(category).toHaveTextContent("项目资料 / 交付成果");
    fireEvent.change(category, { target: { value: "deliverable" } });
    expect(category).toHaveValue("deliverable");
  });

  it("retries target category loading without losing the still-open confirmation", async () => {
    namingApi.fetchNamingOptions.mockRejectedValueOnce(new Error("temporary outage"));
    const tasks = [task("reload-options")];
    render(<PendingBatchActions tasks={tasks} flow={flowFixture(tasks)} />);

    fireEvent.click(screen.getByRole("button", { name: /批量确认入库/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    expect(await screen.findByRole("button", { name: "重新加载规则" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载规则" }));
    expect(await screen.findByLabelText("核对状态筛选")).toBeInTheDocument();
  });

  it("applies one manual category to the batch, bypasses AI classification, and permits exceptions", async () => {
    const tasks = [task("bulk-one"), task("bulk-two")];
    render(<PendingBatchActions tasks={tasks} flow={flowFixture(tasks)} />);

    fireEvent.click(screen.getByRole("button", { name: /批量确认入库/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    const bulkCategory = await screen.findByRole("combobox", { name: "本批目录类别" });
    await waitFor(() => expect(bulkCategory).toHaveTextContent("项目资料 / 交付成果"));
    fireEvent.change(bulkCategory, { target: { value: "deliverable" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    expect(await screen.findAllByText("批量设置")).toHaveLength(2);
    expect(namingApi.classifyBatchNamingCategories).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "重试待分类项" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试此项" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("bulk-two.pdf 目录类别"), {
      target: { value: "method" },
    });
    expect(screen.getByLabelText("bulk-one.pdf 目录类别")).toHaveValue("deliverable");
    expect(screen.getByLabelText("bulk-two.pdf 目录类别")).toHaveValue("method");
    expect(screen.getByText("人工已选择")).toBeInTheDocument();
    expect(namingApi.classifyBatchNamingCategories).not.toHaveBeenCalled();
  });

  it("loads AI extraction only on demand and retains the reviewed draft for final confirmation", async () => {
    const item = task("ai-draft");
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: item.id,
          submittable: true,
          canonical_name: "项目资料-AI核对-20260803-V1-L3",
          fields: {},
          notices: [],
        },
      ],
    });
    const handleBatchConfirm = vi.fn();
    render(
      <PendingBatchActions tasks={[item]} flow={flowFixture([item], { handleBatchConfirm })} />,
    );

    await openProjectReview();
    expect(ingestApi.fetchIngestAiResult).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "查看 AI 提取" }));
    expect(await screen.findByRole("dialog", { name: "AI 提取核对" })).toBeInTheDocument();
    expect(ingestApi.fetchIngestAiResult).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("textbox", { name: "建议标题" }), {
      target: { value: "人工核对标题" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "详细摘要" }), {
      target: { value: "人工核对后的详细摘要" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存本条修改" }));
    fireEvent.click(screen.getByRole("button", { name: "查看 AI 提取" }));
    expect(await screen.findByRole("textbox", { name: "建议标题" })).toHaveValue("人工核对标题");
    fireEvent.click(screen.getByRole("button", { name: "保存本条修改" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "确认已选择的 1 项入库" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确认已选择的 1 项入库" }));
    expect(handleBatchConfirm).toHaveBeenCalledWith(
      [item],
      "project",
      "project-a",
      expect.any(Object),
      expect.any(Object),
      true,
      expect.any(Function),
      {
        [item.id]: expect.objectContaining({
          title: "人工核对标题",
          summary: "人工核对后的详细摘要",
        }),
      },
    );
  });

  it("keeps processing, failed, and forbidden AI results safe and item-scoped", async () => {
    const tasks = [task("processing-ai"), task("failed-ai"), task("forbidden-ai")];
    ingestApi.fetchIngestAiResult
      .mockReset()
      .mockResolvedValueOnce({
        ingest_task_id: tasks[0].id,
        status: "processing",
        suggestion_generation_status: "needs_manual_completion",
      })
      .mockResolvedValueOnce({
        ingest_task_id: tasks[1].id,
        status: "failed",
        suggestion_generation_status: "needs_manual_completion",
      })
      .mockRejectedValueOnce(new ApiError(403, "internal detail", "ingest_result_forbidden"));
    render(<PendingBatchActions tasks={tasks} flow={flowFixture(tasks)} />);
    await openProjectReview();

    const reviewButtons = screen.getAllByRole("button", { name: "查看 AI 提取" });
    fireEvent.click(reviewButtons[0]);
    expect(await screen.findByText("AI 提取仍在处理中，完成前不会提交入库。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新状态" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /确认入库/ }).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));

    fireEvent.click(reviewButtons[1]);
    expect(
      await screen.findByText("AI 提取未完成，可重试生成；当前资料不会因此入库。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试生成" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));

    fireEvent.click(reviewButtons[2]);
    expect(await screen.findByText("当前身份无权查看这条资料的 AI 提取结果。")).toBeInTheDocument();
    expect(screen.queryByText("internal detail")).not.toBeInTheDocument();
  });

  it("filters and counts AI-ready, manual, reviewed, and exceptional rows", async () => {
    const aiReady = task("ai-ready", {
      naming_parsed_fields: {
        ...task("ai-ready").naming_parsed_fields!,
        inferred_fields: ["secondary_category"],
        missing_fields: ["primary_category"],
      },
    });
    const manual = task("manual", {
      naming_parsed_fields: {
        ...task("manual").naming_parsed_fields!,
        date: "20260803",
        inferred_fields: ["date"],
        missing_fields: ["date"],
      },
    });
    const reviewed = task("reviewed");
    const duplicate = task("duplicate");
    const tasks = [aiReady, manual, reviewed, duplicate];
    const flow = flowFixture(tasks);
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: aiReady.id,
          submittable: false,
          canonical_name: null,
          rule_version: null,
          fields: null,
          notices: [],
          error_code: null,
          message: null,
        },
        {
          task_id: manual.id,
          submittable: false,
          canonical_name: null,
          rule_version: null,
          fields: null,
          notices: [],
          error_code: null,
          message: null,
        },
        {
          task_id: reviewed.id,
          submittable: true,
          canonical_name: "【P-2026-交付成果】reviewed主题_20260803_V1_L2.pdf",
          rule_version: 3,
          fields: { subject: "reviewed主题" },
          notices: [],
          error_code: null,
          message: null,
        },
        {
          task_id: duplicate.id,
          submittable: true,
          canonical_name: "【P-2026-交付成果】duplicate主题_20260803_V1_L2.pdf",
          rule_version: 3,
          fields: { subject: "duplicate主题" },
          notices: [{ code: "exact_duplicate", kind: "exact", message: "已存在相同文件，请核对" }],
          error_code: null,
          message: null,
        },
      ],
    });

    render(<PendingBatchActions tasks={tasks} flow={flow} />);
    await openProjectReview();
    expect(screen.getByRole("button", { name: "AI 已确定（3）" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("ai-ready.pdf 主题"), {
      target: { value: "人工改动" },
    });
    expect(screen.getByRole("button", { name: "AI 已确定（2）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "需人工补齐（2）" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("ai-ready.pdf 主题"), {
      target: { value: "ai-ready主题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成或刷新全部预览" }));

    await screen.findByRole("button", { name: "AI 已确定（0）" });
    expect(screen.getByRole("button", { name: "需人工补齐（2）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "已核对（2）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "异常/重复（0）" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "已核对（2）" }));
    expect(screen.getByText("当前筛选显示 2/4 条")).toBeInTheDocument();
    expect(screen.getByText(/reviewed\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/duplicate\.pdf/)).toBeInTheDocument();
    expect(screen.queryByText(/manual\.pdf/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仍然确认已选择的 4 项入库" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "异常/重复（0）" }));
    expect(screen.getByText("当前筛选下没有资料")).toBeInTheDocument();
    expect(screen.queryByText(/reviewed\.pdf/)).not.toBeInTheDocument();
    const dialog = screen.getByRole("dialog", { name: "逐条核对 4 项规范命名" });
    const scrollRegion = dialog.querySelector(".upload77-batch-naming-scroll");
    const closeButton = within(dialog).getByRole("button", { name: "关闭批量命名核对" });
    const confirmButton = within(dialog).getByRole("button", {
      name: "仍然确认已选择的 4 项入库",
    });
    const cancelButton = within(dialog).getByRole("button", { name: "取消" });
    expect(scrollRegion).toBeInTheDocument();
    expect(scrollRegion).not.toContainElement(closeButton);
    expect(scrollRegion).not.toContainElement(confirmButton);
    expect(scrollRegion).not.toContainElement(cancelButton);
    expect(flow.handleBatchConfirm).not.toHaveBeenCalled();
  });

  it("never marks any remaining missing or inferred field as AI-determined", async () => {
    const inferredLevel = task("inferred-level", {
      naming_parsed_fields: {
        ...task("inferred-level").naming_parsed_fields!,
        inferred_fields: ["confidentiality_level"],
      },
    });
    const missingAccess = task("missing-access", {
      naming_parsed_fields: {
        ...task("missing-access").naming_parsed_fields!,
        missing_fields: ["ai_access_level"],
      },
    });
    const tasks = [inferredLevel, missingAccess];

    render(<PendingBatchActions tasks={tasks} flow={flowFixture(tasks)} />);
    await openProjectReview();

    expect(screen.getByRole("button", { name: "AI 已确定（0）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "需人工补齐（2）" })).toBeInTheDocument();
  });

  it("shows persisted filename version and reliable AI content confidentiality sources", async () => {
    const item = task("source-priority", {
      source_file_name: "项目复盘_V1.1_L3.md",
      suggested_version: "V1.1",
      version_source: "source_filename",
      version_confidence: "high",
      suggested_confidentiality_level: "L4",
      confidentiality_source: "ai_content",
      confidentiality_confidence: "high",
      confidentiality_reason: "AI 根据正文内容特征建议为 L4",
    });

    render(<PendingBatchActions tasks={[item]} flow={flowFixture([item])} />);
    await openProjectReview();

    expect(screen.getByLabelText("项目复盘_V1.1_L3.md 版本")).toHaveValue("V1.1");
    expect(screen.getByText("来自源文件")).toBeInTheDocument();
    expect(screen.getByLabelText("项目复盘_V1.1_L3.md 密级")).toHaveValue("L4");
    expect(screen.getByText("AI 内容建议 · 高置信度")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 已确定（1）" })).toBeInTheDocument();
  });

  it("treats legacy advice as editable defaults and accepts decimal version edits", async () => {
    const item = task("legacy-advice", {
      suggested_version: undefined,
      version_source: undefined,
      version_confidence: undefined,
      suggested_confidentiality_level: "L5",
      confidentiality_source: undefined,
      confidentiality_confidence: undefined,
    });

    render(<PendingBatchActions tasks={[item]} flow={flowFixture([item])} />);
    await openProjectReview();

    const version = screen.getByLabelText("legacy-advice.pdf 版本");
    const level = screen.getByLabelText("legacy-advice.pdf 密级");
    expect(version).toHaveValue("V1");
    expect(level).toHaveValue("L2");
    expect(screen.getByText("规则默认，需核对")).toBeInTheDocument();
    expect(screen.getByText("AI 未确定，规则默认，需核对")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 已确定（0）" })).toBeInTheDocument();

    fireEvent.change(version, { target: { value: "V2.03" } });
    fireEvent.change(level, { target: { value: "L3" } });
    expect(version).toHaveValue("V2.03");
    expect(level).toHaveValue("L3");
    expect(screen.getAllByText("已人工修改")).toHaveLength(2);
  });

  it("handles an empty delayed preview return without an unhandled exception", async () => {
    const item = task("empty-preview");
    namingApi.previewBatchIngestNaming.mockReturnValue(undefined);

    render(<PendingBatchActions tasks={[item]} flow={flowFixture([item])} />);
    await openProjectReview();

    expect(
      await screen.findByText("规范名预览暂时失败，请重试；已保留上一次有效预览"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("empty-preview.pdf 主题")).toHaveValue("empty-preview主题");
  });

  it("cancels a pending delayed preview when the review dialog closes", async () => {
    const item = task("close-preview");
    namingApi.previewBatchIngestNaming.mockResolvedValue({ items: [] });

    render(<PendingBatchActions tasks={[item]} flow={flowFixture([item])} />);
    await openProjectReview();
    fireEvent.click(within(topDialog()).getByRole("button", { name: "关闭批量命名核对" }));
    expect(topDialog()).toHaveTextContent("放弃本次批量命名核对");
    fireEvent.click(within(topDialog()).getByRole("button", { name: "放弃修改并关闭" }));
    await new Promise((resolve) => window.setTimeout(resolve, 300));

    expect(namingApi.previewBatchIngestNaming).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    expect(screen.getByRole("combobox", { name: "批量入库目标知识库" })).toHaveValue("");
  });

  it("keeps governed edits and target context when batch submission has failures", async () => {
    const item = task("retry-governed");
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: item.id,
          submittable: true,
          canonical_name: "【P-2026-交付成果】保留的主题_20260803_V1_L2.pdf",
          rule_version: 3,
          fields: { subject: "保留的主题" },
          notices: [],
          error_code: null,
          message: null,
        },
      ],
    });
    const handleBatchConfirm = vi.fn(
      async (...args: Parameters<UploadFlow["handleBatchConfirm"]>) => {
        args[6]?.({ succeededIds: [], failedIds: [item.id] });
      },
    );

    render(
      <PendingBatchActions tasks={[item]} flow={flowFixture([item], { handleBatchConfirm })} />,
    );
    await openProjectReview();
    fireEvent.change(screen.getByLabelText("retry-governed.pdf 主题"), {
      target: { value: "保留的主题" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "确认已选择的 1 项入库" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确认已选择的 1 项入库" }));

    await screen.findByText(/1 项资料确认未完成/);
    expect(screen.getByRole("dialog", { name: "逐条核对 1 项规范命名" })).toBeInTheDocument();
    expect(screen.getByLabelText("retry-governed.pdf 主题")).toHaveValue("保留的主题");
    expect(handleBatchConfirm).toHaveBeenCalledWith(
      [item],
      "project",
      "project-a",
      expect.objectContaining({
        [item.id]: expect.objectContaining({ subject: "保留的主题" }),
      }),
      { [item.id]: [] },
      true,
      expect.any(Function),
    );
  });

  it("closes and clears governed review only after every submitted item succeeds", async () => {
    const item = task("successful-governed");
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: item.id,
          submittable: true,
          canonical_name: "【P-2026-交付成果】successful-governed主题_20260803_V1_L2.pdf",
          rule_version: 3,
          fields: { subject: "successful-governed主题" },
          notices: [],
          error_code: null,
          message: null,
        },
      ],
    });
    const handleBatchConfirm = vi.fn(
      async (...args: Parameters<UploadFlow["handleBatchConfirm"]>) => {
        args[6]?.({ succeededIds: [item.id], failedIds: [] });
      },
    );

    render(
      <PendingBatchActions tasks={[item]} flow={flowFixture([item], { handleBatchConfirm })} />,
    );
    await openProjectReview();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "确认已选择的 1 项入库" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确认已选择的 1 项入库" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it.each(["path_b_upload", "path_a_wecom"] as const)(
    "keeps an eight-item %s review session after one item succeeds",
    async (source) => {
      const initialTasks = Array.from({ length: 8 }, (_, index) =>
        task(`session-${index}`, { source }),
      );
      namingApi.previewBatchIngestNaming.mockImplementation(
        async (input: { items: Array<{ taskId: string; naming: { subject: string } }> }) => ({
          items: input.items.map(({ taskId, naming }) => ({
            task_id: taskId,
            submittable: true,
            canonical_name: `【P-2026-交付成果】${naming.subject}_20260803_V1_L2.pdf`,
            rule_version: 3,
            fields: { subject: naming.subject },
            notices: [],
            error_code: null,
            message: null,
          })),
        }),
      );

      function Harness() {
        const [currentTasks, setCurrentTasks] = useState(initialTasks);
        const [selection, setSelection] = useState(initialTasks.map((item) => item.id));
        const flow = flowFixture(currentTasks, {
          batchSelection: selection,
          handleSingleBatchConfirm: async (confirmed: PendingIngestItemDTO) => {
            setCurrentTasks((current) => current.filter((item) => item.id !== confirmed.id));
            setSelection((current) => current.filter((id) => id !== confirmed.id));
            return {
              succeededIds: [confirmed.id],
              failedIds: [],
              resultAssetIds: { [confirmed.id]: `asset-${confirmed.id}` },
            };
          },
        });
        return <PendingBatchActions tasks={currentTasks} flow={flow} />;
      }

      render(<Harness />);
      await openProjectReview();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "确认入库 session-0.pdf" })).toBeEnabled(),
      );
      fireEvent.change(screen.getByLabelText("session-1.pdf 主题"), {
        target: { value: "仍在编辑的第二条" },
      });
      fireEvent.click(screen.getByRole("button", { name: "确认入库 session-0.pdf" }));
      fireEvent.click(within(topDialog()).getByRole("button", { name: "确认入库" }));

      const assetLink = await screen.findByRole("link", {
        name: "查看知识资产卡片：session-0主题",
      });
      expect(screen.getByRole("dialog", { name: "逐条核对 8 项规范命名" })).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: /确认入库 session-/ })).toHaveLength(7);
      expect(screen.getByLabelText("session-1.pdf 主题")).toHaveValue("仍在编辑的第二条");
      expect(screen.getByRole("button", { name: "全部（7）" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(assetLink).toHaveAttribute("href", "/knowledge/asset-session-0");
      expect(assetLink).toHaveAttribute("target", "_blank");
      expect(assetLink).toHaveAttribute("rel", "noopener noreferrer");
      fireEvent.click(assetLink);
      expect(screen.getByRole("dialog", { name: "逐条核对 8 项规范命名" })).toBeInTheDocument();
      expect(screen.getByLabelText("session-1.pdf 主题")).toHaveValue("仍在编辑的第二条");
    },
  );

  it.each(["path_b_upload", "path_a_wecom"] as const)(
    "removes a vanished %s task from the open review session after refresh",
    async (source) => {
      const initialTasks = Array.from({ length: 8 }, (_, index) =>
        task(`refresh-${index}`, { source }),
      );
      const { rerender } = render(
        <PendingBatchActions tasks={initialTasks} flow={flowFixture(initialTasks)} />,
      );
      await openProjectReview();
      fireEvent.change(screen.getByLabelText("refresh-1.pdf 主题"), {
        target: { value: "刷新后仍保留的编辑值" },
      });

      const refreshedTasks = initialTasks.filter((item) => item.id !== "refresh-3");
      rerender(<PendingBatchActions tasks={refreshedTasks} flow={flowFixture(refreshedTasks)} />);

      await waitFor(() =>
        expect(screen.queryByLabelText("refresh-3.pdf 主题")).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("dialog", { name: "逐条核对 8 项规范命名" })).toBeInTheDocument();
      expect(screen.getAllByRole("button", { name: /确认入库 refresh-/ })).toHaveLength(7);
      expect(screen.getByLabelText("refresh-1.pdf 主题")).toHaveValue("刷新后仍保留的编辑值");
      expect(screen.getByRole("button", { name: "全部（7）" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    },
  );

  it("keeps the completed result visible when the last review item succeeds", async () => {
    const item = task("last-item");
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: item.id,
          submittable: true,
          canonical_name: "【P-2026-交付成果】last-item主题_20260803_V1_L2.pdf",
          rule_version: 3,
          fields: { subject: "last-item主题" },
          notices: [],
          error_code: null,
          message: null,
        },
      ],
    });
    function Harness() {
      const [currentTasks, setCurrentTasks] = useState([item]);
      const flow = flowFixture(currentTasks, {
        handleSingleBatchConfirm: async () => {
          setCurrentTasks([]);
          return {
            succeededIds: [item.id],
            failedIds: [],
            resultAssetIds: { [item.id]: "asset-last" },
          };
        },
      });
      return <PendingBatchActions tasks={currentTasks} flow={flow} />;
    }

    render(<Harness />);
    await openProjectReview();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "确认入库 last-item.pdf" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "确认入库 last-item.pdf" }));
    fireEvent.click(within(topDialog()).getByRole("button", { name: "确认入库" }));

    expect(
      await screen.findByText("本批待核对资料已处理完成，可查看本次结果或关闭弹窗"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看知识资产卡片：last-item主题" })).toHaveAttribute(
      "href",
      "/knowledge/asset-last",
    );
    expect(screen.getByRole("button", { name: "关闭批量命名核对" })).toBeInTheDocument();
  });

  it("permanently deletes one row while preserving the filter and other edits", async () => {
    const first = task("first");
    const second = task("second");
    const deleteItem = vi.fn();

    function Harness() {
      const [tasks, setTasks] = useState([first, second]);
      const flow = flowFixture(tasks, {
        handleDeleteBatchReviewItem: async (taskId: string) => {
          deleteItem(taskId);
          setTasks((current) => current.filter((item) => item.id !== taskId));
          return { ok: true as const };
        },
      });
      return <PendingBatchActions tasks={tasks} flow={flow} />;
    }

    render(<Harness />);
    await openProjectReview();
    fireEvent.click(screen.getByRole("button", { name: "AI 已确定（2）" }));
    fireEvent.change(screen.getByLabelText("second.pdf 主题"), {
      target: { value: "人工修改后保留" },
    });
    fireEvent.click(screen.getByRole("button", { name: "删除 first.pdf" }));

    const deleteDialog = topDialog();
    expect(deleteDialog).toHaveTextContent("永久删除该错误上传资料");
    expect(deleteDialog).toHaveTextContent("不可恢复");
    fireEvent.click(within(deleteDialog).getByRole("button", { name: "确认永久删除" }));

    await waitFor(() => expect(deleteItem).toHaveBeenCalledWith("first"));
    expect(screen.queryByText(/first\.pdf/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /AI 已确定/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText("second.pdf 主题")).toHaveValue("人工修改后保留");
    fireEvent.click(screen.getByRole("button", { name: "需人工补齐（1）" }));
    expect(screen.getByLabelText("second.pdf 主题")).toHaveValue("人工修改后保留");
  });

  it("keeps the row on cancel and exposes retry only for transient deletion failures", async () => {
    const item = task("keep-me");
    const deleteItem = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        message: "服务暂时不可用，任务仍保留，可重试。",
        retryable: true,
      })
      .mockResolvedValueOnce({ ok: false, message: "当前任务不能永久删除。", retryable: false });
    const flow = flowFixture([item], { handleDeleteBatchReviewItem: deleteItem });
    render(<PendingBatchActions tasks={[item]} flow={flow} />);
    await openProjectReview();

    fireEvent.click(screen.getByRole("button", { name: "删除 keep-me.pdf" }));
    fireEvent.click(within(topDialog()).getByRole("button", { name: "取消" }));
    expect(deleteItem).not.toHaveBeenCalled();
    expect(screen.getByLabelText("keep-me.pdf 主题")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除 keep-me.pdf" }));
    fireEvent.click(
      within(topDialog()).getByRole("button", {
        name: "确认永久删除",
      }),
    );
    expect(await screen.findByRole("button", { name: "重试删除" })).toBeInTheDocument();
    expect(screen.getByLabelText("keep-me.pdf 主题")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试删除" }));
    fireEvent.click(
      within(topDialog()).getByRole("button", {
        name: "确认永久删除",
      }),
    );
    await screen.findByText("当前任务不能永久删除。");
    expect(screen.queryByRole("button", { name: "重试删除" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("keep-me.pdf 主题")).toBeInTheDocument();
  });

  it("does not present an ineligible row as successfully deletable", async () => {
    const item = task("locked", { can_batch_reject: false });
    const deleteItem = vi.fn();
    render(
      <PendingBatchActions
        tasks={[item]}
        flow={flowFixture([item], { handleDeleteBatchReviewItem: deleteItem })}
      />,
    );
    await openProjectReview();

    expect(screen.getByRole("button", { name: "删除 locked.pdf" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "删除 locked.pdf" })).toHaveAttribute(
      "title",
      "当前资料不能永久删除",
    );
    expect(deleteItem).not.toHaveBeenCalled();
  });

  it("atomically switches the retained same-batch item and keeps the skipped row visible", async () => {
    const first = task("same-a");
    const second = task("same-b");
    const sameBatch = (taskId: string) => ({
      duplicate_state: "same_batch",
      match_type: "same_batch",
      match_count: 2,
      preferred_candidate: {
        match_type: "same_batch",
        title: null,
        file_name: null,
        file_size: null,
        scope: "personal",
        scope_label: "我的个人库",
        directory_key: null,
        subject: null,
        formed_on: null,
        version: null,
        asset_status: null,
        ingested_at: null,
        safe_summary: null,
        asset_id: null,
        can_view_detail: false,
        can_view_original: false,
        same_batch_ordinal: taskId === first.id ? 1 : 0,
      },
      same_batch_group_id: "group-1",
      same_batch_first_ordinal: 0,
      default_selected: taskId === first.id,
      decision: null,
    });
    namingApi.previewIngestNaming.mockImplementation((taskId: string) =>
      Promise.resolve({
        required: false,
        canonical_name: null,
        rule_version: null,
        fields: null,
        notices: [],
        message: null,
        duplicate: sameBatch(taskId),
      }),
    );
    ingestApi.decideUploadDuplicate.mockResolvedValue({
      task_id: second.id,
      status: "pending_confirmation",
      decision: "batch_keep",
      skipped_task_ids: [first.id],
      duplicate: { ...sameBatch(second.id), default_selected: true, decision: "batch_keep" },
    });
    render(<PendingBatchActions tasks={[first, second]} flow={flowFixture([first, second])} />);

    fireEvent.click(screen.getByRole("button", { name: /批量确认入库/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "personal" },
    });
    const directory = await screen.findByRole("combobox", { name: "本批个人目录" });
    fireEvent.change(directory, { target: { value: "personal.learning_notes" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对入库" }));

    const secondRow = (await screen.findByText(/2\. same-b\.pdf/)).closest("article")!;
    fireEvent.click(within(secondRow).getByRole("button", { name: "对比" }));
    fireEvent.click(within(secondRow).getByRole("button", { name: "设为本批保留项" }));

    await waitFor(() =>
      expect(ingestApi.decideUploadDuplicate).toHaveBeenCalledWith(
        expect.objectContaining({ taskId: second.id, action: "keep" }),
      ),
    );
    expect(
      (await screen.findAllByText("本次不入库")).some(
        (element) => element.getAttribute("role") === "status",
      ),
    ).toBe(true);
    expect(screen.getByText("same-a.pdf")).toBeInTheDocument();
  });
});
