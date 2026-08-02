import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ChangeEvent } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useUploadFlow } from "./useUploadFlow";
import { useIngestConfirmation } from "./useIngestConfirmation";
import { ApiError } from "../../api/http";
import type { ModelSelectionState } from "../../hooks/useModelSelection";
import type {
  IngestAiResultDTO,
  IngestTaskStatusDTO,
  PendingIngestItemDTO,
} from "../../types/ingest";

// 可变的模型选择状态（驱动「自动选中默认 / 缺默认禁用提交 / 切换后 payload 带 ref」）。
const modelState: { current: ModelSelectionState } = {
  current: {
    loading: false,
    loaded: true,
    weknoraDisabled: false,
    defaultMissing: false,
    embeddingOptions: [],
    rerankOptions: [],
    embeddingRef: "ref_emb_default",
    rerankRef: "ref_rer_default",
    setEmbeddingRef: vi.fn(),
    setRerankRef: vi.fn(),
    reload: vi.fn(),
    blockSubmit: false,
  },
};
vi.mock("../../hooks/useModelSelection", () => ({
  useModelSelection: () => modelState.current,
}));

const auth = vi.hoisted(() => ({ fetchAuthMe: vi.fn() }));
vi.mock("../../api/auth", () => auth);

const ingest = vi.hoisted(() => ({
  createIngestUpload: vi.fn(),
  createUploadSession: undefined,
  fetchUploadSessions: undefined,
  fetchUploadSession: undefined,
  retryUploadSessionItem: undefined,
  removeUploadSessionItem: undefined,
  removeFailedUploadSessionItems: undefined,
  fetchIngestAiResult: vi.fn(),
  fetchIngestTaskStatus: vi.fn(),
  fetchPendingIngestTasks: vi.fn(),
  confirmIngest: vi.fn(),
  bulkConfirmIngest: vi.fn(),
  deletePendingTask: vi.fn(),
}));
vi.mock("../../api/ingest", () => ingest);

const namingApi = vi.hoisted(() => ({
  fetchNamingOptions: vi.fn(),
  previewIngestNaming: vi.fn(),
}));
vi.mock("../../api/naming", () => namingApi);

vi.mock("./uploadConstants", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./uploadConstants")>();
  return { ...actual, POLL_INTERVAL_MS: 10, POLL_MAX_ATTEMPTS: 3 };
});

const readyAiResult: IngestAiResultDTO = {
  ingest_task_id: "t1",
  status: "ready",
  suggested_title: "渠道转型方法论",
  suggested_one_liner: "一句话",
  suggested_summary: "详细摘要内容",
  summary: "详细摘要内容",
  summary_status: "generated",
  generation_model_ref: "ref_generation_default",
  suggested_key_points: ["要点一"],
  suggested_tags: ["渠道"],
  llm_provider: "external",
  llm_model: "content-model",
  content_processing_status: "llm",
  desensitization_status: "applied",
  desensitization_counts: {},
  desensitization_message: null,
  suggested_asset_type: "methodology",
  suggested_confidentiality_level: "L2",
  suggested_ai_access_level: "A2",
  suggested_phase_key: "行动辅导",
  confidence: 0.9,
  suggestion_generation_status: "generated",
  suggestion_generation_reason: "已提取正文并生成建议，请人工核对",
  naming_compliant: true,
  naming_parsed_fields: null,
  naming_anomalies: [],
  extraction_status: "extracted",
  extracted_text_preview: null,
  extracted_char_count: 100,
  error_type: null,
  error_message: null,
  is_possible_duplicate: false,
  duplicate_of_task_id: null,
  duplicate_of_asset_id: null,
};

