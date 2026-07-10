import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ChangeEvent } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useUploadFlow } from "./useUploadFlow";
import type { ModelSelectionState } from "../../hooks/useModelSelection";

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

const readyAiResult = {
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
  confidence: 0.9,
  naming_parsed_fields: null,
  extraction_status: "extracted",
  extracted_text_preview: null,
  extracted_char_count: 100,
  error_message: null,
  is_possible_duplicate: false,
  duplicate_of_task_id: null,
  duplicate_of_asset_id: null,
};

function fileEvent() {
  const file = new File(["bytes"], "doc.pptx", { type: "application/vnd.ms-powerpoint" });
  return { target: { files: [file] } } as unknown as ChangeEvent<HTMLInputElement>;
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
      result_asset_id: "a1",
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
});
