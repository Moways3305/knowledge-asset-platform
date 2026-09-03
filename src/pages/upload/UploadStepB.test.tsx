import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import UploadStepB from "./UploadStepB";
import type { UploadFlow } from "./useUploadFlow";

const namingApi = vi.hoisted(() => ({
  fetchNamingOptions: vi.fn(),
  previewIngestNaming: vi.fn(),
  previewBatchIngestNaming: vi.fn(),
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
    namingApi.previewIngestNaming.mockReset().mockResolvedValue({
      required: false,
      canonical_name: null,
      rule_version: null,
      fields: null,
      notices: [],
      message: "个人资料不强制规范命名",
      duplicate: {
        duplicate_state: "none",
        match_type: "none",
        match_count: 0,
        preferred_candidate: null,
        same_batch_group_id: null,
        same_batch_first_ordinal: null,
        default_selected: true,
        decision: null,
      },
    });
    namingApi.fetchNamingOptions.mockReset();
    namingApi.previewBatchIngestNaming.mockReset();
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
      directories: [
        {
          directory_key: "project.deliverables",
          scope: "project",
          display_name: "03 交付成果",
          sort_order: 30,
          enabled: true,
        },
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
      ],
      default_confidentiality: "L2",
      message: null,
    });
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

  it("keeps completed queue items visible alongside the pending-confirmation link", () => {
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

    expect(screen.getByRole("heading", { name: "本次上传队列" })).toBeInTheDocument();
    expect(screen.getByText(/本次上传 1 项派生处理已完成/)).toBeInTheDocument();
    expect(screen.getByText(/规范文本已生成；2 项待人工确认，尚未进入检索/)).toBeInTheDocument();
    expect(screen.getByText("done.pdf")).toBeInTheDocument();
    expect(
      screen.queryByText("本文件暂未完成处理，请按操作重试或重新选择原文件"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往待确认入库" })).toHaveAttribute(
      "href",
      "#local-pending-title",
    );
    expect(screen.getByRole("heading", { name: "待确认入库" })).toBeInTheDocument();
  });

  it("paginates a large queue without hiding the batch totals or failed-file recovery", async () => {
    const queue = Array.from({ length: 10 }, (_, index) => ({
      id: `queue-${index}`,
      file: null,
      fileName: `file-${index}.pdf`,
      fileSize: 1024,
      fileType: "PDF",
      status: index === 9 ? ("failed" as const) : ("processing" as const),
      error: index === 9 ? "upload timeout" : null,
      ingestTaskId: null,
      pollAttempts: 0,
      retryable: index === 9,
    }));
    const retryLocalUpload = vi.fn().mockResolvedValue(undefined);
    render(
      <UploadStepB
        flow={flowFixture({
          localUploadQueue: queue,
          retryLocalUpload,
          uploadSession: {
            total_files: 10,
            completed_files: 0,
            processing_files: 9,
            waiting_files: 0,
            failed_files: 1,
            uploaded_files: 10,
            uploaded_batches: 1,
            total_batches: 1,
            current_batch_number: 1,
          },
        })}
      />,
    );

    expect(screen.getByLabelText("上传会话进度")).toHaveTextContent("总数10");
    expect(screen.getByText("显示 1–8 / 10")).toBeInTheDocument();
    expect(screen.queryByText("file-9.pdf")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByText("file-9.pdf")).toBeInTheDocument();
    expect(screen.getByText("处理超时，稍后可重试")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试可恢复失败项" }));
    await waitFor(() => expect(retryLocalUpload).toHaveBeenCalledWith("queue-9"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "重试可恢复失败项" })).toBeEnabled(),
    );
  });

  it("retries failed upload-session items serially", async () => {
    const releases: Array<() => void> = [];
    const retryLocalUpload = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          releases.push(resolve);
        }),
    );
    const queue = Array.from({ length: 3 }, (_, index) => ({
      id: `serial-retry-${index}`,
      file: null,
      fileName: `failed-${index}.pdf`,
      fileSize: 1024,
      fileType: "PDF",
      status: "failed" as const,
      error: "传输失败",
      ingestTaskId: null,
      pollAttempts: 0,
      retryable: true,
    }));
    render(<UploadStepB flow={flowFixture({ localUploadQueue: queue, retryLocalUpload })} />);

    fireEvent.click(screen.getByRole("button", { name: "重试可恢复失败项" }));
    expect(retryLocalUpload).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "正在重试失败项…" })).toBeDisabled();

    await act(async () => releases[0]());
    await waitFor(() => expect(retryLocalUpload).toHaveBeenCalledTimes(2));
    await act(async () => releases[1]());
    await waitFor(() => expect(retryLocalUpload).toHaveBeenCalledTimes(3));
    await act(async () => releases[2]());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "重试可恢复失败项" })).toBeEnabled(),
    );
  });

  it("disables item and batch removal while a single upload retry is running", async () => {
    let releaseRetry!: () => void;
    const retryLocalUpload = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          releaseRetry = resolve;
        }),
    );
    const removeLocalUpload = vi.fn();
    const removeFailedLocalUploads = vi.fn();
    render(
      <UploadStepB
        flow={flowFixture({
          localUploadQueue: [
            {
              id: "single-retry",
              file: null,
              fileName: "failed.pdf",
              fileSize: 1024,
              fileType: "PDF",
              status: "failed",
              error: "传输失败",
              ingestTaskId: null,
              pollAttempts: 0,
              retryable: true,
            },
          ],
          retryLocalUpload,
          removeLocalUpload,
          removeFailedLocalUploads,
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重试处理" }));

    expect(screen.getByRole("button", { name: "正在重试…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "移除" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "清理全部失败项" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "移除" }));
    fireEvent.click(screen.getByRole("button", { name: "清理全部失败项" }));
    expect(removeLocalUpload).not.toHaveBeenCalled();
    expect(removeFailedLocalUploads).not.toHaveBeenCalled();

    await act(async () => releaseRetry());
    await waitFor(() => expect(screen.getByRole("button", { name: "移除" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "移除" }));
    expect(removeLocalUpload).toHaveBeenCalledWith("single-retry");
  });

  it("recognizes Chinese protected-file errors and keeps OCR complexity distinct from confidence", () => {
    const failures = [
      {
        id: "queue-protected",
        fileName: "protected.pdf",
        error: "文件已加密，需要密码",
      },
      {
        id: "queue-complex",
        fileName: "complex.pdf",
        error: "文件版面过于复杂",
        processingStage: "ocr_too_complex" as const,
      },
      {
        id: "queue-confidence",
        fileName: "low-confidence.pdf",
        error: "OCR 置信度不足",
        processingStage: "ocr_failed" as const,
      },
    ].map((item) => ({
      file: null,
      fileSize: 1024,
      fileType: "PDF",
      status: "failed" as const,
      ingestTaskId: null,
      pollAttempts: 0,
      retryable: true,
      ...item,
    }));

    render(<UploadStepB flow={flowFixture({ localUploadQueue: failures })} />);

    expect(screen.getByText("文件受密码保护，请解锁后重新上传")).toBeInTheDocument();
    expect(screen.getByText("文件页数、图像或版面过于复杂，请拆分文件后重试")).toBeInTheDocument();
    expect(
      screen.getByText("OCR 识别置信度不足，请上传更清晰的文件或改为人工校对"),
    ).toBeInTheDocument();
  });

  it("maps backend extraction error codes to stable actionable failure reasons", () => {
    const failures = [
      ["format", "extraction_format_mismatch", "文件已加密"],
      ["structure", "extraction_structure_limit", "格式不支持"],
      ["archive", "extraction_archive_limit", "文件无法解析"],
      ["parse", "file_parse_failed", "文件过于复杂"],
    ].map(([id, errorCode, error]) => ({
      id,
      file: null,
      fileName: `${id}.pdf`,
      fileSize: 1024,
      fileType: "PDF",
      status: "failed" as const,
      error,
      errorCode,
      ingestTaskId: null,
      pollAttempts: 0,
      retryable: true,
    }));

    render(<UploadStepB flow={flowFixture({ localUploadQueue: failures })} />);

    expect(screen.getByText("文件格式不符合处理要求，请检查后重新上传")).toBeInTheDocument();
    expect(screen.getAllByText("文件页数、图像或版面过于复杂，请拆分文件后重试")).toHaveLength(2);
    expect(screen.getByText("文件可能损坏或无法解析，请确认扩展名后重新上传")).toBeInTheDocument();
  });

  it("shows canonical Markdown generation as a distinct asynchronous stage", () => {
    render(
      <UploadStepB
        flow={flowFixture({
          batchSelection: [],
          localUploadQueue: [
            {
              id: "queue-markdown",
              file: null,
              fileName: "methodology.pdf",
              fileSize: 1024,
              fileType: "PDF",
              status: "processing",
              error: null,
              ingestTaskId: "task-markdown",
              pollAttempts: 1,
              processingStage: "canonical_markdown_generation",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("正在生成 Markdown")).toBeInTheDocument();
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

  it("requires one explicit destination and a formal personal directory before confirmation", async () => {
    const flow = flowFixture();
    render(<UploadStepB flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（2）" }));
    const target = screen.getByRole("combobox", { name: "批量入库目标知识库" });
    expect(target).toHaveValue("");
    expect(screen.getByRole("dialog")).toHaveTextContent("取消不会创建资产");

    fireEvent.click(screen.getByRole("button", { name: "确认已选择的 2 项入库" }));
    expect(flow.handleBatchConfirm).not.toHaveBeenCalled();

    fireEvent.change(target, { target: { value: "personal" } });
    const directory = await screen.findByRole("combobox", { name: "本批个人目录" });
    expect(directory).not.toHaveTextContent("04 待处理");
    expect(screen.getByRole("button", { name: "下一步：核对入库" })).toBeDisabled();
    fireEvent.change(directory, { target: { value: "personal.learning_notes" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对入库" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认已选择的 2 项入库" }));
    expect(flow.handleBatchConfirm).toHaveBeenCalledWith(
      flow.localPendingTasks,
      "personal",
      undefined,
      undefined,
      expect.any(Object),
      true,
      expect.any(Function),
      undefined,
      {
        "task-secret-a": "personal.learning_notes",
        "task-secret-b": "personal.learning_notes",
      },
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
    expect(screen.getByRole("button", { name: "确认已选择的 1 项入库" })).toBeDisabled();
    expect(screen.getAllByText(/仍有 1 条需补充形成日期/)).toHaveLength(1);

    fireEvent.change(date, { target: { value: "2026-08-03" } });
    expect(screen.getByText("正在按当前填写内容生成…")).toBeInTheDocument();
    expect(screen.queryByText("请补齐或修改该资料的命名字段")).not.toBeInTheDocument();
    await screen.findByText("【ALPHA-2026-交付件】安全标题_20260803_V1_L2.pdf");
    expect(screen.getByText("可确认")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认已选择的 1 项入库" }));

    expect(flow.handleBatchConfirm).toHaveBeenCalledWith(
      [task],
      "project",
      "project-a",
      {
        [task.id]: {
          directory_key: "project.deliverables",
          subject: "安全标题",
          formed_on: "2026-08-03",
          version: "V1",
          applicable_to: "",
          confidentiality_level: "L2",
        },
      },
      { [task.id]: [] },
      true,
      expect.any(Function),
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
    expect(screen.getByRole("button", { name: "确认已选择的 1 项入库" })).toBeDisabled();
  });

  it("uses a formal directory directly and keeps it editable", async () => {
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
      directories: [
        {
          directory_key: "project.basic_information",
          scope: "project",
          display_name: "01 项目基础信息",
          sort_order: 10,
          enabled: true,
        },
        {
          directory_key: "project.deliverables",
          scope: "project",
          display_name: "03 交付成果",
          sort_order: 30,
          enabled: true,
        },
      ],
      default_confidentiality: "L2",
      message: null,
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

    const directory = await screen.findByRole("combobox", { name: "交付成果.md 正式目录" });
    expect(directory).toHaveValue("project.basic_information");
    fireEvent.change(directory, { target: { value: "project.deliverables" } });
    expect(directory).toHaveValue("project.deliverables");
  });

  it("keeps an incomplete item in the manual filter while its formal directory is visible", async () => {
    const task = {
      ...pending("manual-category", "待分类资料.md"),
      target_scope: null,
      naming_parsed_fields: {
        date: "",
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

    await screen.findByLabelText("待分类资料.md 正式目录");
    expect(screen.getByRole("button", { name: "需人工补齐（1）" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "异常/重复（0）" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "需人工补齐（1）" }));
    fireEvent.change(screen.getByLabelText("待分类资料.md 文件形成日期"), {
      target: { value: "2026-08-03" },
    });

    await screen.findByText("【ALPHA-2026-交付件】安全标题_20260803_V1_L2.md");
    expect(screen.getByLabelText("待分类资料.md 正式目录")).toBeInTheDocument();
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
    const handleSingleBatchConfirm = vi.fn().mockResolvedValue({
      succeededIds: [task.id],
      failedIds: [],
      resultAssetIds: { [task.id]: "asset-single-confirm" },
    });
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
    expect(screen.getByRole("button", { name: "仍然确认已选择的 1 项入库" })).toBeDisabled();
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
          directory_key: "project.deliverables",
          subject: "安全标题",
          formed_on: "2026-08-03",
          version: "V1",
          confidentiality_level: "L2",
        }),
        ["exact_duplicate"],
      ),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("逐条核对");
    expect(screen.getByRole("link", { name: "查看知识资产卡片：安全标题" })).toHaveAttribute(
      "href",
      "/knowledge/asset-single-confirm",
    );
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
    await screen.findByLabelText("竞态资料.md 正式目录");
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

  it("keeps controls outside the scroll region with 213 long-name review rows", async () => {
    const longName = `${"超长项目资料文件名".repeat(12)}.pdf`;
    const tasks = Array.from({ length: 213 }, (_, index) => ({
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
    fireEvent.click(screen.getByRole("button", { name: "批量确认入库（213）" }));
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标知识库" }), {
      target: { value: "project" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "批量入库目标项目" }), {
      target: { value: "project-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对命名" }));

    await waitFor(() => {
      expect(document.querySelectorAll(".upload77-batch-naming-row")).toHaveLength(213);
    });
    const dialog = screen.getByRole("dialog", { name: "逐条核对 213 项规范命名" });
    const scrollRegion = dialog.querySelector(".upload77-batch-naming-scroll");
    expect(scrollRegion).toBeInTheDocument();
    expect(scrollRegion).not.toContainElement(
      within(dialog).getByRole("button", { name: "关闭批量命名核对" }),
    );
    expect(scrollRegion).not.toContainElement(
      within(dialog).getByRole("button", { name: "确认已选择的 213 项入库" }),
    );
    expect(scrollRegion).not.toContainElement(within(dialog).getByRole("button", { name: "取消" }));
    expect(document.querySelectorAll<HTMLInputElement>('input[type="date"]')[0]).toHaveValue(
      "2026-08-02",
    );
    expect(screen.getAllByText(/已核对 0\/213 条/).length).toBeGreaterThan(0);
  });

  it("selects all actionable rows, exposes half-selected state, and excludes disabled rows", async () => {
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
    const directory = await screen.findByRole("combobox", { name: "本批个人目录" });
    fireEvent.change(directory, { target: { value: "personal.learning_notes" } });
    fireEvent.click(screen.getByRole("button", { name: "下一步：核对入库" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认已选择的 1 项入库" }));
    expect(flow.handleBatchConfirm).toHaveBeenCalledWith(
      [first],
      "personal",
      undefined,
      undefined,
      expect.any(Object),
      true,
      expect.any(Function),
      undefined,
      { first: "personal.learning_notes" },
    );

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

  it("shows the real transport batch progress for the session and each file", () => {
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
        transportBatchNumber: 4,
      },
    ];
    const uploadSession = {
      id: "session-a",
      status: "uploading",
      total_files: 196,
      completed_files: 30,
      processing_files: 8,
      waiting_files: 158,
      failed_files: 0,
      current_batch_number: 1,
      total_batches: 20,
      uploaded_files: 38,
      uploaded_batches: 4,
      upload_completed: false,
      created_at: "2026-08-24T00:00:00Z",
      updated_at: "2026-08-24T00:00:00Z",
      items: [],
    };

    render(
      <UploadStepB
        flow={flowFixture({ batchSelection: [], localUploadQueue: queue, uploadSession })}
      />,
    );

    expect(screen.getByText("已上传 38/196，第 4/20 批")).toBeInTheDocument();
    expect(screen.getByText("传输第 4 批")).toBeInTheDocument();
    expect(screen.queryByText(/每批最多\s*200/)).not.toBeInTheDocument();
  });
});