function taskStatus(
  taskId: string,
  stage: IngestTaskStatusDTO["stage"] = "awaiting_confirmation",
  status: IngestTaskStatusDTO["status"] = "action_required",
): IngestTaskStatusDTO {
  return {
    task_id: taskId,
    stage,
    status,
    updated_at: null,
    retryable: status === "failed",
    next_action: null,
    error: null,
    result_asset_id: null,
    review_id: null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

type TestFileSystemEntry =
  | {
      isFile: true;
      isDirectory: false;
      name: string;
      file: (success: (file: File) => void, failure?: () => void) => void;
    }
  | {
      isFile: false;
      isDirectory: true;
      name: string;
      createReader: () => {
        readEntries: (
          success: (entries: TestFileSystemEntry[]) => void,
          failure?: () => void,
        ) => void;
      };
    };

function droppedFile(file: File, options?: { unreadable?: boolean }): TestFileSystemEntry {
  return {
    isFile: true,
    isDirectory: false,
    name: file.name,
    file: (success, failure) => {
      if (options?.unreadable) failure?.();
      else success(file);
    },
  };
}

function droppedDirectory(
  name: string,
  entries: TestFileSystemEntry[],
  options?: { unreadable?: boolean },
): TestFileSystemEntry {
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => {
      let delivered = false;
      return {
        readEntries: (success, failure) => {
          if (options?.unreadable) {
            failure?.();
            return;
          }
          if (delivered) success([]);
          else {
            delivered = true;
            success(entries);
          }
        },
      };
    },
  };
}

function folderDataTransfer(entries: TestFileSystemEntry[]): DataTransfer {
  return {
    items: entries.map((entry) => ({
      webkitGetAsEntry: () => entry,
      getAsFile: () => null,
    })),
    files: [],
  } as unknown as DataTransfer;
}

function pendingTask(id: string, fileName: string): PendingIngestItemDTO {
  return {
    id,
    source: "path_a_wecom",
    status: "pending_confirmation",
    source_file_name: fileName,
    target_scope: "personal",
    target_project_id: null,
    can_batch_confirm: true,
    can_batch_reject: true,
    extraction_status: "extracted",
    error_type: null,
    error_message: null,
    suggested_title: null,
    suggested_one_liner: null,
    naming_parsed_fields: null,
    confidence: null,
    suggestion_generation_status: "needs_correction",
    suggestion_generation_reason: "历史任务信息不足，请人工核对",
    result_asset_id: null,
    created_at: null,
    updated_at: null,
  };
}

async function driveToReady(result: { current: ReturnType<typeof useUploadFlow> }) {
  await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
  await act(async () => {
    await result.current.handleSelectPendingTask({
      ...pendingTask("t1", "doc.pptx"),
      source: "path_b_upload",
    });
  });
  await waitFor(() => expect(result.current.flowState).toBe("ready"));
}

describe("useUploadFlow model selection (PBC-38)", () => {
  beforeEach(() => {
    auth.fetchAuthMe.mockReset().mockResolvedValue({ projects: [] });
    ingest.createIngestUpload.mockReset().mockResolvedValue({ ingest_task_id: "t1" });
    ingest.fetchIngestAiResult.mockReset().mockResolvedValue(readyAiResult);
    ingest.fetchIngestTaskStatus
      .mockReset()
      .mockImplementation((taskId: string) => Promise.resolve(taskStatus(taskId)));
    ingest.fetchPendingIngestTasks.mockReset().mockResolvedValue([]);
    namingApi.fetchNamingOptions.mockReset().mockResolvedValue({
      required: false,
      rule_version: null,
      categories: [],
      default_confidentiality: null,
      message: null,
    });
    namingApi.previewIngestNaming.mockReset();
    ingest.confirmIngest.mockReset().mockResolvedValue({
      task_id: "t1",
      status: "completed",
      result_asset_id: "a1",
      review_id: null,
      index_status: "indexed",
    });
    ingest.bulkConfirmIngest
      .mockReset()
      .mockImplementation((input: { items: Array<{ taskId: string }> }) =>
        Promise.resolve({
          operation_id: "bulk-1",
          status: "completed",
          execution_mode: "synchronous",
          submitted: input.items.length,
          succeeded: input.items.length,
          skipped: 0,
          failed: 0,
          items: input.items.map((item) => ({
            item_id: item.taskId,
            status: "succeeded",
            reason_code: null,
            message: null,
          })),
        }),
      );
    ingest.deletePendingTask.mockReset().mockResolvedValue(undefined);
    modelState.current = {
      ...modelState.current,
      blockSubmit: false,
      embeddingRef: "ref_emb_default",
      rerankRef: "ref_rer_default",
    };
  });

  it("fails closed when a project naming policy cannot be loaded", async () => {
    namingApi.fetchNamingOptions.mockRejectedValue(new Error("policy unavailable"));
    const { result } = renderHook(() => useUploadFlow());
    await driveToReady(result);

    act(() => {
      result.current.setTargetLibrary("project");
      result.current.setTargetProjectId("00000000-0000-0000-0000-0000000000b1");
    });

    await waitFor(() => expect(result.current.namingPreviewError).toBeTruthy());
    expect(result.current.canSubmit).toBe(false);
  });

  it("默认模型存在时可提交，confirm payload 携带选中的 model_ref", async () => {
    const { result } = renderHook(() => useUploadFlow());
    await driveToReady(result);
    expect(result.current.canSubmit).toBe(true);

    await act(async () => {
      await result.current.handleSubmit();
    });
    expect(ingest.confirmIngest).toHaveBeenCalledTimes(1);
    const payload = ingest.confirmIngest.mock.calls[0][1];
    expect(payload.embedding_model_ref).toBe("ref_emb_default");
    expect(payload.rerank_model_ref).toBe("ref_rer_default");
    // 绝不发送真实 model_id 字段。
    expect(payload).not.toHaveProperty("embedding_model_id");
  });

  it("confirmation 边界统一暴露已验证目标、人工字段、AI 建议和 task 身份", async () => {
    const loadPending = vi.fn().mockResolvedValue(undefined);
    const loadLocalPending = vi.fn().mockResolvedValue(undefined);
    const removeLocalTask = vi.fn();
    const { result } = renderHook(() =>
      useIngestConfirmation({
        activePath: "a",
        embeddingModelRef: "ref_emb_default",
        rerankModelRef: "ref_rer_default",
        loadPending,
        loadLocalPending,
        removeLocalTask,
        beforeSingleTask: vi.fn(),
      }),
    );

    await act(async () => {
      await result.current.handleSelectPendingTask(pendingTask("t1", "doc.pptx"));
    });

    expect(result.current.namingPreviewState).toMatchObject({
      taskId: "t1",
      target: { library: "personal", projectId: "", locked: true },
      fields: {
        title: "渠道转型方法论",
        summary: "详细摘要内容",
      },
      ai: {
        naming: null,
        generation: { status: "generated" },
      },
    });
  });

  it("切换模型后 confirm payload 使用新的 model_ref", async () => {
    modelState.current = { ...modelState.current, embeddingRef: "ref_emb_alt" };
    const { result } = renderHook(() => useUploadFlow());
    await driveToReady(result);
    await act(async () => {
      await result.current.handleSubmit();
    });
    expect(ingest.confirmIngest.mock.calls[0][1].embedding_model_ref).toBe("ref_emb_alt");
  });

  it("平台默认嵌入或问答模型缺失（blockSubmit）时禁用提交", async () => {
    modelState.current = {
      ...modelState.current,
      defaultMissing: true,
      blockSubmit: true,
      embeddingRef: "",
    };
    const { result } = renderHook(() => useUploadFlow());
    await driveToReady(result);
    expect(result.current.canSubmit).toBe(false);
  });

  it("普通顾问提交项目知识后展示真实待审批状态而非资产结果", async () => {
    auth.fetchAuthMe.mockResolvedValue({
      projects: [{ projectId: "project-alpha", projectName: "Alpha 项目" }],
    });
    ingest.confirmIngest.mockResolvedValue({
      task_id: "t1",
      status: "waiting_review",
      result_asset_id: null,
      review_id: "review-1",
      index_status: null,
    });
    const { result } = renderHook(() => useUploadFlow());
    await driveToReady(result);
    act(() => {
      result.current.setTargetLibrary("project");
      result.current.setTargetProjectId("project-alpha");
    });
    await act(async () => {
      await result.current.handleSubmit();
    });
    expect(result.current.awaitingProjectReview).toBe(true);
    expect(result.current.resultAssetId).toBeNull();
    expect(result.current.submitReviewId).toBe("review-1");
  });

  it("多文件拖放按顺序创建独立上传任务", async () => {
    auth.fetchAuthMe.mockResolvedValue({
      projects: [{ projectId: "project-ready", projectName: "验收项目" }],
    });
    const { result } = renderHook(() => useUploadFlow());
    const file = new File(["markdown"], "复盘.md", { type: "text/markdown" });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    const second = new File(["text"], "second.txt", { type: "text/plain" });
    act(() => result.current.handleFileDrop([file, second]));
    await waitFor(() => expect(ingest.createIngestUpload).toHaveBeenCalledTimes(2));
    expect(ingest.createIngestUpload.mock.calls.map((call) => call[0].file.name)).toEqual([
      "复盘.md",
      "second.txt",
    ]);
    expect(result.current.localUploadQueue.map((item) => item.fileName)).toEqual([
      "复盘.md",
      "second.txt",
    ]);
    expect(
      result.current.localUploadQueue.every((item) => item.status === "awaiting_confirmation"),
    ).toBe(true);
  });

  it("递归读取嵌套目录并按自然顺序隔离无效、超限和不可读文件", async () => {
    const tooLarge = new File(["x"], "large.pdf", { type: "application/pdf" });
    Object.defineProperty(tooLarge, "size", { value: 26 * 1024 * 1024 });
    const transfer = folderDataTransfer([
      droppedDirectory("客户资料", [
        droppedFile(new File(["one"], "one.txt", { type: "text/plain" })),
        droppedDirectory("子目录", [
          droppedFile(new File(["bad"], "bad.exe")),
          droppedFile(tooLarge),
          droppedFile(new File(["two"], "two.pdf", { type: "application/pdf" })),
          droppedFile(new File([], "locked.docx"), { unreadable: true }),
        ]),
      ]),
    ]);
    const { result } = renderHook(() => useUploadFlow());

    await act(async () => result.current.handleDataTransferDrop(transfer));
    await waitFor(() => expect(ingest.createIngestUpload).toHaveBeenCalledTimes(2));
    expect(ingest.createIngestUpload.mock.calls.map((call) => call[0].file.name)).toEqual([
      "one.txt",
      "two.pdf",
    ]);
    expect(result.current.localUploadQueue.map((item) => item.fileName)).toEqual([
      "one.txt",
      "bad.exe",
      "large.pdf",
      "two.pdf",
      "locked.docx",
    ]);
    expect(result.current.localUploadQueue.map((item) => item.error)).toEqual([
      null,
      "该文件类型暂不支持上传",
      "文件超过 25 MiB 大小上限",
      null,
      "文件内容当前不可读取；请先在本机完成下载后重新选择",
    ]);
    expect(JSON.stringify(result.current.localUploadQueue)).not.toMatch(
      /[A-Za-z]:\\|\/Users\/|webkitRelativePath/,
    );
  });

  it("拒绝 macOS 伴生文件且不误伤普通隐藏文件", async () => {
    const transfer = folderDataTransfer([
      droppedDirectory("__MACOSX", [
        droppedFile(new File(["metadata"], "._archive.md", { type: "text/markdown" })),
      ]),
      droppedFile(new File(["finder"], ".DS_Store")),
      droppedFile(new File(["metadata"], "._foo.md", { type: "text/markdown" })),
      droppedFile(new File(["real"], ".notes.md", { type: "text/markdown" })),
      droppedFile(new File(["real"], "中文 资料.md", { type: "text/markdown" })),
    ]);
    const { result } = renderHook(() => useUploadFlow());

    await act(async () => result.current.handleDataTransferDrop(transfer));
    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(5));
    expect(result.current.localUploadQueue.map((item) => item.status)).toEqual([
      "failed",
      "failed",
      "failed",
      "awaiting_confirmation",
      "awaiting_confirmation",
    ]);
    expect(result.current.localUploadQueue.slice(0, 3).map((item) => item.error)).toEqual([
      "这是 macOS 元数据文件，不是原始资料；请选择不带 `._` 前缀的原文件",
      "这是 macOS 元数据文件，不是原始资料；请选择不带 `._` 前缀的原文件",
      "这是 macOS 元数据文件，不是原始资料；请选择不带 `._` 前缀的原文件",
    ]);
    expect(ingest.createIngestUpload.mock.calls.map((call) => call[0].file.name)).toEqual([
      ".notes.md",
      "中文 资料.md",
    ]);
    expect(JSON.stringify(result.current.localUploadQueue)).not.toContain("__MACOSX");
  });

  it("目录 API 不可用时回退普通文件并给出可行动提示", async () => {
    const fallbackFile = new File(["plain"], "fallback.txt", { type: "text/plain" });
    const transfer = {
      items: [{ getAsFile: () => fallbackFile }],
      files: [fallbackFile],
    } as unknown as DataTransfer;
    const { result } = renderHook(() => useUploadFlow());

    await act(async () => result.current.handleDataTransferDrop(transfer));
    await waitFor(() => expect(ingest.createIngestUpload).toHaveBeenCalledTimes(1));
    expect(result.current.folderDropNotice).toContain("浏览器不支持读取文件夹");
    expect(result.current.localUploadQueue[0].fileName).toBe("fallback.txt");
  });

  it("目录 API 降级时仍接收超过 200 个文件并交给批次队列", async () => {
    const files = Array.from(
      { length: 201 },
      (_, index) => new File(["plain"], `fallback-${index}.txt`, { type: "text/plain" }),
    );
    const transfer = {
      items: files.map((file) => ({ getAsFile: () => file })),
      files,
    } as unknown as DataTransfer;
    const { result } = renderHook(() => useUploadFlow());

    await act(async () => result.current.handleDataTransferDrop(transfer));
    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(201));
    expect(result.current.folderDropNotice).toContain("浏览器不支持读取文件夹");
    expect(result.current.folderDropNotice).not.toContain("一次最多添加");
  });

  it("目录文件条目超过 200 时保留全部独立失败条目", async () => {
    const entries = Array.from({ length: 201 }, (_, index) =>
      droppedFile(new File(["bad"], `unsupported-${index}.exe`)),
    );
    const { result } = renderHook(() => useUploadFlow());

    await act(async () =>
      result.current.handleDataTransferDrop(
        folderDataTransfer([droppedDirectory("huge", entries)]),
      ),
    );
    expect(result.current.localUploadQueue).toHaveLength(201);
    expect(result.current.localUploadQueue.every((item) => item.status === "failed")).toBe(true);
    expect(result.current.folderDropNotice).toBeNull();
    expect(ingest.createIngestUpload).not.toHaveBeenCalled();
  });

  it("切换来源后忽略晚到的目录读取结果", async () => {
    let release!: () => void;
    const lateEntry: TestFileSystemEntry = {
      isFile: true,
      isDirectory: false,
      name: "late.txt",
      file: (success) => {
        release = () => success(new File(["late"], "late.txt", { type: "text/plain" }));
      },
    };
    const { result } = renderHook(() => useUploadFlow());
    let reading!: Promise<void>;

    act(() => {
      reading = result.current.handleDataTransferDrop(folderDataTransfer([lateEntry]));
    });
    act(() => result.current.switchPath("a"));
    await act(async () => {
      release();
      await reading;
    });

    expect(result.current.localUploadQueue).toEqual([]);
    expect(ingest.createIngestUpload).not.toHaveBeenCalled();
  });

  it("组件卸载后不上传递归读取的晚到文件", async () => {
    let release!: () => void;
    const lateEntry: TestFileSystemEntry = {
      isFile: true,
      isDirectory: false,
      name: "late.txt",
      file: (success) => {
        release = () => success(new File(["late"], "late.txt", { type: "text/plain" }));
      },
    };
    const { result, unmount } = renderHook(() => useUploadFlow());
    let reading!: Promise<void>;

    act(() => {
      reading = result.current.handleDataTransferDrop(folderDataTransfer([lateEntry]));
    });
    unmount();
    await act(async () => {
      release();
      await reading;
    });

    expect(ingest.createIngestUpload).not.toHaveBeenCalled();
  });

  it("单条上传失败不阻塞后续文件，并可单独重试", async () => {
    ingest.createIngestUpload
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ ingest_task_id: "t2" })
      .mockResolvedValueOnce({ ingest_task_id: "t1-retry" });
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
    act(() =>
      result.current.handleFileSelect({
        target: {
          files: [
            new File(["a"], "first.pdf", { type: "application/pdf" }),
            new File(["b"], "second.pdf", { type: "application/pdf" }),
          ],
          value: "",
        },
      } as unknown as ChangeEvent<HTMLInputElement>),
    );
    await waitFor(() =>
      expect(result.current.localUploadQueue[1]?.status).toBe("awaiting_confirmation"),
    );
    expect(result.current.localUploadQueue[0]).toMatchObject({
      status: "failed",
      error: "上传失败，请稍后重试",
    });
    act(() => result.current.retryLocalUpload(result.current.localUploadQueue[0].id));
    await waitFor(() =>
      expect(result.current.localUploadQueue[0]?.status).toBe("awaiting_confirmation"),
    );
  });

  it("混合选择时仅有效文件进入上传，非法文件保留各自安全失败原因", async () => {
    const { result } = renderHook(() => useUploadFlow());
    const tooLarge = new File(["x"], "large.pdf", { type: "application/pdf" });
    Object.defineProperty(tooLarge, "size", { value: 26 * 1024 * 1024 });
    act(() =>
      result.current.handleFileSelect({
        target: {
          files: [
            new File(["ok"], "valid.txt", { type: "text/plain" }),
            new File(["bad"], "unsafe.exe", { type: "application/octet-stream" }),
            tooLarge,
          ],
          value: "",
        },
      } as unknown as ChangeEvent<HTMLInputElement>),
    );
    await waitFor(() => expect(ingest.createIngestUpload).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(result.current.localUploadQueue.map((item) => item.status)).toEqual([
        "awaiting_confirmation",
        "failed",
        "failed",
      ]),
    );
    expect(result.current.localUploadQueue[1].error).toBe("该文件类型暂不支持上传");
    expect(result.current.localUploadQueue[2].error).toBe("文件超过 25 MiB 大小上限");
  });

  it("三个本地文件按各自服务端状态独立收敛，并刷新待确认列表", async () => {
    const taskPolls = new Map<string, number>();
    ingest.createIngestUpload.mockImplementation(({ file }: { file: File }) =>
      Promise.resolve({ ingest_task_id: file.name.replace(".pdf", "") }),
    );
    ingest.fetchIngestTaskStatus.mockImplementation((taskId: string) => {
      const attempt = (taskPolls.get(taskId) ?? 0) + 1;
      taskPolls.set(taskId, attempt);
      if (taskId === "second" && attempt === 1) {
        return Promise.resolve(taskStatus(taskId, "content_generation", "processing"));
      }
      if (taskId === "third") {
        return Promise.resolve({
          ...taskStatus(taskId, "failed", "failed"),
          error: {
            code: "processing_failed",
            message: "文件内容无法处理，请检查后重试",
            recovery_hint: "retry",
          },
        });
      }
      return Promise.resolve(taskStatus(taskId));
    });
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());

    act(() =>
      result.current.handleFileDrop([
        new File(["a"], "first.pdf", { type: "application/pdf" }),
        new File(["b"], "second.pdf", { type: "application/pdf" }),
        new File(["c"], "third.pdf", { type: "application/pdf" }),
      ]),
    );

    await waitFor(() =>
      expect(result.current.localUploadQueue.map((item) => item.status)).toEqual([
        "awaiting_confirmation",
        "awaiting_confirmation",
        "failed",
      ]),
    );
    expect(result.current.localUploadQueue[2].error).toBe("文件内容无法处理，请检查后重试");
    expect(taskPolls).toEqual(
      new Map([
        ["first", 1],
        ["second", 2],
        ["third", 1],
      ]),
    );
    expect(ingest.fetchPendingIngestTasks).toHaveBeenCalledWith("path_b_upload");
    const terminalCallCount = ingest.fetchIngestTaskStatus.mock.calls.length;
    await new Promise((resolve) => window.setTimeout(resolve, 35));
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(terminalCallCount);
  });

  it("安全降级完成后进入人工确认并停止轮询，不误报处理超时", async () => {
    ingest.fetchIngestTaskStatus.mockResolvedValue({
      ...taskStatus("t1", "degraded_complete", "degraded"),
      next_action: {
        key: "review_and_confirm",
        route_key: "upload_task",
        enabled: true,
      },
      error: {
        code: "content_generation_unavailable",
        message: "内容建议暂不可用，请人工核对后继续",
        recovery_hint: "review_and_confirm",
      },
    });
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());

    act(() =>
      result.current.handleFileDrop([new File(["a"], "degraded.pdf", { type: "application/pdf" })]),
    );

    await waitFor(() =>
      expect(result.current.localUploadQueue[0]).toMatchObject({
        status: "awaiting_confirmation",
        error: "内容建议暂不可用，请人工核对后继续",
      }),
    );
    expect(ingest.fetchPendingIngestTasks).toHaveBeenCalledWith("path_b_upload");
    await new Promise((resolve) => window.setTimeout(resolve, 35));
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1);
    expect(result.current.localUploadQueue[0]?.error).not.toContain("超时");
  });

  it("失败状态优先于待确认 stage 与 action，矛盾组合必须 fail closed", async () => {
    ingest.createIngestUpload.mockImplementation(({ file }: { file: File }) =>
      Promise.resolve({ ingest_task_id: file.name.replace(".pdf", "") }),
    );
    ingest.fetchIngestTaskStatus.mockImplementation((taskId: string) =>
      Promise.resolve({
        ...taskStatus(
          taskId,
          taskId === "failed-status" ? "awaiting_confirmation" : "failed",
          taskId === "failed-status" ? "failed" : "action_required",
        ),
        next_action: {
          key: "review_and_confirm",
          route_key: "upload_task",
          enabled: true,
        },
        error: {
          code: "processing_failed",
          message: `${taskId} 安全失败提示`,
          recovery_hint: "retry",
        },
      }),
    );
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());

    act(() =>
      result.current.handleFileDrop([
        new File(["a"], "failed-status.pdf", { type: "application/pdf" }),
        new File(["b"], "failed-stage.pdf", { type: "application/pdf" }),
      ]),
    );

    await waitFor(() =>
      expect(result.current.localUploadQueue.map((item) => item.status)).toEqual([
        "failed",
        "failed",
      ]),
    );
    expect(result.current.localUploadQueue.map((item) => item.error)).toEqual([
      "failed-status 安全失败提示",
      "failed-stage 安全失败提示",
    ]);
    expect(ingest.fetchPendingIngestTasks).toHaveBeenCalledTimes(1);
    const terminalCallCount = ingest.fetchIngestTaskStatus.mock.calls.length;
    await new Promise((resolve) => window.setTimeout(resolve, 35));
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(terminalCallCount);
  });

  it("状态轮询同一时刻只允许一个请求批次在飞行", async () => {
    const firstStatus = deferred<IngestTaskStatusDTO>();
    ingest.fetchIngestTaskStatus.mockReset().mockReturnValue(firstStatus.promise);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());

    act(() =>
      result.current.handleFileDrop([new File(["a"], "single.pdf", { type: "application/pdf" })]),
    );
    await waitFor(() => expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => window.setTimeout(resolve, 35));
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1);

    await act(async () => firstStatus.resolve(taskStatus("t1")));
    await waitFor(() =>
      expect(result.current.localUploadQueue[0]?.status).toBe("awaiting_confirmation"),
    );
  });

  it("来源切换后停止轮询并忽略晚到的状态响应", async () => {
    const firstStatus = deferred<IngestTaskStatusDTO>();
    ingest.fetchIngestTaskStatus.mockReset().mockReturnValue(firstStatus.promise);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
    act(() =>
      result.current.handleFileDrop([new File(["a"], "switch.pdf", { type: "application/pdf" })]),
    );
    await waitFor(() => expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1));

    act(() => result.current.switchPath("a"));
    await act(async () => firstStatus.resolve(taskStatus("t1")));
    await new Promise((resolve) => window.setTimeout(resolve, 25));

    expect(result.current.activePath).toBe("a");
    expect(result.current.localUploadQueue[0]?.status).toBe("processing");
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1);
  });

  it("卸载后停止轮询并忽略晚到的状态响应", async () => {
    const firstStatus = deferred<IngestTaskStatusDTO>();
    ingest.fetchIngestTaskStatus.mockReset().mockReturnValue(firstStatus.promise);
    const { result, unmount } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
    act(() =>
      result.current.handleFileDrop([new File(["a"], "unmount.pdf", { type: "application/pdf" })]),
    );
    await waitFor(() => expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1));

    unmount();
    firstStatus.resolve(taskStatus("t1"));
    await new Promise((resolve) => window.setTimeout(resolve, 25));
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(1);
  });

  it("处理状态持续不收敛时在有限次数后变为可重试失败", async () => {
    ingest.fetchIngestTaskStatus
      .mockReset()
      .mockImplementation((taskId: string) =>
        Promise.resolve(taskStatus(taskId, "content_generation", "processing")),
      );
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
    act(() =>
      result.current.handleFileDrop([new File(["a"], "timeout.pdf", { type: "application/pdf" })]),
    );

    await waitFor(() => expect(result.current.localUploadQueue[0]?.status).toBe("failed"));
    expect(result.current.localUploadQueue[0]?.error).toBe("文件处理超时，请稍后重试");
    expect(ingest.fetchIngestTaskStatus).toHaveBeenCalledTimes(3);
  });

  it("reset 立即收敛 loading，旧请求晚到也不能恢复旧列表", async () => {
    const initialLocalPending = deferred<PendingIngestItemDTO[]>();
    ingest.fetchPendingIngestTasks.mockReset().mockReturnValue(initialLocalPending.promise);
    const { result } = renderHook(() => useUploadFlow());
    expect(result.current.localPendingLoading).toBe(true);

    act(() => result.current.handleReset());
    expect(result.current.localPendingLoading).toBe(false);
    await act(async () =>
      initialLocalPending.resolve([
        { ...pendingTask("stale", "stale.pdf"), source: "path_b_upload" },
      ]),
    );

    expect(result.current.localPendingLoading).toBe(false);
    expect(result.current.localPendingTasks).toEqual([]);
  });

  it("删除成功由 hook 唯一 reset 并只刷新当前来源，失败时保留编辑态", async () => {
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockResolvedValueOnce([{ ...pendingTask("local", "local.pdf"), source: "path_b_upload" }])
      .mockResolvedValueOnce([]);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localPendingTasks).toHaveLength(1));
    await act(async () => result.current.handleDeletePending("local"));
    await waitFor(() => expect(result.current.localPendingLoading).toBe(false));

    expect(ingest.deletePendingTask).toHaveBeenCalledWith("local");
    expect(result.current.localPendingTasks).toEqual([]);
    expect(ingest.fetchPendingIngestTasks.mock.calls).toEqual([
      ["path_b_upload"],
      ["path_b_upload"],
    ]);

    await act(async () => {
      await result.current.handleSelectPendingTask({
        ...pendingTask("keep", "keep.pdf"),
        source: "path_b_upload",
      });
    });
    ingest.deletePendingTask.mockRejectedValueOnce(new Error("network"));
    await act(async () => result.current.handleDeletePending("keep"));
    expect(result.current.taskId).toBe("keep");
    expect(result.current.flowState).toBe("ready");
    expect(result.current.apiError).toBe("拒绝入库失败，任务仍保留，请重试");
  });

  it("来源切换后忽略晚到的单条拒绝响应", async () => {
    const lateDelete = deferred<void>();
    const local = { ...pendingTask("late-local", "late.pdf"), source: "path_b_upload" };
    const wecom = { ...pendingTask("wecom-current", "wecom.pdf"), source: "path_a_wecom" };
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockImplementation(async (source) => (source === "path_b_upload" ? [local] : [wecom]));
    ingest.deletePendingTask.mockReset().mockReturnValueOnce(lateDelete.promise);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localPendingTasks).toEqual([local]));

    let deleting!: Promise<void>;
    act(() => {
      deleting = result.current.handleDeletePending(local.id);
    });
    act(() => result.current.switchPath("a"));
    await waitFor(() => expect(result.current.pendingTasks).toEqual([wecom]));

    await act(async () => {
      lateDelete.resolve();
      await deleting;
    });

    expect(result.current.activePath).toBe("a");
    expect(result.current.pendingTasks).toEqual([wecom]);
    expect(result.current.apiError).toBeNull();
    expect(ingest.fetchPendingIngestTasks.mock.calls).toEqual([
      ["path_b_upload"],
      ["path_a_wecom"],
    ]);
  });

  it("本地单条拒绝成功同时移除待确认列表和本次上传队列，失败则两处均保留", async () => {
    const local = { ...pendingTask("t1", "local.pdf"), source: "path_b_upload" };
    ingest.fetchPendingIngestTasks.mockReset().mockResolvedValue([local]);
    const { result } = renderHook(() => useUploadFlow());
    act(() =>
      result.current.handleFileDrop([
        new File(["local"], "local.pdf", { type: "application/pdf" }),
      ]),
    );
    await waitFor(() =>
      expect(result.current.localUploadQueue[0]?.status).toBe("awaiting_confirmation"),
    );
    await waitFor(() => expect(result.current.localPendingTasks).toHaveLength(1));

    ingest.deletePendingTask.mockRejectedValueOnce(new Error("SECRET upstream"));
    await act(async () => result.current.handleDeletePending("t1"));
    expect(result.current.localPendingTasks).toHaveLength(1);
    expect(result.current.localUploadQueue).toHaveLength(1);
    expect(result.current.apiError).toBe("拒绝入库失败，任务仍保留，请重试");
    expect(JSON.stringify(result.current)).not.toContain("SECRET upstream");

    ingest.fetchPendingIngestTasks.mockResolvedValueOnce([]);
    await act(async () => result.current.handleDeletePending("t1"));
    expect(result.current.localPendingTasks).toEqual([]);
    expect(result.current.localUploadQueue).toEqual([]);
  });

  it("本地单条确认成功从本次上传队列移除服务端任务", async () => {
    const { result } = renderHook(() => useUploadFlow());
    act(() =>
      result.current.handleFileDrop([
        new File(["local"], "local.pdf", { type: "application/pdf" }),
      ]),
    );
    await waitFor(() =>
      expect(result.current.localUploadQueue[0]?.status).toBe("awaiting_confirmation"),
    );
    await act(async () => {
      await result.current.handleSelectPendingTask({
        ...pendingTask("t1", "local.pdf"),
        source: "path_b_upload",
      });
    });
    await act(async () => result.current.handleSubmit());

    expect(result.current.localUploadQueue).toEqual([]);
    expect(result.current.flowState).toBe("submitted");
  });

  it("忽略 A→B 反序完成中的 A 旧回包", async () => {
    const responseA = deferred<IngestAiResultDTO>();
    const responseB = deferred<IngestAiResultDTO>();
    ingest.fetchIngestAiResult
      .mockReset()
      .mockReturnValueOnce(responseA.promise)
      .mockReturnValueOnce(responseB.promise);
    const { result } = renderHook(() => useUploadFlow());
    let runA!: Promise<void>;
    let runB!: Promise<void>;

    act(() => {
      runA = result.current.handleSelectPendingTask(pendingTask("task-a", "A.docx"));
      runB = result.current.handleSelectPendingTask(pendingTask("task-b", "B.docx"));
    });
    await act(async () => {
      responseB.resolve({
        ...readyAiResult,
        ingest_task_id: "task-b",
        suggested_title: "B 任务建议",
      });
      await runB;
    });
    expect(result.current.taskId).toBe("task-b");
    expect(result.current.editTitle).toBe("B 任务建议");

    await act(async () => {
      responseA.resolve({
        ...readyAiResult,
        ingest_task_id: "task-a",
        suggested_title: "A 任务旧建议",
      });
      await runA;
    });
    expect(result.current.taskId).toBe("task-b");
    expect(result.current.editTitle).toBe("B 任务建议");
  });

  it("重置后忽略仍在飞行中的任务回包", async () => {
    const response = deferred<IngestAiResultDTO>();
    ingest.fetchIngestAiResult.mockReset().mockReturnValueOnce(response.promise);
    const { result } = renderHook(() => useUploadFlow());
    let run!: Promise<void>;

    act(() => {
      run = result.current.handleSelectPendingTask(pendingTask("task-a", "A.docx"));
    });
    act(() => result.current.handleReset());
    await act(async () => {
      response.resolve({ ...readyAiResult, suggested_title: "不应写入的建议" });
      await run;
    });

    expect(result.current.flowState).toBe("idle");
    expect(result.current.taskId).toBeNull();
    expect(result.current.editTitle).toBe("");
  });

  it("切换来源后忽略旧来源的任务回包", async () => {
    const response = deferred<IngestAiResultDTO>();
    ingest.fetchIngestAiResult.mockReset().mockReturnValueOnce(response.promise);
    const { result } = renderHook(() => useUploadFlow());
    let run!: Promise<void>;

    act(() => result.current.switchPath("a"));
    act(() => {
      run = result.current.handleSelectPendingTask(pendingTask("task-a", "A.docx"));
    });
    act(() => result.current.switchPath("b"));
    await act(async () => {
      response.resolve({ ...readyAiResult, suggested_title: "不应跨来源写入" });
      await run;
    });

    expect(result.current.activePath).toBe("b");
    expect(result.current.flowState).toBe("idle");
    expect(result.current.taskId).toBeNull();
    expect(result.current.editTitle).toBe("");
  });

  it("keeps the first WeCom view loading until its pending request settles", async () => {
    const pending = deferred<PendingIngestItemDTO[]>();
    // Path "b" 初始加载会立即 resolved；Path "a" 切换到 WeCom 时才用延迟 promise。
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockResolvedValueOnce([]) // path "b"（本地上传待确认）
      .mockReturnValueOnce(pending.promise); // path "a"（企微待确认）
    const { result } = renderHook(() => useUploadFlow());

    // 等初始 path "b" 加载完毕
    await waitFor(() => expect(result.current.localPendingLoading).toBe(false));

    expect(result.current.pendingLoading).toBe(true);
    act(() => result.current.switchPath("a"));
    expect(result.current.pendingLoading).toBe(true);
    await waitFor(() => expect(ingest.fetchPendingIngestTasks).toHaveBeenCalledTimes(2));

    await act(async () => pending.resolve([]));
    await waitFor(() => expect(result.current.pendingLoading).toBe(false));
  });

  it("confirms a selected batch strictly in order and continues after one failure", async () => {
    const first = deferred<IngestAiResultDTO>();
    ingest.fetchIngestAiResult
      .mockReset()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ ...readyAiResult, ingest_task_id: "task-b" });
    ingest.bulkConfirmIngest.mockResolvedValueOnce({
      operation_id: "bulk-1",
      status: "completed_with_errors",
      execution_mode: "synchronous",
      submitted: 2,
      succeeded: 1,
      skipped: 1,
      failed: 0,
      items: [
        {
          item_id: "task-a",
          status: "skipped",
          reason_code: "item_state_changed",
          message: "状态已变化",
        },
        {
          item_id: "task-b",
          status: "succeeded",
          reason_code: null,
          message: null,
        },
      ],
    });
    ingest.createIngestUpload
      .mockReset()
      .mockResolvedValueOnce({ ingest_task_id: "task-a" })
      .mockResolvedValueOnce({ ingest_task_id: "task-b" });
    const { result } = renderHook(() => useUploadFlow());
    const a = pendingTask("task-a", "A.docx");
    const b = pendingTask("task-b", "B.docx");
    act(() =>
      result.current.handleFileDrop([new File(["a"], "A.docx"), new File(["b"], "B.docx")]),
    );
    await waitFor(() =>
      expect(result.current.localUploadQueue.map((item) => item.status)).toEqual([
        "awaiting_confirmation",
        "awaiting_confirmation",
      ]),
    );
    let batch!: Promise<void>;

    act(() => {
      batch = result.current.handleBatchConfirm([a, b], "personal");
    });
    expect(result.current.batchStatus["task-a"]).toBe("processing");
    expect(ingest.fetchIngestAiResult).toHaveBeenCalledTimes(1);
    expect(ingest.fetchIngestAiResult).toHaveBeenLastCalledWith("task-a");

    await act(async () => {
      first.resolve({ ...readyAiResult, ingest_task_id: "task-a" });
      await batch;
    });
    expect(ingest.bulkConfirmIngest).toHaveBeenCalledWith(
      expect.objectContaining({
        targetScope: "personal",
        items: [
          expect.objectContaining({ taskId: "task-a" }),
          expect.objectContaining({ taskId: "task-b" }),
        ],
      }),
    );
    expect(result.current.batchStatus["task-a"]).toBe("failed");
    expect(result.current.batchStatus["task-b"]).toBe("success");
    expect(result.current.localUploadQueue.map((item) => item.ingestTaskId)).toEqual(["task-a"]);
  });

  it("本地来源严格串行批量拒绝，失败项保留勾选并可单条重试", async () => {
    const a = { ...pendingTask("local-a", "A.docx"), source: "path_b_upload" };
    const b = { ...pendingTask("local-b", "B.docx"), source: "path_b_upload" };
    const firstDelete = deferred<void>();
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockResolvedValueOnce([a, b])
      .mockResolvedValueOnce([a])
      .mockResolvedValueOnce([]);
    ingest.deletePendingTask
      .mockReset()
      .mockReturnValueOnce(firstDelete.promise)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localPendingTasks).toHaveLength(2));
    act(() => {
      result.current.toggleBatchTask(a.id);
      result.current.toggleBatchTask(b.id);
    });

    let rejecting!: Promise<void>;
    act(() => {
      rejecting = result.current.handleBatchReject([a, b]);
    });
    expect(ingest.deletePendingTask).toHaveBeenCalledTimes(1);
    expect(ingest.deletePendingTask).toHaveBeenLastCalledWith("local-a");
    expect(result.current.batchStatus["local-a"]).toBe("processing");

    await act(async () => {
      firstDelete.reject(new Error("safe failure"));
      await rejecting;
    });
    expect(ingest.deletePendingTask.mock.calls.map((call) => call[0])).toEqual([
      "local-a",
      "local-b",
    ]);
    await waitFor(() => expect(result.current.localPendingLoading).toBe(false));
    expect(result.current.localPendingTasks.map((task) => task.id)).toEqual(["local-a"]);
    expect(result.current.batchSelection).toEqual(["local-a"]);
    expect(result.current.batchErrors["local-a"]).toBe("网络连接中断，任务仍保留，可重试。");
    expect(result.current.batchRejectRetryability["local-a"]).toBe(true);
    expect(ingest.confirmIngest).not.toHaveBeenCalled();

    await act(async () => result.current.handleBatchReject([a]));
    await waitFor(() => expect(result.current.localPendingTasks).toEqual([]));
    expect(result.current.batchSelection).toEqual([]);
  });

  it("永久拒绝的状态冲突保留任务但不提供自动重试", async () => {
    const task = { ...pendingTask("local-conflict", "Conflict.docx"), source: "path_b_upload" };
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockResolvedValueOnce([task])
      .mockResolvedValueOnce([task]);
    ingest.deletePendingTask
      .mockReset()
      .mockRejectedValueOnce(new ApiError(409, "状态冲突", "ingest_already_confirmed"));
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localPendingTasks).toHaveLength(1));

    await act(async () => result.current.handleBatchReject([task]));

    expect(result.current.localPendingTasks).toHaveLength(1);
    expect(result.current.batchSelection).toEqual([]);
    expect(result.current.batchRejectRetryability[task.id]).toBe(false);
    expect(result.current.batchErrors[task.id]).toBe(
      "已入库：该任务已形成知识资产，不能永久删除。",
    );
  });

  it("第二项拒绝仍在请求中时第一项成功任务已从本地列表消失", async () => {
    const a = { ...pendingTask("local-a", "A.docx"), source: "path_b_upload" };
    const b = { ...pendingTask("local-b", "B.docx"), source: "path_b_upload" };
    const secondDelete = deferred<void>();
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockResolvedValueOnce([a, b])
      .mockResolvedValueOnce([a, b])
      .mockResolvedValueOnce([]);
    ingest.deletePendingTask
      .mockReset()
      .mockResolvedValueOnce(undefined)
      .mockReturnValueOnce(secondDelete.promise);
    ingest.createIngestUpload
      .mockReset()
      .mockResolvedValueOnce({ ingest_task_id: "local-a" })
      .mockResolvedValueOnce({ ingest_task_id: "local-b" });
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localPendingTasks).toHaveLength(2));
    act(() =>
      result.current.handleFileDrop([new File(["a"], "A.docx"), new File(["b"], "B.docx")]),
    );
    await waitFor(() =>
      expect(result.current.localUploadQueue.map((item) => item.status)).toEqual([
        "awaiting_confirmation",
        "awaiting_confirmation",
      ]),
    );
    act(() => {
      result.current.toggleBatchTask(a.id);
      result.current.toggleBatchTask(b.id);
    });

    let rejecting!: Promise<void>;
    act(() => {
      rejecting = result.current.handleBatchReject([a, b]);
    });
    await waitFor(() => expect(ingest.deletePendingTask).toHaveBeenCalledTimes(2));

    expect(result.current.localPendingTasks.map((task) => task.id)).toEqual(["local-b"]);
    expect(result.current.localUploadQueue.map((item) => item.ingestTaskId)).toEqual(["local-b"]);
    expect(result.current.batchSelection).toEqual(["local-b"]);
    expect(result.current.batchStatus["local-b"]).toBe("processing");
    expect(result.current.batchBusy).toBe(true);

    await act(async () => {
      secondDelete.resolve();
      await rejecting;
    });
    await waitFor(() => expect(result.current.localPendingTasks).toEqual([]));
    expect(result.current.localUploadQueue).toEqual([]);
  });

  it("企微来源批量拒绝只刷新企微列表且不调用确认入库", async () => {
    const a = pendingTask("wecom-a", "A.docx");
    const b = pendingTask("wecom-b", "B.docx");
    ingest.fetchPendingIngestTasks
      .mockReset()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([a, b])
      .mockResolvedValueOnce([]);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localPendingLoading).toBe(false));
    act(() => result.current.switchPath("a"));
    await waitFor(() => expect(result.current.pendingTasks).toHaveLength(2));

    await act(async () => result.current.handleBatchReject([a, b]));
    await waitFor(() => expect(result.current.pendingLoading).toBe(false));

    expect(ingest.deletePendingTask.mock.calls.map((call) => call[0])).toEqual([
      "wecom-a",
      "wecom-b",
    ]);
    expect(ingest.fetchPendingIngestTasks.mock.calls).toEqual([
      ["path_b_upload"],
      ["path_a_wecom"],
      ["path_a_wecom"],
    ]);
    expect(result.current.pendingTasks).toEqual([]);
    expect(ingest.confirmIngest).not.toHaveBeenCalled();
  });

  it("来源切换会停止批量拒绝后续条目并忽略晚到响应", async () => {
    const firstDelete = deferred<void>();
    ingest.deletePendingTask.mockReset().mockReturnValueOnce(firstDelete.promise);
    const { result } = renderHook(() => useUploadFlow());
    const a = { ...pendingTask("local-a", "A.docx"), source: "path_b_upload" };
    const b = { ...pendingTask("local-b", "B.docx"), source: "path_b_upload" };
    let rejecting!: Promise<void>;

    act(() => {
      rejecting = result.current.handleBatchReject([a, b]);
    });
    await waitFor(() => expect(ingest.deletePendingTask).toHaveBeenCalledWith("local-a"));
    act(() => result.current.switchPath("a"));
    await act(async () => {
      firstDelete.resolve();
      await rejecting;
    });

    expect(ingest.deletePendingTask).toHaveBeenCalledTimes(1);
    expect(result.current.activePath).toBe("a");
    expect(result.current.batchBusy).toBe(false);
  });

  it("组件卸载后停止批量拒绝后续条目", async () => {
    const firstDelete = deferred<void>();
    ingest.deletePendingTask.mockReset().mockReturnValueOnce(firstDelete.promise);
    const { result, unmount } = renderHook(() => useUploadFlow());
    const a = { ...pendingTask("local-a", "A.docx"), source: "path_b_upload" };
    const b = { ...pendingTask("local-b", "B.docx"), source: "path_b_upload" };
    let rejecting!: Promise<void>;

    act(() => {
      rejecting = result.current.handleBatchReject([a, b]);
    });
    await waitFor(() => expect(ingest.deletePendingTask).toHaveBeenCalledWith("local-a"));
    unmount();
    await act(async () => {
      firstDelete.resolve();
      await rejecting;
    });

    expect(ingest.deletePendingTask).toHaveBeenCalledTimes(1);
  });

  it("ignores a late bulk-confirm response when the user switches source", async () => {
    const bulkConfirmation = deferred<{
      operation_id: string;
      status: string;
      execution_mode: string;
      submitted: number;
      succeeded: number;
      skipped: number;
      failed: number;
      items: Array<{
        item_id: string;
        status: string;
        reason_code: null;
        message: null;
      }>;
    }>();
    ingest.fetchIngestAiResult
      .mockReset()
      .mockResolvedValueOnce({ ...readyAiResult, ingest_task_id: "task-a" })
      .mockResolvedValueOnce({ ...readyAiResult, ingest_task_id: "task-b" });
    ingest.bulkConfirmIngest.mockReset().mockReturnValueOnce(bulkConfirmation.promise);
    const { result } = renderHook(() => useUploadFlow());
    const a = pendingTask("task-a", "A.docx");
    const b = pendingTask("task-b", "B.docx");
    let batch!: Promise<void>;

    act(() => {
      batch = result.current.handleBatchConfirm([a, b], "personal");
    });
    await waitFor(() => expect(ingest.bulkConfirmIngest).toHaveBeenCalledTimes(1));
    act(() => {
      result.current.switchPath("a");
    });
    await act(async () => {
      bulkConfirmation.resolve({
        operation_id: "bulk-1",
        status: "completed",
        execution_mode: "synchronous",
        submitted: 2,
        succeeded: 2,
        skipped: 0,
        failed: 0,
        items: [
          {
            item_id: "task-a",
            status: "succeeded",
            reason_code: null,
            message: null,
          },
          {
            item_id: "task-b",
            status: "succeeded",
            reason_code: null,
            message: null,
          },
        ],
      });
      await batch;
    });

    expect(ingest.bulkConfirmIngest).toHaveBeenCalledTimes(1);
    expect(ingest.fetchIngestAiResult).toHaveBeenCalledTimes(2);
    expect(result.current.batchBusy).toBe(false);
  });

  it("stops a batch after unmount without confirming later items", async () => {
    const first = deferred<IngestAiResultDTO>();
    ingest.fetchIngestAiResult.mockReset().mockReturnValueOnce(first.promise);
    const { result, unmount } = renderHook(() => useUploadFlow());
    const a = pendingTask("task-a", "A.docx");
    const b = pendingTask("task-b", "B.docx");
    let batch!: Promise<void>;

    act(() => {
      batch = result.current.handleBatchConfirm([a, b], "personal");
    });
    unmount();
    await act(async () => {
      first.resolve({ ...readyAiResult, ingest_task_id: "task-a" });
      await batch;
    });

    expect(ingest.confirmIngest).not.toHaveBeenCalled();
    expect(ingest.fetchIngestAiResult).toHaveBeenCalledTimes(1);
  });

  it("releases the batch lock when another task selection invalidates the batch", async () => {
    const firstBatchResult = deferred<IngestAiResultDTO>();
    ingest.fetchIngestAiResult
      .mockReset()
      .mockReturnValueOnce(firstBatchResult.promise)
      .mockResolvedValueOnce({ ...readyAiResult, ingest_task_id: "task-b" })
      .mockResolvedValueOnce({ ...readyAiResult, ingest_task_id: "task-a" });
    ingest.confirmIngest.mockReset().mockResolvedValue({
      task_id: "task-a",
      status: "completed",
      result_asset_id: "a1",
    });
    const { result } = renderHook(() => useUploadFlow());
    const a = pendingTask("task-a", "A.docx");
    const b = pendingTask("task-b", "B.docx");
    let batch!: Promise<void>;

    act(() => {
      batch = result.current.handleBatchConfirm([a, b], "personal");
    });
    await act(async () => {
      await result.current.handleSelectPendingTask(b);
      firstBatchResult.resolve({ ...readyAiResult, ingest_task_id: "task-a" });
      await batch;
    });
    expect(result.current.batchBusy).toBe(false);

    await act(async () => {
      await result.current.handleBatchConfirm([a], "personal");
    });
    expect(ingest.bulkConfirmIngest).toHaveBeenCalledTimes(1);
    expect(ingest.bulkConfirmIngest).toHaveBeenLastCalledWith(
      expect.objectContaining({
        targetScope: "personal",
        items: [expect.objectContaining({ taskId: "task-a" })],
      }),
    );
  });
});
