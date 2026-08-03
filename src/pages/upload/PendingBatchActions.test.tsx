import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import PendingBatchActions from "./PendingBatchActions";
import type { UploadFlow } from "./useUploadFlow";

const namingApi = vi.hoisted(() => ({
  classifyBatchNamingCategories: vi.fn(),
  fetchNamingOptions: vi.fn(),
  previewBatchIngestNaming: vi.fn(),
  saveManualNamingCategory: vi.fn(),
}));
vi.mock("../../api/naming", () => namingApi);

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
    namingApi.fetchNamingOptions.mockReset().mockResolvedValue({
      required: true,
      rule_version: 3,
      categories: [
        {
          id: "deliverable",
          primary: "项目资料",
          secondary: "交付成果",
          prefix: "项目资料-交付成果",
          default_confidentiality: "L2",
        },
      ],
      default_confidentiality: "L2",
      message: null,
    });
    namingApi.previewBatchIngestNaming.mockReset();
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
    expect(screen.getByRole("button", { name: "仍然确认批量入库" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "异常/重复（0）" }));
    expect(screen.getByText("当前筛选下没有资料")).toBeInTheDocument();
    expect(screen.queryByText(/reviewed\.pdf/)).not.toBeInTheDocument();
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
    fireEvent.click(within(topDialog()).getByRole("button", { name: "取消" }));
    await new Promise((resolve) => window.setTimeout(resolve, 300));

    expect(namingApi.previewBatchIngestNaming).not.toHaveBeenCalled();
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
});
