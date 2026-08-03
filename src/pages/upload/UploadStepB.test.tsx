import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import UploadStepB from "./UploadStepB";
import type { UploadFlow } from "./useUploadFlow";

const namingApi = vi.hoisted(() => ({
  classifyBatchNamingCategories: vi.fn(),
  fetchNamingOptions: vi.fn(),
  previewBatchIngestNaming: vi.fn(),
  saveManualNamingCategory: vi.fn(),
}));
vi.mock("../../api/naming", () => namingApi);

function pending(id: string, fileName: string): PendingIngestItemDTO {
  return {
    id,
    source: "path_b_upload",
    status: "pending_confirmation",
    source_file_name: fileName,
    target_scope: "personal",
    target_project_id: null,
    can_batch_confirm: true,
    can_batch_reject: true,
    extraction_status: "extracted",
    error_type: null,
    error_message: null,
    suggested_title: "安全标题",
    suggested_one_liner: null,
    naming_parsed_fields: null,
    confidence: null,
    suggestion_generation_status: "needs_correction",
    suggestion_generation_reason: "摘要未生成，请核对",
    result_asset_id: null,
    created_at: null,
    updated_at: null,
  };
}

function flowFixture(overrides: Record<string, unknown> = {}): UploadFlow {
  const tasks = [pending("task-secret-a", "A.pptx"), pending("task-secret-b", "B.docx")];
  return {
    flowState: "idle",
    fileName: "",
    fileSize: 0,
    fileType: "",
    hasFile: false,
    extraction: null,
    fileRef: { current: null },
    handleFileSelect: vi.fn(),
    handleDataTransferDrop: vi.fn().mockResolvedValue(undefined),
    folderDropNotice: null,
    intakeFeedback: null,
    handleStart: vi.fn(),
    localUploadQueue: [],
    uploadSession: null,
    retryLocalUpload: vi.fn(),
    removeLocalUpload: vi.fn(),
    removeFailedLocalUploads: vi.fn(),
    handleRefreshProcessing: vi.fn(),
    handleReset: vi.fn(),
    handleDeletePending: vi.fn(),
    apiError: null,
    processingNote: null,
    localPendingTasks: tasks,
    localPendingLoading: false,
    localPendingError: null,
    loadLocalPending: vi.fn(),
    handleSelectPendingTask: vi.fn(),
    taskId: null,
    batchSelection: tasks.map((task) => task.id),
    batchStatus: {},
    batchBusy: false,
    batchOperation: null,
    batchErrors: {},
    batchRejectRetryability: {},
    toggleBatchTask: vi.fn(),
    setBatchTasksSelected: vi.fn(),
    handleBatchConfirm: vi.fn(),
    handleSingleBatchConfirm: vi.fn().mockResolvedValue({ succeededIds: [], failedIds: [] }),
    handleBatchReject: vi.fn(),
    handleDeleteBatchReviewItem: vi.fn().mockResolvedValue({ ok: true }),
    projects: [{ projectId: "project-a", projectName: "项目 A" }],
    canUseCompanyTarget: false,
    ...overrides,
  } as unknown as UploadFlow;
}

