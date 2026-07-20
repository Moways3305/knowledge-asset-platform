import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ChangeEvent } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useUploadFlow } from "./useUploadFlow";
import type { ModelSelectionState } from "../../hooks/useModelSelection";
import type { IngestAiResultDTO, PendingIngestItemDTO } from "../../types/ingest";

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
  fetchIngestAiResult: vi.fn(),
  fetchPendingIngestTasks: vi.fn(),
  confirmIngest: vi.fn(),
}));
vi.mock("../../api/ingest", () => ingest);

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

function fileEvent() {
  const file = new File(["bytes"], "doc.pptx", { type: "application/vnd.ms-powerpoint" });
  return { target: { files: [file] } } as unknown as ChangeEvent<HTMLInputElement>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function pendingTask(id: string, fileName: string): PendingIngestItemDTO {
  return {
    id,
    source: "path_a_wecom",
    status: "pending_confirmation",
    source_file_name: fileName,
    target_scope: "personal",
    target_project_id: null,
    extraction_status: "extracted",
    error_type: null,
    error_message: null,
    suggested_title: null,
    suggested_one_liner: null,
    naming_parsed_fields: null,
    confidence: null,
    result_asset_id: null,
    created_at: null,
    updated_at: null,
  };
}

async function driveToReady(result: { current: ReturnType<typeof useUploadFlow> }) {
  await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
  act(() => result.current.handleFileSelect(fileEvent()));
  await act(async () => {
    await result.current.handleStart();
  });
  await waitFor(() => expect(result.current.flowState).toBe("ready"));
}

describe("useUploadFlow model selection (PBC-38)", () => {
  beforeEach(() => {
    auth.fetchAuthMe.mockReset().mockResolvedValue({ projects: [] });
    ingest.createIngestUpload.mockReset().mockResolvedValue({ ingest_task_id: "t1" });
    ingest.fetchIngestAiResult.mockReset().mockResolvedValue(readyAiResult);
    ingest.fetchPendingIngestTasks.mockReset().mockResolvedValue([]);
    ingest.confirmIngest.mockReset().mockResolvedValue({
      task_id: "t1",
      status: "completed",
      result_asset_id: "a1",
      review_id: null,
      index_status: "indexed",
    });
    modelState.current = {
      ...modelState.current,
      blockSubmit: false,
      embeddingRef: "ref_emb_default",
      rerankRef: "ref_rer_default",
    };
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

  it("接受真实拖放文件并在重置时清空前一任务状态", async () => {
    auth.fetchAuthMe.mockResolvedValue({
      projects: [{ projectId: "project-ready", projectName: "验收项目" }],
    });
    const { result } = renderHook(() => useUploadFlow());
    const file = new File(["markdown"], "复盘.md", { type: "text/markdown" });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    act(() => result.current.handleFileDrop(file));
    expect(result.current.fileName).toBe("复盘.md");
    expect(result.current.flowState).toBe("file_selected");

    act(() => result.current.handleReset());
    expect(result.current.fileName).toBe("");
    expect(result.current.taskId).toBeNull();
    expect(result.current.flowState).toBe("idle");
  });

  it("处理失败时保持不可提交并提供真实恢复状态", async () => {
    ingest.fetchIngestAiResult.mockResolvedValue({
      ...readyAiResult,
      status: "failed",
      suggested_one_liner: null,
      suggested_summary: null,
      summary: null,
      summary_status: "failed",
      error_message: "未能生成内容建议",
    });
    const { result } = renderHook(() => useUploadFlow());

    await waitFor(() => expect(auth.fetchAuthMe).toHaveBeenCalled());
    act(() => result.current.handleFileSelect(fileEvent()));
    await act(async () => result.current.handleStart());

    expect(result.current.flowState).toBe("failed");
    expect(result.current.canSubmit).toBe(false);
    expect(result.current.processingNote).toContain("未能生成内容建议");
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
    ingest.fetchPendingIngestTasks.mockReset().mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useUploadFlow());

    expect(result.current.pendingLoading).toBe(true);
    act(() => result.current.switchPath("a"));
    expect(result.current.pendingLoading).toBe(true);
    await waitFor(() => expect(ingest.fetchPendingIngestTasks).toHaveBeenCalledTimes(1));

    await act(async () => pending.resolve([]));
    await waitFor(() => expect(result.current.pendingLoading).toBe(false));
  });
});
