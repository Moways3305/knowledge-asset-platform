import { useState, useRef, useCallback, useEffect } from "react";
import { ApiError } from "../../api/http";
import { fetchAuthMe } from "../../api/auth";
import {
  confirmIngest,
  createIngestUpload,
  fetchIngestAiResult,
  fetchPendingIngestTasks,
} from "../../api/ingest";
import type { IngestAiResultDTO, NamingFields, PendingIngestItemDTO } from "../../types/ingest";
import { useModelSelection } from "../../hooks/useModelSelection";
import {
  POLL_INTERVAL_MS,
  POLL_MAX_ATTEMPTS,
  sleep,
  visibilityToKey,
  type FlowState,
  type PathBranch,
  type TargetLibrary,
} from "./uploadConstants";

// 资产化确认工作台的容器 Hook：收拢企业微信待确认 / 本地上传共享的
// 全部状态、AI 结果轮询、人工校正字段、确认入库与重置逻辑。页面本体只消费此 hook、
// 做步骤路由与顶层 state 传递；展示拆到 UploadStepA / UploadStepB / UploadConfirmPanel。
export function useUploadFlow() {
  const [activePath, setActivePath] = useState<PathBranch>("b");

  // PBC-38：入库模型选择（默认平台推荐 embedding/rerank；缺默认时禁用提交）。
  const models = useModelSelection();

  // Path B local upload state
  const [flowState, setFlowState] = useState<FlowState>("idle");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);
  const [fileType, setFileType] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [extraction, setExtraction] = useState<{
    status: string | null;
    charCount: number | null;
    isDuplicate: boolean;
  } | null>(null);
  const [naming, setNaming] = useState<NamingFields | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const workflowRunRef = useRef(0);
  const pendingRequestRef = useRef(0);

  const beginWorkflowRun = useCallback(() => {
    workflowRunRef.current += 1;
    return workflowRunRef.current;
  }, []);
  const isCurrentWorkflowRun = useCallback((runId: number) => workflowRunRef.current === runId, []);

  // Path A：企微微盘待确认任务。
  const [pendingTasks, setPendingTasks] = useState<PendingIngestItemDTO[]>([]);
  // Path A is lazy-mounted. Start in loading state so the first switch cannot
  // flash an empty result before its effect begins the pending-task request.
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [selectedTaskName, setSelectedTaskName] = useState("");

  // Shared confirmation fields
  const [editTitle, setEditTitle] = useState("");
  const [editOneLiner, setEditOneLiner] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editKeyPoints, setEditKeyPoints] = useState("");
  const [llmStatus, setLlmStatus] = useState<{
    status: string | null;
    provider: string | null;
    summaryStatus: IngestAiResultDTO["summary_status"];
    generationModelRef: string | null;
  } | null>(null);
  const [desensitization, setDesensitization] = useState<{
    status: string | null;
    counts: Record<string, number> | null;
    message: string | null;
  } | null>(null);
  const [editTags, setEditTags] = useState("");
  const [editVisibility, setEditVisibility] = useState("项目内");
  const [editBizStage, setEditBizStage] = useState("行动辅导");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("personal");
  const [confirmConfidence, setConfirmConfidence] = useState("—");

  // 真实入库任务状态
  const [taskId, setTaskId] = useState<string | null>(null);
  const [resultAssetId, setResultAssetId] = useState<string | null>(null);
  const [submitReviewId, setSubmitReviewId] = useState<string | null>(null);
  const [submitIndexStatus, setSubmitIndexStatus] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [processingNote, setProcessingNote] = useState<string | null>(null);
  const [editAssetType, setEditAssetType] = useState("methodology");
  const [editConfidentiality, setEditConfidentiality] = useState("L2");
  const [editAiAccess, setEditAiAccess] = useState("A2");
  const [projects, setProjects] = useState<{ projectId: string; projectName: string }[]>([]);
  const [targetProjectId, setTargetProjectId] = useState("");

  useEffect(() => {
    return () => {
      workflowRunRef.current += 1;
      pendingRequestRef.current += 1;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  useEffect(() => {
    fetchAuthMe()
      .then((me) => {
        setProjects(
          me.projects.map((p) => ({ projectId: p.projectId, projectName: p.projectName })),
        );
        if (me.projects.length > 0) setTargetProjectId(me.projects[0].projectId);
      })
      .catch(() => setProjects([]));
  }, []);

  // 企业微信待确认：拉取当前用户可处理的待确认任务。
  const loadPending = useCallback(async () => {
    const requestId = ++pendingRequestRef.current;
    setPendingLoading(true);
    setPendingError(null);
    try {
      const tasks = await fetchPendingIngestTasks("path_a_wecom");
      if (pendingRequestRef.current !== requestId) return;
      setPendingTasks(tasks);
    } catch (e) {
      if (pendingRequestRef.current !== requestId) return;
      setPendingError(
        e instanceof ApiError ? e.message : "企业微信待确认任务暂时无法加载，请稍后重试",
      );
    } finally {
      if (pendingRequestRef.current === requestId) setPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePath === "a") void loadPending();
  }, [activePath, loadPending]);

  // 把一次 ai-result 的建议填入人工校正区（Path A / Path B 共用）。
  const applyAiResult = useCallback((ai: IngestAiResultDTO, fallbackTitle: string) => {
    setLlmStatus({
      status: ai.content_processing_status,
      provider: ai.llm_provider,
      summaryStatus: ai.summary_status,
      generationModelRef: ai.generation_model_ref,
    });
    setDesensitization({
      status: ai.desensitization_status,
      counts: ai.desensitization_counts,
      message: ai.desensitization_message,
    });
    setEditTitle(ai.suggested_title ?? fallbackTitle);
    setEditOneLiner(ai.suggested_one_liner ?? "");
    setEditSummary(ai.suggested_summary ?? "");
    setEditKeyPoints((ai.suggested_key_points ?? []).join("\n"));
    setEditTags((ai.suggested_tags ?? []).join(" · "));
    setEditAssetType(ai.suggested_asset_type ?? "methodology");
    setEditConfidentiality(ai.suggested_confidentiality_level ?? "L2");
    setEditAiAccess(ai.suggested_ai_access_level ?? "A2");
    setConfirmConfidence(ai.confidence != null ? `${Math.round(ai.confidence * 100)}%` : "—");
    setNaming(ai.naming_parsed_fields ?? null);
    setExtraction({
      status: ai.extraction_status,
      charCount: ai.extracted_char_count,
      isDuplicate: ai.is_possible_duplicate,
    });
  }, []);

  // 轮询 ai-result 至非 processing 或超时。
  const pollAiResult = useCallback(async (id: string, isCurrent: () => boolean) => {
    if (!isCurrent()) return null;
    let ai = await fetchIngestAiResult(id);
    if (!isCurrent()) return null;
    let attempts = 0;
    while (ai.status === "processing" && attempts < POLL_MAX_ATTEMPTS) {
      await sleep(POLL_INTERVAL_MS);
      if (!isCurrent()) return null;
      ai = await fetchIngestAiResult(id);
      if (!isCurrent()) return null;
      attempts += 1;
    }
    return ai;
  }, []);

  // Path A：点击真实待确认任务 → 拉取 AI 建议（与 Path B 同一 ai-result 接口）→ 填入
  // 人工校正区。处理中则轮询；失败/超时给安全提示且不可确认。
  const handleSelectPendingTask = useCallback(
    async (t: PendingIngestItemDTO) => {
      const runId = beginWorkflowRun();
      const isCurrent = () => isCurrentWorkflowRun(runId);
      setSelectedTaskName(t.source_file_name);
      setTaskId(t.id);
      setApiError(null);
      setProcessingNote(null);
      setResultAssetId(null);
      if (
        t.target_scope === "personal" ||
        t.target_scope === "project" ||
        t.target_scope === "company"
      ) {
        setTargetLibrary(t.target_scope);
      }
      if (t.target_project_id) setTargetProjectId(t.target_project_id);
      setFlowState("processing");
      try {
        const ai = await pollAiResult(t.id, isCurrent);
        if (!ai || !isCurrent()) return;
        applyAiResult(ai, t.source_file_name);
        if (ai.status === "processing") {
          setProcessingNote(
            "后台仍在处理该企微微盘文件（抽取 / LLM 内容处理），请稍后刷新重试，暂不可确认。",
          );
          setFlowState("processing");
          return;
        }
        if (ai.status === "failed") {
          setProcessingNote(
            `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重试，当前不可确认入库。`,
          );
          setFlowState("failed");
          return;
        }
        setFlowState("ready");
      } catch (e) {
        if (!isCurrent()) return;
        setApiError(e instanceof ApiError ? e.message : "加载该任务的 AI 建议失败");
        setFlowState("idle");
      }
    },
    [applyAiResult, beginWorkflowRun, isCurrentWorkflowRun, pollAiResult],
  );

  const selectLocalFile = useCallback(
    (file: File) => {
      beginWorkflowRun();
      setSelectedFile(file);
      setFileName(file.name);
      setFileSize(file.size);
      setFileType(file.name.split(".").pop()?.toUpperCase() || file.type || "未知");
      setExtraction(null);
      setNaming(null);
      setApiError(null);
      setProcessingNote(null);
      setFlowState("file_selected");
    },
    [beginWorkflowRun],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) selectLocalFile(file);
    },
    [selectLocalFile],
  );

  const handleFileDrop = useCallback(
    (file: File) => {
      selectLocalFile(file);
      if (fileRef.current) fileRef.current.value = "";
    },
    [selectLocalFile],
  );

  // Path B：上传真实文件字节 + 创建入库任务 + 异步轮询内容建议。
  const handleStart = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!selectedFile) {
      setApiError("请先选择本地文件");
      return;
    }
    setFlowState("processing");
    setApiError(null);
    setProcessingNote(null);
    try {
      const up = await createIngestUpload({ file: selectedFile });
      if (!isCurrent()) return;
      setTaskId(up.ingest_task_id);
      const ai = await pollAiResult(up.ingest_task_id, isCurrent);
      if (!ai || !isCurrent()) return;
      if (ai.status === "processing") {
        setProcessingNote(
          "后台仍在处理该上传（抽取 / LLM 内容处理），请稍后刷新重试，暂不可提交。",
        );
        setFlowState("processing");
        return;
      }
      applyAiResult(ai, fileName);
      if (ai.status === "failed") {
        setProcessingNote(
          `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重新上传，当前不可提交入库。`,
        );
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      if (!isCurrent()) return;
      setApiError(e instanceof ApiError ? e.message : "创建入库任务失败，请稍后重试");
      setFlowState("file_selected");
    }
  }, [selectedFile, fileName, applyAiResult, beginWorkflowRun, isCurrentWorkflowRun, pollAiResult]);

  // 轮询达到有限上限后，由用户显式重新检查同一真实任务，不创建伪进度或新任务。
  const handleRefreshProcessing = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!taskId) return;
    setApiError(null);
    setProcessingNote(null);
    setFlowState("processing");
    try {
      const ai = await pollAiResult(taskId, isCurrent);
      if (!ai || !isCurrent()) return;
      applyAiResult(ai, activePath === "a" ? selectedTaskName : fileName);
      if (ai.status === "processing") {
        setProcessingNote("后台仍在处理，请稍后重新检查，当前不可确认入库。");
        return;
      }
      if (ai.status === "failed") {
        setProcessingNote(
          `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。当前不可确认入库。`,
        );
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      if (!isCurrent()) return;
      setApiError(e instanceof ApiError ? e.message : "任务状态暂时无法获取，请稍后重试");
      setFlowState(activePath === "a" ? "idle" : "file_selected");
    }
  }, [
    activePath,
    applyAiResult,
    beginWorkflowRun,
    fileName,
    isCurrentWorkflowRun,
    pollAiResult,
    selectedTaskName,
    taskId,
  ]);

  // 两种来源共用同一确认链路。确认成功后展示资产链接；
  // Path A 额外刷新待确认列表。
  const handleSubmit = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!taskId) return;
    setApiError(null);
    if (targetLibrary === "project" && !targetProjectId) {
      setApiError("请选择目标项目");
      return;
    }
    try {
      const tags = editTags
        .split(/[·,，、\s]+/)
        .map((t) => t.trim())
        .filter(Boolean);
      const keyPoints = editKeyPoints
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);
      const res = await confirmIngest(taskId, {
        title: editTitle,
        one_liner: editOneLiner || undefined,
        summary: editSummary,
        key_points: keyPoints,
        tags,
        target_scope: targetLibrary,
        target_project_id: targetLibrary === "project" ? targetProjectId : undefined,
        target_zone: "material",
        asset_type: editAssetType,
        visibility: visibilityToKey[editVisibility] ?? "project_only",
        confidentiality_level: editConfidentiality,
        ai_access_level: editAiAccess,
        lifecycle_phase_key: editBizStage,
        // 仅传安全 model_ref；缺省（"" / WeKnora 未配置）则省略 → 后端走平台默认。
        embedding_model_ref: models.embeddingRef || undefined,
        rerank_model_ref: models.rerankRef || undefined,
      });
      if (!isCurrent()) return;
      setResultAssetId(res.result_asset_id);
      setSubmitReviewId(res.review_id ?? null);
      setSubmitIndexStatus(res.index_status ?? null);
      setFlowState("submitted");
      if (activePath === "a") void loadPending();
    } catch (e) {
      if (!isCurrent()) return;
      setApiError(e instanceof ApiError ? e.message : "提交入库失败");
    }
  }, [
    activePath,
    taskId,
    targetLibrary,
    targetProjectId,
    editTags,
    editTitle,
    editOneLiner,
    editSummary,
    editKeyPoints,
    editBizStage,
    editAssetType,
    editVisibility,
    editConfidentiality,
    editAiAccess,
    beginWorkflowRun,
    isCurrentWorkflowRun,
    loadPending,
    models.embeddingRef,
    models.rerankRef,
  ]);

  const handleReset = useCallback(() => {
    beginWorkflowRun();
    pendingRequestRef.current += 1;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setFlowState("idle");
    setApiError(null);
    setProcessingNote(null);
    setLlmStatus(null);
    setDesensitization(null);
    setSelectedFile(null);
    setExtraction(null);
    setNaming(null);
    setFileName("");
    setFileSize(0);
    setFileType("");
    if (fileRef.current) fileRef.current.value = "";
    setSelectedTaskName("");
    setEditTitle("");
    setEditOneLiner("");
    setEditSummary("");
    setEditKeyPoints("");
    setLlmStatus(null);
    setEditTags("");
    setEditVisibility("项目内");
    setEditBizStage("行动辅导");
    setTargetLibrary("personal");
    setConfirmConfidence("—");
    setEditAssetType("methodology");
    setEditConfidentiality("L2");
    setEditAiAccess("A2");
    setTaskId(null);
    setResultAssetId(null);
    setSubmitReviewId(null);
    setSubmitIndexStatus(null);
    setApiError(null);
  }, [beginWorkflowRun]);

  // 切换来源时清空当前流程 / 选中态，避免一处来源的校正数据残留到另一处。
  const switchPath = useCallback(
    (p: PathBranch) => {
      if (p === activePath) return;
      handleReset();
      setActivePath(p);
    },
    [activePath, handleReset],
  );

  const confirmReady = flowState === "ready";
  const requiredFieldsOk =
    editTitle.trim().length > 0 &&
    (editSummary.trim().length > 0 || editOneLiner.trim().length > 0) &&
    (targetLibrary !== "project" || targetProjectId.length > 0);
  // 平台默认嵌入或问答模型未配置时禁用提交（models.blockSubmit），不静默走 .env 兜底。
  const canSubmit = confirmReady && requiredFieldsOk && !models.blockSubmit;
  const confirmSubmitted = flowState === "submitted";
  const awaitingProjectReview = confirmSubmitted && submitReviewId !== null;
  const sourceLabel = activePath === "a" ? "企微微盘" : "本地上传";
  const sourceFile = activePath === "a" ? selectedTaskName : fileName;
  const hasFile = flowState !== "idle";

  return {
    activePath,
    switchPath,
    flowState,
    fileName,
    fileSize,
    fileType,
    hasFile,
    extraction,
    desensitization,
    naming,
    fileRef,
    handleFileSelect,
    handleFileDrop,
    handleStart,
    handleRefreshProcessing,
    handleReset,
    pendingTasks,
    pendingLoading,
    pendingError,
    loadPending,
    handleSelectPendingTask,
    taskId,
    editTitle,
    setEditTitle,
    editOneLiner,
    setEditOneLiner,
    editSummary,
    setEditSummary,
    editKeyPoints,
    setEditKeyPoints,
    editTags,
    setEditTags,
    editVisibility,
    setEditVisibility,
    editBizStage,
    setEditBizStage,
    editAssetType,
    setEditAssetType,
    editConfidentiality,
    setEditConfidentiality,
    editAiAccess,
    setEditAiAccess,
    targetLibrary,
    setTargetLibrary,
    targetProjectId,
    setTargetProjectId,
    projects,
    confirmConfidence,
    llmStatus,
    apiError,
    processingNote,
    confirmReady,
    confirmSubmitted,
    canSubmit,
    sourceLabel,
    sourceFile,
    resultAssetId,
    submitReviewId,
    awaitingProjectReview,
    submitIndexStatus,
    handleSubmit,
    models,
  };
}

export type UploadFlow = ReturnType<typeof useUploadFlow>;