describe("UploadStepB folder drop and batch rejection", () => {
  beforeEach(() => {
    namingApi.fetchNamingOptions.mockReset();
    namingApi.previewBatchIngestNaming.mockReset();
    namingApi.saveManualNamingCategory.mockReset().mockResolvedValue({});
    namingApi.fetchNamingOptions.mockResolvedValue({
      required: true,
      rule_version: 2,
      categories: [
        {
          id: "category-a",
          primary: "项目资料",
          secondary: "交付件",
          prefix: "项目资料-交付件",
          default_confidentiality: "L2",
        },
      ],
      default_confidentiality: "L2",
      message: null,
    });
    namingApi.classifyBatchNamingCategories.mockReset().mockImplementation((input) =>
      Promise.resolve({
        target_label: "项目知识库 / 项目 A",
        candidate_rule_revision: 2,
        candidate_count: 1,
        items: input.taskIds.map((taskId: string) => ({
          task_id: taskId,
          suggested_category_id: "category-a",
          category_source: "rule_only_option",
          category_confidence: "high",
          category_reason: "当前规则只有一个启用目录类别",
          candidate_rule_revision: 2,
          status: "classified",
          retryable: false,
        })),
      }),
    );
  });
  it.each([1280, 1440, 1920])(
    "keeps the isolated pending-table layout contract at %ipx",
    (viewportWidth) => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: viewportWidth });
      const fileName = "客户经营分析与下一阶段行动计划最终修订版本.pptx";
      const subject = "客户经营分析与下一阶段行动计划及关键管理举措";
      const task = { ...pending("layout", fileName), suggested_title: subject };
      render(<UploadStepB flow={flowFixture({ localPendingTasks: [task], batchSelection: [] })} />);

      const table = screen.getByRole("table");
      expect(table).toHaveClass("upload77-pending-table");
      expect(table.closest(".upload77-table-wrap")).not.toBeNull();
      expect(table.querySelectorAll("colgroup col")).toHaveLength(7);
      expect(table.querySelector(".upload77-pending-col-file")).not.toBeNull();
      expect(table.querySelector(".upload77-pending-col-subject")).not.toBeNull();
      expect(screen.getByRole("columnheader", { name: "建议主题" })).toBeInTheDocument();
      expect(screen.queryByRole("columnheader", { name: "建议标题" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: fileName })).toHaveAttribute("title", fileName);
      expect(screen.getByText(subject)).toHaveClass("upload77-pending-truncate");
      expect(screen.getByText(subject)).toHaveAttribute("title", subject);
    },
  );

  it("uses the server batch capability for legacy pending selection", () => {
    const legacy = {
      ...pending("legacy", "legacy-notes.md"),
      status: "pending",
      can_batch_reject: false,
      suggestion_generation_status: "generated" as const,
      suggestion_generation_reason: "旧 Markdown 建议字段已准备",
    };
    const flow = flowFixture({
      localPendingTasks: [legacy],
      batchSelection: [],
    });
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByLabelText("全选当前可处理的待确认项"));
    expect(flow.setBatchTasksSelected).toHaveBeenCalledWith(["legacy"], true);
    expect(screen.getByLabelText("选择 legacy-notes.md")).toBeEnabled();
    expect(screen.getByText("建议已生成")).toBeInTheDocument();
  });

  it("keeps selection explanations outside the table header", () => {
    const blocked = {
      ...pending("blocked", "blocked.docx"),
      can_batch_confirm: false,
      can_batch_reject: false,
    };
    render(
      <UploadStepB flow={flowFixture({ localPendingTasks: [blocked], batchSelection: [] })} />,
    );

    const reason = screen.getByText("当前没有可批量处理的待确认项");
    expect(reason.closest("th")).toBeNull();
    expect(screen.getByLabelText("全选当前可处理的待确认项")).toBeDisabled();
  });

  it("replaces a completed upload queue with a compact link to pending confirmation", () => {
    const queue = [
      {
        id: "queue-complete",
        file: null,
        fileName: "done.pdf",
        fileSize: 1,
        fileType: "PDF",
        status: "awaiting_confirmation",
        error: "内容建议暂不可用，请人工核对后继续",
        ingestTaskId: "task-secret-a",
        pollAttempts: 0,
      },
    ];
    render(<UploadStepB flow={flowFixture({ localUploadQueue: queue })} />);

    expect(screen.queryByRole("heading", { name: "本次上传队列" })).not.toBeInTheDocument();
    expect(screen.getByText(/本次上传 1 项已完成/)).toBeInTheDocument();
    expect(screen.getByText("内容建议暂不可用，请人工核对后继续")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往待确认入库" })).toHaveAttribute(
      "href",
      "#local-pending-title",
    );
    expect(screen.getByRole("heading", { name: "待确认入库" })).toBeInTheDocument();
  });

  it("prevents browser navigation and delegates the complete DataTransfer", () => {
    const flow = flowFixture({ batchSelection: [] });
    const { container } = render(<UploadStepB flow={flow} />);
    const dropzone = container.querySelector(".upload77-dropzone")!;
    const dataTransfer = { files: [], items: [] } as unknown as DataTransfer;
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });

    dropzone.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(flow.handleDataTransferDrop).toHaveBeenCalledWith(dataTransfer);
    expect(screen.getByText(/PPTX 自动提取/)).toBeInTheDocument();
    expect(screen.getByText(/旧 \.ppt 仅保存，需人工补全/)).toBeInTheDocument();
  });

  it("shows a distinct drag state and persistent 700-item batch feedback", () => {
    const flow = flowFixture({
      batchSelection: [],
      intakeFeedback: {
        kind: "accepted",
        total: 700,
        accepted: 700,
        rejected: 0,
        waitingBatches: 3,
        batchSizes: [200, 200, 200, 100],
        message: "全部已接收，后续批次将自动等待（200 + 200 + 200 + 100）。",
      },
    });
    const { container } = render(<UploadStepB flow={flow} />);
    const dropzone = container.querySelector(".upload77-dropzone")!;

    fireEvent.dragEnter(dropzone);
    expect(dropzone).toHaveAttribute("data-dragging", "true");
    expect(screen.getByText("松开即可逐项检查")).toBeInTheDocument();
    expect(screen.getByLabelText("本次上传接收结果")).toHaveTextContent("检测700");
    expect(screen.getByLabelText("本次上传接收结果")).toHaveTextContent("等待批次3");
    expect(screen.getByLabelText("本次上传接收结果")).toHaveTextContent(
      "批次分布：200 + 200 + 200 + 100",
    );
  });

  it("shows a safe folder fallback notice without rendering an absolute path", () => {
    render(
      <UploadStepB
        flow={flowFixture({
          batchSelection: [],
          folderDropNotice:
            "当前浏览器不支持读取文件夹，已仅添加可直接读取的文件；请使用最新版浏览器。",
        })}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("浏览器不支持读取文件夹");
    expect(document.body).not.toHaveTextContent(/[A-Za-z]:\\|\/Users\/|storage_ref/);
  });

  it("explains that legacy .ppt files are saved but require manual completion", () => {
    render(
      <UploadStepB
        flow={flowFixture({
          hasFile: true,
          fileName: "legacy.ppt",
          fileSize: 12,
          fileType: "PPT",
          flowState: "ready",
          extraction: { status: "unsupported", charCount: null, isDuplicate: false },
        })}
      />,
    );

    expect(screen.getByText(/\.ppt 格式暂不支持自动提取/)).toHaveTextContent(
      "已保存文件，请人工补全内容",
    );
  });

  it("cancels permanent batch rejection without sending a request or clearing selection", () => {
    const flow = flowFixture();
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量拒绝入库（2）" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("2 条待确认任务");
    expect(screen.getByRole("dialog")).toHaveTextContent("不可恢复");
    expect(screen.getByRole("dialog")).not.toHaveTextContent(
      /task-secret|storage_ref|internal:\/\//,
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(flow.handleBatchReject).not.toHaveBeenCalled();
    expect(flow.handleBatchConfirm).not.toHaveBeenCalled();
    expect(flow.batchSelection).toHaveLength(2);
  });

  it("confirms rejection through the delete workflow without calling batch confirmation", () => {
    const flow = flowFixture();
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量拒绝入库（2）" }));
    fireEvent.click(screen.getByRole("button", { name: "确认永久拒绝" }));

    expect(flow.handleBatchReject).toHaveBeenCalledWith(flow.localPendingTasks);
    expect(flow.handleBatchConfirm).not.toHaveBeenCalled();
    expect(document.body).not.toHaveTextContent(/task-secret|原始正文|storage_ref/);
  });

  it("requires one explicit destination before batch confirmation", () => {
    const flow = flowFixture();
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（2）" }));
    const target = screen.getByRole("combobox", { name: "批量入库目标知识库" });
    expect(target).toHaveValue("");
    expect(screen.getByRole("dialog")).toHaveTextContent("取消不会创建资产");

    fireEvent.click(screen.getByRole("button", { name: "确认批量入库" }));
    expect(flow.handleBatchConfirm).not.toHaveBeenCalled();

    fireEvent.change(target, { target: { value: "personal" } });
    fireEvent.click(screen.getByRole("button", { name: "确认批量入库" }));
    expect(flow.handleBatchConfirm).toHaveBeenCalledWith(
      flow.localPendingTasks,
      "personal",
      undefined,
    );
  });

  it("requires each governed item to provide a formed date and receive a server preview", async () => {
    const task = {
      ...pending("governed", "Governed.pdf"),
      target_scope: null,
      naming_parsed_fields: {
        primary_category: "",
        secondary_category: "",
        topic: "",
        subject_or_client: "",
        date: "2026-08-02",
        version: "V1",
        confidentiality_level: "L2",
        ai_access_level: "A2",
        normalized_title: "",
        inferred_fields: [],
        missing_fields: ["date"],
        source_file_name: "Governed.pdf",
        original_naming_compliant: false,
      },
    };
    const flow = flowFixture({ localPendingTasks: [task], batchSelection: [task.id] });
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: task.id,
          submittable: true,
          canonical_name: "【ALPHA-2026-交付件】安全标题_20260803_V1_L2.pdf",
          rule_version: 2,
          fields: { subject: "安全标题" },
          notices: [],
          error_code: null,
          message: null,
        },
      ],
    });
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    const date = await screen.findByLabelText("Governed.pdf 文件形成日期");
    expect(date).toHaveValue("");
    expect(screen.getByRole("button", { name: "确认批量入库" })).toBeDisabled();
    expect(screen.getAllByText(/仍有 1 条需补充形成日期/)).toHaveLength(1);

    fireEvent.change(date, { target: { value: "2026-08-03" } });
    expect(screen.getByText("正在按当前填写内容生成…")).toBeInTheDocument();
    expect(screen.queryByText("请补齐或修改该资料的命名字段")).not.toBeInTheDocument();
    await screen.findByText("【ALPHA-2026-交付件】安全标题_20260803_V1_L2.pdf");
    expect(screen.getByText("可确认")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认批量入库" }));

    expect(flow.handleBatchConfirm).toHaveBeenCalledWith(
      [task],
      "project",
      "project-a",
      {
        [task.id]: {
          category_id: "category-a",
          subject: "安全标题",
          formed_on: "2026-08-03",
          version: "V1",
          applicable_to: "",
          confidentiality_level: "L2",
        },
      },
      { [task.id]: [] },
    );
  });

  it("places a server field diagnostic beside the corresponding input", async () => {
    const task = {
      ...pending("diagnostic", "Diagnostic.pdf"),
      target_scope: null,
      naming_parsed_fields: {
        date: "20210116",
        version: "V1",
        missing_fields: [],
        source_file_name: "Diagnostic.pdf",
      },
    };
    const flow = flowFixture({ localPendingTasks: [task], batchSelection: [task.id] });
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: task.id,
          submittable: false,
          canonical_name: null,
          rule_version: null,
          fields: null,
          notices: [],
          error_code: "naming_version_invalid",
          message: "请填写有效版本，例如 V1 或 V1.1",
        },
      ],
    });
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));
    await screen.findByLabelText("Diagnostic.pdf 文件形成日期");
    fireEvent.click(screen.getByRole("button", { name: "生成或刷新全部预览" }));

    const versionInput = screen.getByLabelText("Diagnostic.pdf 版本");
    const versionField = versionInput.closest("label");
    await waitFor(() => expect(versionField).toHaveTextContent("请填写有效版本，例如 V1 或 V1.1"));
    expect(screen.getByRole("button", { name: "确认批量入库" })).toBeDisabled();
  });

  it("uses a persisted current-rule AI category and keeps it editable", async () => {
    const task = {
      ...pending("ai-category", "交付成果.md"),
      target_scope: null,
      naming_parsed_fields: {
        primary_category: "客户项目",
        secondary_category: "交付成果",
        topic: "年度经营计划",
        subject_or_client: "",
        date: "20210116",
        version: "V1",
        confidentiality_level: "L2",
        ai_access_level: "A2",
        normalized_title: "",
        inferred_fields: ["secondary_category"],
        missing_fields: [],
        source_file_name: "交付成果.md",
        original_naming_compliant: false,
      },
    };
    namingApi.fetchNamingOptions.mockResolvedValueOnce({
      required: true,
      rule_version: 2,
      categories: [
        {
          id: "category-foundation",
          primary: "项目资料",
          secondary: "项目基础信息",
          prefix: "项目资料-项目基础信息",
          default_confidentiality: "L2",
        },
        {
          id: "category-deliverable",
          primary: "项目资料",
          secondary: "交付成果",
          prefix: "项目资料-交付成果",
          default_confidentiality: "L2",
        },
      ],
      default_confidentiality: "L2",
      message: null,
    });
    namingApi.classifyBatchNamingCategories.mockResolvedValueOnce({
      target_label: "项目知识库 / 项目 A",
      candidate_rule_revision: 2,
      candidate_count: 2,
      items: [
        {
          task_id: task.id,
          suggested_category_id: "category-deliverable",
          category_source: "ai_content",
          category_confidence: "high",
          category_reason: "AI 根据正文语义匹配当前目标的目录规则",
          candidate_rule_revision: 2,
          status: "classified",
          retryable: false,
        },
      ],
    });
    const flow = flowFixture({ localPendingTasks: [task], batchSelection: [task.id] });
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    const category = await screen.findByRole("combobox", { name: "交付成果.md 目录类别" });
    expect(category).toHaveValue("category-deliverable");
    expect(screen.getByText("AI 内容建议（高置信度）")).toBeInTheDocument();

    fireEvent.change(category, { target: { value: "category-foundation" } });
    expect(category).toHaveValue("category-foundation");
    expect(screen.getByText("人工已选择")).toBeInTheDocument();
  });

  it("keeps a missing-category item in the manual filter while it is edited", async () => {
    const task = {
      ...pending("manual-category", "待分类资料.md"),
      target_scope: null,
      naming_parsed_fields: {
        date: "20260803",
        version: "V1",
        missing_fields: ["secondary_category"],
        inferred_fields: [],
        source_file_name: "待分类资料.md",
      },
    };
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: task.id,
          submittable: true,
          canonical_name: "【ALPHA-2026-交付件】安全标题_20260803_V1_L2.md",
          rule_version: 2,
          fields: { subject: "安全标题" },
          notices: [],
          error_code: null,
          message: null,
        },
      ],
    });
    const flow = flowFixture({ localPendingTasks: [task], batchSelection: [task.id] });
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    await screen.findByLabelText("待分类资料.md 目录类别");
    expect(screen.getByRole("button", { name: "需人工补齐（1）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "异常/重复（0）" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "需人工补齐（1）" }));
    fireEvent.change(screen.getByLabelText("待分类资料.md 目录类别"), {
      target: { value: "category-a" },
    });

    await screen.findByText("【ALPHA-2026-交付件】安全标题_20260803_V1_L2.md");
    expect(screen.getByLabelText("待分类资料.md 目录类别")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "需人工补齐（1）" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("confirms one governed row without closing the batch review", async () => {
    const task = {
      ...pending("single-confirm", "单条确认.md"),
      target_scope: null,
      naming_parsed_fields: {
        primary_category: "项目资料",
        secondary_category: "交付件",
        date: "20260803",
        version: "V1",
        missing_fields: [],
        inferred_fields: [],
        source_file_name: "单条确认.md",
      },
      suggested_version: "V1",
      version_source: "source_filename",
      suggested_confidentiality_level: "L2",
      confidentiality_source: "ai_content",
      confidentiality_confidence: "high",
    };
    namingApi.previewBatchIngestNaming.mockResolvedValue({
      items: [
        {
          task_id: task.id,
          submittable: true,
          canonical_name: "【ALPHA-2026-交付件】安全标题_20260803_V1_L2.md",
          rule_version: 2,
          fields: { subject: "安全标题" },
          notices: [
            {
              code: "exact_duplicate",
              kind: "exact",
              message: "已存在相同文件，请确认是否仍需独立入库",
            },
          ],
          error_code: null,
          message: null,
        },
      ],
    });
    const handleSingleBatchConfirm = vi
      .fn()
      .mockResolvedValue({ succeededIds: [task.id], failedIds: [] });
    const flow = flowFixture({
      localPendingTasks: [task],
      batchSelection: [task.id],
      handleSingleBatchConfirm,
    });
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));
    await screen.findByText("【ALPHA-2026-交付件】安全标题_20260803_V1_L2.md");
    const singleConfirm = screen.getByRole("button", { name: "确认入库 单条确认.md" });
    expect(singleConfirm).toBeEnabled();

    fireEvent.change(screen.getByLabelText("单条确认.md 主题"), {
      target: { value: "编辑后的主题" },
    });
    expect(singleConfirm).toBeDisabled();
    expect(screen.getByRole("button", { name: "仍然确认批量入库" })).toBeDisabled();
    await waitFor(() => expect(namingApi.previewBatchIngestNaming).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(singleConfirm).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "确认入库 单条确认.md" }));
    const dialogs = screen.getAllByRole("dialog");
    const warningDialog = dialogs[dialogs.length - 1];
    expect(warningDialog).toHaveTextContent("已存在相同文件");
    expect(warningDialog).toHaveTextContent("不会覆盖已有资产");
    fireEvent.click(within(warningDialog).getByRole("button", { name: "仍然确认入库" }));

    await waitFor(() =>
      expect(handleSingleBatchConfirm).toHaveBeenCalledWith(
        task,
        "project",
        "project-a",
        expect.objectContaining({
          category_id: "category-a",
          subject: "安全标题",
          formed_on: "2026-08-03",
          version: "V1",
          confidentiality_level: "L2",
        }),
        ["exact_duplicate"],
      ),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("逐条核对");
  });

  it("keeps only the latest dynamic preview when responses arrive out of order", async () => {
    const task = {
      ...pending("preview-race", "竞态资料.md"),
      target_scope: null,
      naming_parsed_fields: {
        date: "20260803",
        version: "V1",
        missing_fields: ["secondary_category"],
        inferred_fields: [],
        source_file_name: "竞态资料.md",
      },
    };
    const resolvers: Array<(value: unknown) => void> = [];
    namingApi.previewBatchIngestNaming.mockImplementation(
      () => new Promise((resolve) => resolvers.push(resolve)),
    );
    render(
      <UploadStepB flow={flowFixture({ localPendingTasks: [task], batchSelection: [task.id] })} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));
    const category = await screen.findByLabelText("竞态资料.md 目录类别");
    fireEvent.change(category, { target: { value: "category-a" } });
    await waitFor(() => expect(resolvers).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("竞态资料.md 主题"), {
      target: { value: "最后主题" },
    });
    await waitFor(() => expect(resolvers).toHaveLength(2));

    await act(async () => {
      resolvers[1]({
        items: [
          {
            task_id: task.id,
            submittable: true,
            canonical_name: "【ALPHA-2026-交付件】最后主题_20260803_V1_L2.md",
            rule_version: 2,
            fields: { subject: "最后主题" },
            notices: [],
            error_code: null,
            message: null,
          },
        ],
      });
    });
    await screen.findByText("【ALPHA-2026-交付件】最后主题_20260803_V1_L2.md");
    await act(async () => {
      resolvers[0]({
        items: [
          {
            task_id: task.id,
            submittable: true,
            canonical_name: "【ALPHA-2026-交付件】旧主题_20260803_V1_L2.md",
            rule_version: 2,
            fields: { subject: "旧主题" },
            notices: [],
            error_code: null,
            message: null,
          },
        ],
      });
    });
    await waitFor(() =>
      expect(
        screen.getByText("【ALPHA-2026-交付件】最后主题_20260803_V1_L2.md"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("【ALPHA-2026-交付件】旧主题_20260803_V1_L2.md")).toBeNull();
  });

  it("renders 93 long-name review rows inside a bounded scroll container", async () => {
    const longName = `${"超长项目资料文件名".repeat(12)}.pdf`;
    const tasks = Array.from({ length: 93 }, (_, index) => ({
      ...pending(`bulk-${index}`, `${index}-${longName}`),
      target_scope: null,
      naming_parsed_fields:
        index === 0
          ? {
              primary_category: "",
              secondary_category: "",
              topic: "",
              subject_or_client: "",
              date: "20260802",
              version: "V1",
              confidentiality_level: "L2",
              ai_access_level: "A2",
              normalized_title: "",
              inferred_fields: [],
              missing_fields: [],
              source_file_name: `${index}-${longName}`,
              original_naming_compliant: true,
            }
          : null,
    }));
    const flow = flowFixture({
      localPendingTasks: tasks,
      batchSelection: tasks.map((task) => task.id),
    });
    render(<UploadStepB flow={flow} />);
    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（93）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    await waitFor(() => {
      expect(document.querySelectorAll(".upload77-batch-naming-row")).toHaveLength(93);
    });
    expect(document.querySelector(".upload77-batch-naming-scroll")).toBeInTheDocument();
    expect(document.querySelector(".upload77-batch-naming-dialog")).toBeInTheDocument();
    expect(document.querySelectorAll<HTMLInputElement>('input[type="date"]')[0]).toHaveValue(
      "2026-08-02",
    );
    expect(screen.getAllByText(/已核对 0\/93 条/).length).toBeGreaterThan(0);
  });

  it("selects all actionable rows, exposes half-selected state, and excludes disabled rows", () => {
    const first = pending("first", "First.pdf");
    const second = pending("second", "Second.pdf");
    const disabled = {
      ...pending("disabled", "Disabled.pdf"),
      status: "processing",
      can_batch_confirm: false,
      can_batch_reject: false,
    };
    const flow = flowFixture({
      batchSelection: ["first", "disabled"],
      localPendingTasks: [first, second, disabled],
    });
    render(<UploadStepB flow={flow} />);

    const selectAll = screen.getByRole("checkbox", {
      name: "全选当前可处理的待确认项",
    }) as HTMLInputElement;
    expect(selectAll).not.toBeChecked();
    expect(selectAll.indeterminate).toBe(true);
    expect(screen.getByRole("checkbox", { name: "选择 Disabled.pdf" })).toBeDisabled();

    fireEvent.click(selectAll);
    expect(flow.setBatchTasksSelected).toHaveBeenCalledWith(["first", "second"], true);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（1）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "personal" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认批量入库" }));
    expect(flow.handleBatchConfirm).toHaveBeenCalledWith([first], "personal", undefined);

    fireEvent.click(screen.getByRole("button", { name: "批量拒绝入库（1）" }));
    fireEvent.click(screen.getByRole("button", { name: "确认永久拒绝" }));
    expect(flow.handleBatchReject).toHaveBeenCalledWith([first]);
  });

  it("keeps reject-only history selectable without exposing it to batch confirmation", () => {
    const rejected = {
      ...pending("rejected", "Rejected.md"),
      status: "rejected",
      can_batch_confirm: false,
      can_batch_reject: true,
    };
    const flow = flowFixture({
      batchSelection: ["rejected"],
      localPendingTasks: [rejected],
    });
    render(<UploadStepB flow={flow} />);

    expect(screen.getByLabelText("选择 Rejected.md")).toBeEnabled();
    expect(screen.queryByRole("button", { name: /批量确认入库/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "批量拒绝入库（1）" }));
    fireEvent.click(screen.getByRole("button", { name: "确认永久拒绝" }));
    expect(flow.handleBatchReject).toHaveBeenCalledWith([rejected]);
    expect(flow.handleBatchConfirm).not.toHaveBeenCalled();
  });

  it("renders a non-retryable rejection error outside the checkbox column", () => {
    const task = pending("conflict", "Conflict.md");
    const message = "已入库：该任务已形成知识资产，不能永久删除。";
    const flow = flowFixture({
      localPendingTasks: [task],
      batchStatus: { [task.id]: "failed" },
      batchErrors: { [task.id]: message },
      batchRejectRetryability: { [task.id]: false },
    });
    render(<UploadStepB flow={flow} />);

    const checkboxCell = screen.getByLabelText("选择 Conflict.md").closest("td");
    const error = screen.getByText(message);
    expect(checkboxCell).not.toContainElement(error);
    expect(error.closest("td")).toHaveClass("upload77-batch-result");
    expect(screen.getByLabelText("选择 Conflict.md")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
  });

  it("shows real per-file states without inventing percentage progress", () => {
    const queue = [
      {
        id: "queue-a",
        file: new File(["a"], "a.pdf"),
        fileName: "folder/a.pdf",
        fileSize: 1,
        fileType: "PDF",
        status: "uploading",
        error: null,
        ingestTaskId: null,
        pollAttempts: 0,
      },
      {
        id: "queue-b",
        file: new File(["b"], "b.pdf"),
        fileName: "folder/b.pdf",
        fileSize: 1,
        fileType: "PDF",
        status: "failed",
        error: "上传失败，请重试",
        ingestTaskId: null,
        pollAttempts: 0,
      },
    ];
    render(<UploadStepB flow={flowFixture({ batchSelection: [], localUploadQueue: queue })} />);

    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText("上传中")).toBeInTheDocument();
    expect(screen.getByText("上传失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "移除" })).toBeInTheDocument();
  });
});
