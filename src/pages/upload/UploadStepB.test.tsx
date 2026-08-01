import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import UploadStepB from "./UploadStepB";
import type { UploadFlow } from "./useUploadFlow";

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
    toggleBatchTask: vi.fn(),
    setBatchTasksSelected: vi.fn(),
    handleBatchConfirm: vi.fn(),
    handleBatchReject: vi.fn(),
    projects: [{ projectId: "project-a", projectName: "项目 A" }],
    canUseCompanyTarget: false,
    ...overrides,
  } as unknown as UploadFlow;
}

describe("UploadStepB folder drop and batch rejection", () => {
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
